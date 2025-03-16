from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging
import json
import time
import re
from ..clients.anthropic_client import CachedAnthropicClient
from tenacity import retry, stop_after_attempt, wait_random_exponential

logger = logging.getLogger(__name__)

@dataclass
class ProcessingPhase:
    name: str
    description: str
    processor: callable
    required_fields: List[str]
    output_fields: List[str]

class ProcessingPipeline:
    def __init__(self, db, anthropic_api_key: str, db_path: str = "collected_data.db"):
        self.db = db
        self.anthropic_client = CachedAnthropicClient(
            api_key=anthropic_api_key,
            db_path=db_path
        )

        self.phases = {
            'llm_summary': ProcessingPhase(
                name='llm_summary',
                description='Generate summaries or evaluations of Klipper issues and comments using a Large Language Model',
                processor=self._process_llm_summary,
                required_fields=['klipper_issues.raw_response'],
                output_fields=['summary', 'evaluation']
            )
        }

    def process_item(self, item_id: str, skip_cache: bool = False):
        """Process a single item through the pipeline"""
        try:
            # Log cache stats at the start of processing each item
            self.anthropic_client.get_cache_stats()

            # Mark as in progress
            self.db.mark_item_in_progress(item_id)

            current_phase = self.db.get_processing_status(item_id)
            logger.info(f"Current phase: {current_phase}")
            if not current_phase:
                current_phase = 'llm_summary'

            logger.info(f"Starting processing of {item_id} from phase {current_phase}")

            while current_phase in self.phases:
                phase = self.phases[current_phase]
                logger.info(f"Processing {item_id} in phase {current_phase}")

                # Execute phase processor with skip_cache parameter
                result = phase.processor(item_id, skip_cache=skip_cache)
                logger.info(f"Result: {result}")

                # Check if result is None
                if result is None:
                    logger.warning(f"Phase {current_phase} returned None for item {item_id}, using default values")
                    # Create a default result dictionary
                    result = {
                        'valid_sections': [],
                        'invalid_sections': [],
                        'parsing_errors': [],
                        'analysis': {},
                        'is_config_issue': False,
                        'relevance_score': 0,
                        'full_response': None
                    }

                # Check if analysis is empty and this is the extraction phase
                if current_phase == 'llm_summary' and (not result.get('analysis') or result.get('analysis') == {}):
                    logger.warning(f"Empty analysis result for {item_id} in extraction phase, attempting to improve")
                    # Try to improve the analysis with a more focused prompt
                    improved_result = self._attempt_improved_analysis(item_id)
                    if improved_result and improved_result.get('analysis'):
                        result['analysis'] = improved_result['analysis']
                        logger.info(f"Successfully improved analysis for {item_id}")

                # Store the result in the new analysis_results table
                self.db.store_analysis_result(
                    item_id=item_id,
                    valid_sections=result.get('valid_sections', []),
                    invalid_sections=result.get('invalid_sections', []),
                    parsing_errors=result.get('parsing_errors', []),
                    analysis=result.get('analysis', {}),
                    is_config_issue=result.get('is_config_issue', False),
                    relevance_score=result.get('relevance_score', 0)
                )

                # Update status
                self.db.update_processing_status(
                    item_id=item_id,
                    current_phase=current_phase,
                    metadata=result
                )

                # Move to next phase
                current_phase = self._get_next_phase(current_phase)

            logger.info(f"Completed processing of {item_id}")

            # If successful:
            self.db.mark_item_completed(item_id)

        except Exception as e:
            logger.error(f"Error processing {item_id}: {e}", exc_info=True)
            self.db.update_processing_status(
                item_id=item_id,
                error=str(e)
            )
            self.db.mark_item_failed(item_id, str(e))  # Mark as failed with error message
            raise

    def _get_next_phase(self, current_phase: str) -> Optional[str]:
        """Determine the next processing phase"""
        phases = list(self.phases.keys())
        try:
            current_idx = phases.index(current_phase)
            return phases[current_idx + 1] if current_idx + 1 < len(phases) else None
        except ValueError:
            return None

    def _process_llm_summary(self, item_id: str, skip_cache: bool = False) -> Dict[str, Any]:
        """
        Extract and validate Klipper config sections using an LLM
        """
        try:
            # Fetch the raw content and comments
            issues = self.db.get_issues(item_id)
            comments = self.db.get_comments(item_id)
            attachments = self.db.get_issue_attachments(item_id)

            # Log the fetched data for debugging
            logger.debug(f"Fetched issues for item {item_id}: {issues}")
            logger.debug(f"Fetched comments for item {item_id}: {comments}")
            logger.debug(f"Fetched attachments for item {item_id}: {attachments}")

            if not issues:
                logger.error(f"No content found for item {item_id}")
                return {
                    'valid_sections': [],
                    'invalid_sections': [],
                    'parsing_errors': [{"line": "", "error": "No content found", "suggestion": "Ensure the item exists in the database"}],
                    'analysis': {"root_cause": "Missing content", "impact": "Cannot analyze", "fix_description": "Add content to the database"},
                    'is_config_issue': False,
                    'relevance_score': 0,
                    'full_response': None
                }

            # Extract content from issues
            raw_content = ""
            for issue in issues:
                content = issue.get('content', '')
                metadata = json.loads(issue.get('metadata', '{}'))
                title = metadata.get('title', '')
                raw_content += f"Title: {title}\n\n{content}\n\n"

            # Process comments
            processed_comments = []
            for comment in comments:
                if isinstance(comment, dict):
                    comment_content = comment.get('content', '')
                    author = comment.get('author', '')
                    processed_comments.append(f"Author: {author}\n{comment_content}")
                else:
                    processed_comments.append(str(comment))

            # Process attachments
            processed_attachments = []
            for attachment in attachments:
                if isinstance(attachment, dict):
                    filename = attachment.get('filename', '')
                    content = attachment.get('content', '')
                    processed_attachments.append(f"File: {filename}\n{content}")
                else:
                    processed_attachments.append(str(attachment))

            # Check total size and truncate if necessary
            total_size = (
                len(raw_content.encode('utf-8')) +
                sum(len(comment.encode('utf-8')) for comment in processed_comments) +
                sum(len(attachment.encode('utf-8')) for attachment in processed_attachments)
            )

            max_size = 9000000  # Maximum allowed size in bytes
            if total_size > max_size:
                logger.warning(f"Total input size {total_size} bytes exceeds limit of {max_size} bytes. Truncating...")
                # Truncate content to fit the limit
                raw_content = raw_content[:max_size // 3]  # Adjust as needed
                processed_comments = processed_comments[:5]  # Keep only the first 5 comments
                processed_attachments = processed_attachments[:5]  # Keep only the first 5 attachments

            # Prepare data for LLM
            input_data = {
                "content": raw_content,
                "comments": processed_comments,
                "attachments": processed_attachments
            }

            # Call the LLM, skipping cache if specified
            llm_result = self._call_llm(item_id, input_data, skip_cache)
            llm_response = llm_result["parsed_json"]
            full_response = llm_result["full_response"]

            # Parse LLM response
            valid_sections = llm_response.get('valid_sections', [])
            invalid_sections = llm_response.get('invalid_sections', [])
            parsing_errors = llm_response.get('parsing_errors', [])
            analysis = llm_response.get('analysis', {})
            is_config_issue = llm_response.get('is_config_issue', False)
            relevance_score = llm_response.get('relevance_score', 0)

            return {
                'valid_sections': valid_sections,
                'invalid_sections': invalid_sections,
                'parsing_errors': parsing_errors,
                'analysis': analysis,
                'is_config_issue': is_config_issue,
                'relevance_score': relevance_score,
                'full_response': full_response
            }

        except Exception as e:
            logger.error(f"Error in process_llm_summary phase for item {item_id}: {e}", exc_info=True)
            return {
                'valid_sections': [],
                'invalid_sections': [],
                'parsing_errors': [{"line": "", "error": f"Processing error: {str(e)}", "suggestion": "Check logs for details"}],
                'analysis': {"root_cause": "Processing error", "impact": "Cannot analyze", "fix_description": f"Fix error: {str(e)}"},
                'is_config_issue': False,
                'relevance_score': 0,
                'full_response': None
            }

    def _sanitize_json_string(self, json_string: str) -> str:
        """Sanitize the JSON string by escaping control characters."""
        # Replace unescaped control characters with their escaped versions
        return re.sub(r'[\x00-\x1F\x7F]', '', json_string)  # Remove control characters

    def _extract_json_from_text(self, text: str) -> Optional[Dict]:
        """Extract and parse JSON from text that may contain additional content"""
        # Look for content between curly braces, handling nested structures
        def find_matching_brace(s: str, start: int) -> int:
            count = 0
            for i in range(start, len(s)):
                if s[i] == '{':
                    count += 1
                elif s[i] == '}':
                    count -= 1
                    if count == 0:
                        return i
            return -1

        # Find all potential JSON objects
        i = 0
        while i < len(text):
            try:
                # Find the start of a JSON object
                start = text.find('{', i)
                if start == -1:
                    break

                # Find the matching closing brace
                end = find_matching_brace(text, start)
                if end == -1:
                    break

                # Extract the potential JSON string
                json_str = text[start:end + 1]

                # Try to parse it
                parsed = json.loads(json_str)

                # Verify it has our expected structure
                if any(key in parsed for key in ['is_config_issue', 'analysis', 'relevance_score']):
                    return parsed

                # Move to the next position
                i = end + 1

            except json.JSONDecodeError:
                # If parsing fails, move to the next character
                i += 1
                continue

        return None

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(6))
    def _call_llm(self, item_id: str, input_data: Dict[str, Any], skip_cache: bool = False) -> Dict[str, Any]:
        """
        Call the Anthropic Claude LLM with the provided input data and return the response.
        First checks if we already have a response for this item in the database.
        """
        try:
            # Check if we already have a response in the database unless skipping cache
            if not skip_cache:
                existing_response = self.db.get_llm_request(item_id)
                if existing_response:
                    logger.info(f"Found existing LLM response for item {item_id}, reusing...")
                    full_response = existing_response['full_response']
                    parsed_json = self._extract_json_from_text(full_response)

                    if parsed_json is not None:
                        return {"parsed_json": parsed_json, "full_response": full_response}
                    else:
                        logger.warning(f"Could not parse JSON from existing response for item {item_id}, will make new request")
            else:
                logger.info(f"Skipping cache for item {item_id}, making new request")

            # First truncate the content
            content = input_data.get("content", "")
            comments = input_data.get("comments", [])
            attachments = input_data.get("attachments", [])

            # Calculate sizes
            content_chars = len(content)
            comments_chars = sum(len(str(c)) for c in comments)
            attachments_chars = sum(len(str(a)) for a in attachments)
            total_chars = content_chars + comments_chars + attachments_chars

            # Estimate base prompt size (template, instructions, etc.) - roughly 2000 tokens or 8000 chars
            base_prompt_chars = 8000
            # Target total size (leaving room for base prompt and model response)
            max_total_chars = 150000 * 4  # 150k tokens ≈ 600k chars
            max_content_chars = max_total_chars - base_prompt_chars

            logger.debug(f"Initial sizes - Content: {content_chars}, Comments: {comments_chars}, Attachments: {attachments_chars}")

            if total_chars > max_content_chars:
                # Calculate proportions with minimum guarantees
                content_weight = 0.4  # 40% for main content
                comments_weight = 0.3  # 30% for comments
                attachments_weight = 0.3  # 30% for attachments

                # Calculate maximum chars for each section
                max_content_section = int(max_content_chars * content_weight)
                max_comments_section = int(max_content_chars * comments_weight)
                max_attachments_section = int(max_content_chars * attachments_weight)

                # Ensure minimum sizes for comments and attachments
                min_chars_per_item = 500
                min_items = 3

                # Truncate content
                if len(content) > max_content_section:
                    content = content[:max_content_section]
                    logger.warning(f"Truncated content from {content_chars} to {len(content)} characters")

                # Truncate comments while ensuring minimum representation
                if comments_chars > max_comments_section:
                    truncated_comments = []
                    chars_so_far = 0

                    # Always include at least min_items comments if available
                    for i, comment in enumerate(comments[:min_items]):
                        comment_str = str(comment)
                        if len(comment_str) > min_chars_per_item:
                            comment_str = comment_str[:min_chars_per_item] + "... [truncated]"
                        truncated_comments.append(comment_str)
                        chars_so_far += len(comment_str)

                    # Add more comments if space allows
                    for comment in comments[min_items:]:
                        comment_str = str(comment)
                        if chars_so_far + len(comment_str) <= max_comments_section:
                            if len(comment_str) > min_chars_per_item:
                                comment_str = comment_str[:min_chars_per_item] + "... [truncated]"
                            truncated_comments.append(comment_str)
                            chars_so_far += len(comment_str)
                        else:
                            break

                    comments = truncated_comments
                    logger.warning(f"Truncated comments from {len(input_data['comments'])} to {len(comments)} items")

                # Truncate attachments while ensuring minimum representation
                if attachments_chars > max_attachments_section:
                    truncated_attachments = []
                    chars_so_far = 0

                    # Always include at least min_items attachments if available
                    for i, attachment in enumerate(attachments[:min_items]):
                        attachment_str = str(attachment)
                        if len(attachment_str) > min_chars_per_item:
                            attachment_str = attachment_str[:min_chars_per_item] + "... [truncated]"
                        truncated_attachments.append(attachment_str)
                        chars_so_far += len(attachment_str)

                    # Add more attachments if space allows
                    for attachment in attachments[min_items:]:
                        attachment_str = str(attachment)
                        if chars_so_far + len(attachment_str) <= max_attachments_section:
                            if len(attachment_str) > min_chars_per_item:
                                attachment_str = attachment_str[:min_chars_per_item] + "... [truncated]"
                            truncated_attachments.append(attachment_str)
                            chars_so_far += len(attachment_str)
                        else:
                            break

                    attachments = truncated_attachments
                    logger.warning(f"Truncated attachments from {len(input_data['attachments'])} to {len(attachments)} items")

                # Create new truncated input data
                input_data = {
                    "content": content,
                    "comments": comments,
                    "attachments": attachments,
                    "focus_on_analysis": input_data.get("focus_on_analysis", False)
                }

            # Prepare the prompt with truncated data
            prompt = self._create_prompt(input_data)

            # Final size check
            if len(prompt.encode('utf-8')) > 750000:  # Roughly 187.5k tokens
                logger.warning("Prompt still too large after truncation, performing emergency truncation")
                prompt = prompt[:750000] + "\n\n[Content truncated due to length]\n"

            messages = [{"role": "user", "content": prompt}]

            # Make the API request using the Anthropic client
            message = self.anthropic_client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=4096,
                messages=messages
            )
            logger.debug(f"LLM response: {message}")

            # Extract the full response text from the message object
            full_response = message.content[0].text if message.content else ""

            # Sanitize the full response
            sanitized_response = self._sanitize_json_string(full_response)

            # Store the LLM request and response data
            self.db.store_llm_data(
                item_id=item_id,
                request_data=json.dumps(messages),
                full_response=sanitized_response
            )

            # Try to extract and parse JSON from the response
            parsed_json = self._extract_json_from_text(sanitized_response)
            if parsed_json is not None:
                return {"parsed_json": parsed_json, "full_response": sanitized_response}

            logger.error(f"Could not find valid JSON in response: {sanitized_response}")
            raise ValueError("Could not extract valid JSON from LLM response")

        except Exception as e:
            logger.error(f"Error in _call_llm for item {item_id}: {e}", exc_info=True)
            raise

    def _create_prompt(self, input_data: Dict[str, Any]) -> str:
        """
        Create a prompt for the LLM to analyze Klipper configuration issues
        """
        content = input_data.get("content", "")
        comments = input_data.get("comments", [])
        attachments = input_data.get("attachments", [])
        focus_on_analysis = input_data.get("focus_on_analysis", False)

        if focus_on_analysis:
            # More focused prompt specifically for analysis
            prompt = """You are an expert in Klipper 3D printer configurations and firmware. Your task is to analyze the following GitHub issue, its comments, and any configuration attachments to determine the root cause of the problem and suggest a solution.

Please focus specifically on providing a detailed analysis of the configuration issue.

ISSUE CONTENT:
-------------
{content}

COMMENTS:
---------
{comments}

ATTACHMENTS:
-----------
{attachments}

Please provide your analysis in the following JSON format:

{{
    "is_config_issue": boolean,  // Whether this is a configuration-related issue
    "analysis": {{              // Detailed analysis of the issue
        "root_cause": string,   // Root cause of the problem
        "impact": string,       // What problems this causes for the user
        "fix_description": string,  // How to fix the issue
        "proposed_lint_rule": {{    // Suggestion for a lint rule
            "rule_name": string,
            "rule_description": string,
            "detection_pattern": string,
            "severity": "error|warning|info"
        }}
    }},
    "relevance_score": number   // 0-1 score indicating how relevant this issue is for linting
}}

Focus on providing a thorough analysis of the configuration issue, even if you're not certain about all details."""
        else:
            # Original comprehensive prompt
            prompt = """You are an expert in Klipper 3D printer configurations and firmware. Your task is to analyze the following GitHub issue, its comments, and any configuration attachments to determine if there's a configuration-related problem that could be prevented through linting rules.

Please analyze the following content and provide a structured response:

ISSUE CONTENT:
-------------
{content}

COMMENTS:
---------
{comments}

ATTACHMENTS:
-----------
{attachments}

Please provide your analysis in the following JSON format:

{{
    "is_config_issue": boolean,  // Whether this is a configuration-related issue
    "valid_sections": [          // List of valid config sections found
        {{
            "section_name": string,
            "parameters": {{
                "param_name": "param_value"
            }}
        }}
    ],
    "invalid_sections": [        // List of problematic config sections
        {{
            "section_name": string,
            "parameters": {{
                "param_name": "param_value"
            }},
            "error_type": string,
            "error_description": string
        }}
    ],
    "parsing_errors": [          // Any syntax or parsing errors found
        {{
            "line": string,
            "error": string,
            "suggestion": string
        }}
    ],
    "analysis": {{              // Detailed analysis if this is a config issue
        "root_cause": string,   // Root cause of the problem
        "impact": string,       // What problems this causes for the user
        "fix_description": string,  // How to fix the issue
        "proposed_lint_rule": {{    // Suggestion for a lint rule
            "rule_name": string,
            "rule_description": string,
            "detection_pattern": string,
            "severity": "error|warning|info"
        }}
    }},
    "relevance_score": number   // 0-1 score indicating how relevant this issue is for linting
}}

Focus on identifying patterns that could be detected through static analysis of the configuration file. If this is not a configuration-related issue, set is_config_issue to false and leave other fields empty."""

        return prompt.format(
            content=content,
            comments="\n".join(str(comment) for comment in comments),
            attachments="\n".join(str(attachment) for attachment in attachments)
        )

    def _attempt_improved_analysis(self, item_id: str) -> Dict[str, Any]:
        """Attempt to get a better analysis using a more focused prompt"""
        try:
            # Fetch the raw content, comments, and attachments from the database
            raw_content = self.db.get_issues(item_id)
            comments = self.db.get_comments(item_id)
            attachments = self.db.get_issue_attachments(item_id)

            if not raw_content:
                logger.error(f"No content found for item {item_id} during improved analysis attempt")
                return None

            # Prepare a more focused prompt specifically for analysis
            input_data = {
                "content": raw_content,
                "comments": comments,
                "attachments": attachments,
                "focus_on_analysis": True  # Flag to use a more focused prompt
            }

            # Call the LLM with the focused prompt
            llm_result = self._call_llm(item_id, input_data)
            # Return both the parsed JSON and full response
            return llm_result["parsed_json"]

        except Exception as e:
            logger.error(f"Error in improved analysis attempt for item {item_id}: {e}", exc_info=True)
            return None
