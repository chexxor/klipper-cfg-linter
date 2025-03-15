from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging
import json
import time
import re
from ..clients.anthropic_client import CachedAnthropicClient

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
            'llm_summary_github': ProcessingPhase(
                name='llm_summary_github',
                description='Generate summaries or evaluations of GitHub issues and comments using a Large Language Model',
                processor=self._process_llm_summary,
                required_fields=['klipper_issues.raw_response'],
                output_fields=['summary', 'evaluation']
            )
        }

    def process_item(self, item_id: str, source_type: str):
        """Process a single item through the pipeline"""
        try:
            # Log cache stats at the start of processing each item
            self.anthropic_client.get_cache_stats()

            # Mark as in progress
            self.db.mark_item_in_progress(item_id)

            current_phase = self.db.get_processing_status(item_id)
            if not current_phase:
                current_phase = 'llm_summary_github'

            logger.info(f"Starting processing of {item_id} from phase {current_phase}")

            while current_phase in self.phases:
                phase = self.phases[current_phase]
                logger.info(f"Processing {item_id} in phase {current_phase}")

                # Execute phase processor
                result = phase.processor(item_id)

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
                if current_phase == 'llm_summary_github' and (not result.get('analysis') or result.get('analysis') == {}):
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
                    source_type=source_type,
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

    def _process_llm_summary(self, item_id: str) -> Dict[str, Any]:
        """
        Extract and validate Klipper config sections using an LLM
        """
        try:
            # Fetch the raw content and comments
            raw_content = self.db.get_issues(item_id)
            comments = self.db.get_comments(item_id)

            # Fetch attachments from the new table
            attachments = self.db.get_issue_attachments(item_id)

            # Log the fetched data for debugging
            logger.debug(f"Fetched raw content for item {item_id}: {raw_content}")
            logger.debug(f"Fetched comments for item {item_id}: {comments}")
            logger.debug(f"Fetched attachments for item {item_id}: {attachments}")

            if not raw_content:
                logger.error(f"No content found for item {item_id}")
                # Return a default result instead of raising an exception
                return {
                    'valid_sections': [],
                    'invalid_sections': [],
                    'parsing_errors': [{"line": "", "error": "No content found", "suggestion": "Ensure the item exists in the database"}],
                    'analysis': {"root_cause": "Missing content", "impact": "Cannot analyze", "fix_description": "Add content to the database"},
                    'is_config_issue': False,
                    'relevance_score': 0,
                    'full_response': None
                }

            # Prepare data for LLM
            input_data = {
                "content": raw_content,
                "comments": comments,
                "attachments": attachments
            }

            # Call the LLM
            llm_result = self._call_llm(item_id, input_data)
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
            # Return a default result instead of re-raising the exception
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

    def _call_llm(self, item_id: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call the Anthropic Claude LLM with the provided input data and return the response.
        First checks if we already have a response for this item in the database.
        """
        try:
            # Check if we already have a response in the database
            existing_response = self.db.get_llm_request(item_id)
            if existing_response:
                logger.info(f"Found existing LLM response for item {item_id}, reusing...")

                # Parse the existing response
                full_response = existing_response['full_response']
                parsed_json = self._extract_json_from_text(full_response)

                if parsed_json is not None:
                    return {"parsed_json": parsed_json, "full_response": full_response}
                else:
                    logger.warning(f"Could not parse JSON from existing response for item {item_id}, will make new request")
            else:
                logger.debug(f"No existing LLM response found for item {item_id}, making new request")

            # If we don't have a valid existing response, proceed with making a new request
            max_retries = 5
            retry_delay = 1

            for attempt in range(max_retries):
                try:
                    # Prepare the prompt
                    prompt = self._create_prompt(input_data)
                    messages = [
                        {"role": "user", "content": prompt}
                    ]

                    # Check the token count
                    token_count = len(prompt.split())  # Simple token count based on whitespace
                    max_tokens = 200000  # Maximum allowed tokens

                    if token_count > max_tokens:
                        logger.warning(f"Prompt is too long: {token_count} tokens > {max_tokens} maximum. Truncating...")
                        # Truncate the prompt to the maximum allowed length
                        prompt = ' '.join(prompt.split()[:max_tokens])  # Keep only the first max_tokens words

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

                    # If we couldn't find valid JSON, log the response and raise an error
                    logger.error(f"Could not find valid JSON in response: {sanitized_response}")
                    raise ValueError("Could not extract valid JSON from LLM response")

                except Exception as e:
                    logger.error(f"Error calling LLM: {e}", exc_info=True)
                    if attempt < max_retries - 1:
                        logger.info(f"Retrying LLM call (attempt {attempt + 2}/{max_retries})...")
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    raise

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
