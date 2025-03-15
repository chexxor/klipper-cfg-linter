from typing import List, Dict, Any, Optional, Tuple
import requests
from datetime import datetime, timedelta
import logging
import re
from dataclasses import dataclass
from klipperlint.mining.storage.database import Database
import json
from requests_cache import CachedSession
from urllib.parse import urlparse
from pathlib import Path
import hashlib

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ConfigIssueData:
    config: str
    problem_description: str
    labels: List[str]
    resolution: Optional[str]  # From comments marking as resolved
    error_messages: List[str]  # Extracted error messages
    issue_url: str  # For reference
    source_type: str = "inline"  # "inline" or "attachment"
    attachment_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary"""
        return {
            "config": self.config,
            "problem_description": self.problem_description,
            "labels": self.labels,
            "resolution": self.resolution,
            "error_messages": self.error_messages,
            "issue_url": self.issue_url,
            "source_type": self.source_type,
            "attachment_url": self.attachment_url
        }

class GitHubCollector:
    def __init__(self, token: str, db: Database):
        self.token = token
        self.db = db
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        # https://requests-cache.readthedocs.io/en/stable/modules/requests_cache.session.html#requests_cache.session.CachedSession
        self.session = CachedSession(
            db.db_path,
            backend='sqlite',
            expire_after=timedelta(hours=24),
            allowable_methods=('GET',)
        )
        self.session.headers.update(self.headers)
        self.base_url = "https://api.github.com"

    def _make_request(self, url: str, params: Dict[str, Any] = None) -> requests.Response:
        """Make a GET request to GitHub API with logging and caching"""
        logger.info(f"Making GitHub API request: GET {url}")
        logger.info(f"Request params: {params}")
        logger.info(f"Request headers: {self.headers}")

        response = self.session.get(url, params=params)

        logger.info(f"Cache {'hit' if response.from_cache else 'miss'} for: {url}")
        logger.info(f"Response status: {response.status_code}")
        logger.info(f"Rate limit remaining: {response.headers.get('X-RateLimit-Remaining')}")

        try:
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}", exc_info=True)
            logger.error(f"Response content: {response.text}", exc_info=True)
            raise

        return response

    def _get_paginated_data(self, url: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """Generic method to fetch all paginated data from a GitHub API endpoint."""
        all_data = []
        params = params or {}
        params["per_page"] = params.get("per_page", 100)

        while True:
            try:
                response = self._make_request(url, params)
                page_data = response.json()

                # Handle empty response
                if not page_data:
                    break

                # Some endpoints return arrays directly, others nested in objects
                if isinstance(page_data, dict):
                    # Extract the items array from the response object
                    # Remove known metadata fields
                    for key in ["total_count", "incomplete_results"]:
                        page_data.pop(key, None)
                    # Get the remaining array (should be only one key left)
                    page_data = list(page_data.values())[0]

                all_data.extend(page_data)

                # Check for next page in Link header (using lowercase 'link' as per GitHub docs)
                if 'link' not in response.headers:
                    break

                next_url = self._get_next_link(response.headers['link'])
                if not next_url:
                    break

                # Update URL and clear params since they're included in next_url
                url = next_url
                params = {}

            except Exception as e:
                logger.error(f"Failed to fetch paginated data from {url}: {e}", exc_info=True)
                raise

        return all_data

    def collect_issues(self, since: datetime = None) -> List[Dict[str, Any]]:
        """Collect raw issues from GitHub API"""
        params = {
            "per_page": 100,
            "state": "all"
        }
        if since:
            params["since"] = since.isoformat()

        url = f"{self.base_url}/repos/Klipper3d/klipper/issues"
        issues = self._get_paginated_data(url, params)
        logger.info(f"Found {len(issues)} issues")

        # Store basic issue data and process attachments
        for issue in issues:
            issue_id = str(issue['number'])

            # 1. Store issue
            self.db.store_issue(
                issue_id=issue_id,
                source="github",
                content=issue.get("body") or "",
                created_at=datetime.fromisoformat(issue["created_at"].rstrip('Z')),
                metadata={
                    "title": issue["title"],
                    "url": issue["html_url"],
                    "labels": [l["name"] for l in issue["labels"]],
                    "state": issue["state"],
                    "comments_count": issue.get("comments", 0),
                    "number": issue["number"],
                    "updated_at": issue["updated_at"]
                },
                raw_response=issue
            )

            # 2. Queue issue for processing
            self.db.queue_for_processing(
                item_id=issue_id,
                source_type='issue'
            )

            # 3. Process attachments from issue body
            self._process_attachments(issue_id, issue.get('body') or "")

        # 4. Collect and process comments (including their attachments)
        self.collect_issue_comments(issues)

        return issues

    def collect_issue_comments(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collect comments for a list of issues"""
        params = {
            "per_page": 100
        }
        for issue in issues:
            issue_id = str(issue['number'])
            logger.info(f"Collecting comments for issue {issue_id}")
            if 'comments' in issue and issue['comments'] > 0:
                logger.info(f"Collecting {issue['comments']} comments for issue #{issue_id}")

                comments = self._get_paginated_data(issue['comments_url'], params)

                for comment in comments:
                    comment_id = str(comment['id'])

                    # 1. Store comment
                    self.db.store_comment(
                        comment_id=comment_id,
                        issue_id=issue_id,
                        author=comment['user']['login'],
                        created_at=datetime.fromisoformat(comment['created_at'].rstrip('Z')),
                        content=comment.get('body') or "",
                        metadata={
                            "url": comment["html_url"],
                            "updated_at": comment["updated_at"],
                            "author_association": comment["author_association"]
                        },
                        raw_response=comment
                    )

                    # 2. Queue comment for processing
                    self.db.queue_for_processing(
                        item_id=f"{issue_id}_{comment_id}",
                        source_type='comment'
                    )

                    # 3. Process attachments from comment
                    self._process_attachments(issue_id, comment.get('body') or "")

    def _get_next_link(self, link_header: str) -> Optional[str]:
        """Extract the next page URL from the Link header

        Example header:
        <https://api.github.com/repositories/1300192/issues?page=2>; rel="prev",
        <https://api.github.com/repositories/1300192/issues?page=4>; rel="next",
        <https://api.github.com/repositories/1300192/issues?page=515>; rel="last",
        <https://api.github.com/repositories/1300192/issues?page=1>; rel="first"
        """
        # Split the header into individual links
        links = link_header.split(", ")

        # Look for the link with rel="next"
        for link in links:
            if 'rel="next"' in link:
                # Extract URL between < and >; more precise pattern
                url_match = re.search(r'<([^>]+)>; rel="next"', link)
                if url_match:
                    return url_match.group(1)
        return None

    def _fetch_attachment_content(self, url: str) -> Optional[str]:
        """Fetch content of a text file attachment"""
        try:
            logger.info(f"Fetching attachment from: {url}")
            response = self._make_request(url)
            return response.text
        except Exception as e:
            logger.error(f"Failed to fetch attachment {url}: {e}", exc_info=True)
            return None

    def fetch_all_issues(self):
        """Fetch all issues from GitHub and store them in the database."""
        url = f"{self.base_url}/repos/Klipper3d/klipper/issues"
        issues = self._get_paginated_data(url, {"state": "all", "per_page": 100})

        for issue in issues:
            try:
                # Store basic issue data
                self.db.store_issue(
                    issue_id=str(issue['number']),
                    source="github",
                    content=issue.get("body") or "",
                    created_at=datetime.fromisoformat(issue["created_at"].rstrip('Z')),
                    metadata={
                        "title": issue["title"],
                        "url": issue["html_url"],
                        "labels": [l["name"] for l in issue["labels"]],
                        "state": issue["state"],
                        "comments_count": issue.get("comments", 0),
                        "number": issue["number"],
                        "updated_at": issue["updated_at"]
                    },
                    raw_response=issue
                )

            except Exception as e:
                logger.error(f"Failed to process issue {issue.get('number', 'unknown')}: {e}", exc_info=True)

    def _process_attachments(self, issue_id: str, content: str):
        """Process and store attachments from content"""
        try:
            logger.info(f"Starting attachment processing for issue {issue_id}")
            attachments_found = 0

            # Extract code blocks
            logger.debug(f"Searching for code blocks in issue {issue_id}")
            code_blocks = list(re.finditer(r'```([^\n]*)\n(.*?)```', content, re.DOTALL))
            logger.info(f"Found {len(code_blocks)} code blocks in issue {issue_id}")

            for i, match in enumerate(code_blocks):
                language = match.group(1).strip().lower()
                block_content = match.group(2).strip()

                logger.debug(f"Processing code block {i+1}/{len(code_blocks)} in issue {issue_id}")
                logger.debug(f"Code block language: '{language}'")

                if self._is_likely_config(block_content, language):
                    filename = f"code_block_{i + 1}.cfg"
                    logger.info(f"Found Klipper config in code block: issue {issue_id}, {filename}")
                    logger.debug(f"Config content length: {len(block_content)} characters")

                    try:
                        self.db.store_issue_attachment(
                            issue_id=issue_id,
                            filename=filename,
                            content=block_content,
                            source_type='code_block'
                        )
                        attachments_found += 1
                        logger.info(f"Successfully stored code block attachment: {filename} for issue {issue_id}")
                    except Exception as e:
                        logger.error(f"Failed to store code block attachment for issue {issue_id}: {e}", exc_info=True)
                else:
                    logger.debug(f"Code block {i+1} in issue {issue_id} does not appear to be a Klipper config")

            # Extract file links
            logger.debug(f"Searching for config file links in issue {issue_id}")
            file_patterns = [
                (r'https://raw\.githubusercontent\.com/[^\s\)\"\']+\.cfg', 'github_raw'),
                (r'https://gist\.githubusercontent\.com/[^\s\)\"\']+\.cfg', 'gist'),
                (r'https://pastebin\.com/[^\s\)\"\']+', 'pastebin'),
                (r'https://github\.com/[^\s\)\"\']+/blob/[^\s\)\"\']+\.cfg', 'github_blob')
            ]

            for pattern, source in file_patterns:
                logger.debug(f"Searching for {source} links in issue {issue_id}")
                matches = list(re.finditer(pattern, content))
                logger.info(f"Found {len(matches)} {source} links in issue {issue_id}")

                for match in matches:
                    url = match.group(0)
                    logger.info(f"Processing {source} URL: {url} for issue {issue_id}")

                    # Convert GitHub blob URLs to raw URLs
                    if source == 'github_blob':
                        original_url = url
                        url = url.replace('github.com', 'raw.githubusercontent.com').replace('/blob/', '/')
                        logger.debug(f"Converted blob URL from {original_url} to {url}")

                    try:
                        logger.debug(f"Fetching content from URL: {url}")
                        file_content = self._fetch_file_content(url)

                        if file_content:
                            logger.debug(f"Successfully fetched content from {url} (length: {len(file_content)})")

                            if self._is_likely_config(file_content):
                                filename = self._get_filename_from_url(url)
                                logger.info(f"Found Klipper config at URL: issue {issue_id}, {filename} ({url})")

                                try:
                                    self.db.store_issue_attachment(
                                        issue_id=issue_id,
                                        filename=filename,
                                        content=file_content,
                                        url=url,
                                        source_type=source
                                    )
                                    attachments_found += 1
                                    logger.info(f"Successfully stored URL attachment: {filename} for issue {issue_id}")
                                except Exception as e:
                                    logger.error(f"Failed to store URL attachment for issue {issue_id}: {e}", exc_info=True)
                            else:
                                logger.debug(f"Content from {url} does not appear to be a Klipper config")
                        else:
                            logger.warning(f"No content retrieved from URL: {url}")

                    except Exception as e:
                        logger.error(f"Error fetching file from {url} for issue {issue_id}: {e}", exc_info=True)

            logger.info(f"Completed attachment processing for issue {issue_id}. Found {attachments_found} attachments.")

        except Exception as e:
            logger.error(f"Error processing attachments for issue {issue_id}: {e}", exc_info=True)

    def _is_likely_config(self, content: str, language: str = "") -> bool:
        """Check if the content looks like a Klipper config"""
        logger.debug(f"Checking if content is likely a Klipper config (language: '{language}')")

        # If language is specified as 'cfg' or similar, it's likely a config
        if language in ['cfg', 'config', 'klipper', 'printer']:
            logger.debug(f"Identified as config by language: {language}")
            return True

        # Look for common Klipper config sections
        common_sections = [
            '[printer]', '[stepper', '[extruder]', '[heater_bed]',
            '[fan]', '[bed_mesh]', '[bltouch]', '[probe]'
        ]

        # Check for presence of common sections
        for section in common_sections:
            if section in content:
                logger.debug(f"Identified as config by section: {section}")
                return True

        # Check for common Klipper config patterns
        patterns = [
            r'\[.*\]',  # Any section headers
            r'pin:',    # Pin configurations
            r'step_pin:', # Stepper configurations
            r'rotation_distance:' # Common Klipper parameter
        ]

        for pattern in patterns:
            if re.search(pattern, content):
                logger.debug(f"Identified as config by pattern: {pattern}")
                return True

        logger.debug("Content does not appear to be a Klipper config")
        return False

    def _fetch_file_content(self, url: str) -> Optional[str]:
        """Fetch content from a URL with appropriate handling for different services"""
        try:
            # Use the cached session from the collector
            response = self.session.get(url, timeout=10)
            response.raise_for_status()

            # Handle Pastebin links
            if 'pastebin.com' in url:
                if '/raw/' not in url:
                    # Convert to raw URL if needed
                    url = url.replace('pastebin.com/', 'pastebin.com/raw/')
                    response = self.session.get(url, timeout=10)
                    response.raise_for_status()

            return response.text

        except Exception as e:
            logger.error(f"Failed to fetch content from {url}: {e}", exc_info=True)
            return None

    def _get_filename_from_url(self, url: str) -> str:
        """Extract or generate a filename from a URL"""
        # Try to get the filename from the URL
        parsed_url = urlparse(url)
        path = Path(parsed_url.path)

        if path.name and path.suffix:
            return path.name

        # Generate a filename using the URL hash if no valid filename found
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"config_{url_hash}.cfg"
