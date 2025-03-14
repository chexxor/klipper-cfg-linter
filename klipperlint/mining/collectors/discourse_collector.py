from typing import List, Dict, Any, Optional
import requests
from datetime import datetime, timedelta, timezone
import logging
import re
from dataclasses import dataclass
from klipperlint.mining.storage.database import Database
import json
from requests_cache import CachedSession
from urllib.parse import urlparse, urlencode, unquote_plus
from pathlib import Path
import hashlib
import time
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for rate limiting and retries
MAX_RETRIES = 5
RETRY_BACKOFF_FACTOR = 2
RETRY_STATUS_FORCELIST = [429, 500, 502, 503, 504]
REQUEST_DELAY = 1.0  # Delay between requests in seconds
DEFAULT_PAGE_LIMIT = 2  # Default to 2 pages

@dataclass
class CategoryData:
    """Data class for Discourse categories"""
    topic_url: Optional[str] = None
    topic_template: Optional[str] = None
    parent_category_id: Optional[int] = None
    sort_order: Optional[int] = None

    def __str__(self) -> str:
        """String representation of the category"""
        return f"Category (URL: {self.topic_url})"

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> 'CategoryData':
        """Create CategoryData from JSON response"""
        return cls(
            topic_url=data.get('topic_url'),
            topic_template=data.get('topic_template'),
            parent_category_id=data.get('parent_category_id'),
            sort_order=data.get('sort_order')
        )

@dataclass
class ConfigTopicData:
    config: str
    problem_description: str
    tags: List[str]
    resolution: Optional[str]  # From replies marking as resolved
    error_messages: List[str]  # Extracted error messages
    topic_url: str  # For reference
    source_type: str = "inline"  # "inline" or "attachment"
    attachment_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary"""
        return {
            "config": self.config,
            "problem_description": self.problem_description,
            "tags": self.tags,
            "resolution": self.resolution,
            "error_messages": self.error_messages,
            "topic_url": self.topic_url,
            "source_type": self.source_type,
            "attachment_url": self.attachment_url
        }

class DiscourseCollector:
    def __init__(self, cookie_string: str, db: Database):
        """Initialize the Discourse collector with browser cookies

        Args:
            cookie_string: The raw cookie string from your browser (copy from browser dev tools)
            db: Database instance for storing collected data
        """
        self.base_url = 'https://klipper.discourse.group'
        self.db = db

        # Parse the cookie string into a dict, focusing on _t cookie
        self.cookies = {}
        for cookie in cookie_string.split(';'):
            if '=' in cookie:
                name, value = cookie.strip().split('=', 1)
                name = name.strip()
                if name == '_t':  # Only use the _t cookie
                    self.cookies[name] = unquote_plus(value.strip())
                    break

        if '_t' not in self.cookies:
            raise ValueError("No '_t' cookie found in cookie string. Please provide a valid Discourse session cookie.")

        # Set up headers with only ASCII characters
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:135.0) Gecko/20100101 Firefox/135.0"
        }

        # Set up caching session with retry logic
        self.session = CachedSession(
            db.db_path,
            backend='sqlite',
            expire_after=timedelta(hours=24),
            allowable_methods=('GET',)
        )

        # Configure retry strategy
        retry_strategy = Retry(
            total=MAX_RETRIES,
            backoff_factor=RETRY_BACKOFF_FACTOR,
            status_forcelist=RETRY_STATUS_FORCELIST,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

        self.session.headers.update(self.headers)
        self.session.cookies.update(self.cookies)

        # Cache for categories
        self._categories: Optional[List[CategoryData]] = None

    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> requests.Response:
        """Make a GET request to Discourse with logging, caching, and rate limiting"""
        # Add delay between requests to avoid rate limiting
        time.sleep(REQUEST_DELAY)

        # Ensure params are properly encoded
        if params:
            # Convert any non-string values to strings and ensure ASCII compatibility
            params = {
                k: str(v).encode('ascii', 'ignore').decode('ascii')
                if not isinstance(v, str) else v
                for k, v in params.items()
            }

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        logger.info(f"Making Discourse request: GET {url}")
        logger.info(f"Request params: {params}")

        try:
            response = self.session.get(
                url,
                params=params,
                headers=self.headers,
                cookies=self.cookies
            )

            # Check if we need to handle rate limiting manually
            if response.status_code == 429:
                retry_after = int(response.headers.get('Retry-After', 5))
                logger.warning(f"Rate limited. Waiting {retry_after} seconds before retrying...")
                time.sleep(retry_after)
                # Retry the request
                response = self.session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    cookies=self.cookies
                )

            response.raise_for_status()

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}", exc_info=True)
            logger.error(f"Response content: {response.text if 'response' in locals() else 'No response'}")
            raise

        logger.info(f"Cache {'hit' if response.from_cache else 'miss'} for: {url}")
        logger.info(f"Response status: {response.status_code}")

        return response

    def _get_paginated_data(self, endpoint: str, params: Dict[str, Any] = None, page_limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Generic method to fetch all paginated data from a Discourse endpoint."""
        all_data = []
        params = params or {}
        page = 0  # Start from page 0

        # Use default page limit if none specified
        if page_limit is None:
            page_limit = DEFAULT_PAGE_LIMIT

        while True:
            # Check if we've reached the page limit
            if page_limit and page >= page_limit:
                logger.info(f"Reached page limit of {page_limit}")
                break

            try:
                current_params = dict(params)
                current_params["page"] = page

                try:
                    response = self._make_request(endpoint, current_params)
                    page_data = response.json()
                except requests.exceptions.RequestException as e:
                    logger.warning(f"Error fetching page {page}: {e}")
                    time.sleep(RETRY_BACKOFF_FACTOR ** page)  # Exponential backoff
                    continue

                # Handle empty response
                if not page_data:
                    break

                # Extract topic list from response
                if "topic_list" in page_data:
                    topics = page_data["topic_list"]["topics"]
                    if not topics:  # No more topics
                        break
                    all_data.extend(topics)

                    # Check if we have more pages
                    if not page_data["topic_list"].get("more_topics_url"):
                        break
                else:
                    # For other endpoints (like posts)
                    posts = page_data.get("post_stream", {}).get("posts", [])
                    if not posts:  # No more posts
                        break
                    all_data.extend(posts)
                    if not page_data.get("post_stream", {}).get("more_posts"):
                        break

                page += 1
                logger.info(f"Fetched page {page}, got {len(all_data)} items so far")

            except Exception as e:
                logger.error(f"Failed to fetch paginated data from {endpoint}: {e}", exc_info=True)
                break  # Break instead of raise to return partial data

        return all_data

    def get_categories(self) -> List[CategoryData]:
        """Fetch all categories from Discourse"""
        if self._categories is not None:
            return self._categories

        try:
            response = self._make_request("site.json")
            data = response.json()
            categories = data.get("categories", [])

            self._categories = [CategoryData.from_json(cat) for cat in categories]
            logger.info(f"Found {len(self._categories)} categories")

            return self._categories
        except Exception as e:
            logger.error(f"Failed to fetch categories: {e}", exc_info=True)
            raise

    def collect_topics(self, since: datetime = None, category_id: Optional[int] = None, page_limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Collect topics from Discourse"""
        params = {}
        if since:
            # Convert datetime to Unix timestamp for Discourse
            params["created_at"] = int(since.timestamp())

        if category_id is not None:
            # Verify category exists
            categories = self.get_categories()
            if not any(c.topic_url == category_id for c in categories):
                raise ValueError(f"Category ID {category_id} not found")
            params["category"] = category_id

        topics = self._get_paginated_data("latest.json", params, page_limit)
        logger.info(f"Found {len(topics)} topics")

        # Keep track of successfully processed topics
        processed_topics = 0

        # Store basic topic data and process attachments
        for topic in topics:
            topic_id = str(topic['id'])

            # Get the full topic content
            try:
                topic_response = self._make_request(f"t/{topic_id}.json")
                full_topic = topic_response.json()

                # Get content from the first post
                first_post = full_topic.get("post_stream", {}).get("posts", [])[0]
                raw_content = first_post.get("cooked", "") # Get cooked HTML content
                if not raw_content:
                    raw_content = first_post.get("raw", "") # Fallback to raw content

                logger.info(f"Storing topic {topic_id}")

                # Parse created_at timestamp
                try:
                    created_at_str = first_post.get("created_at") # Use post creation time
                    if isinstance(created_at_str, (int, float)):
                        created_at = datetime.fromtimestamp(created_at_str, tz=timezone.utc)
                    else:
                        # Parse ISO 8601 format
                        created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                        # created_at = datetime.fromisoformat(created_at_str[:-1])  # Adjust for timezone if needed
                except (ValueError, TypeError) as e:
                    logger.warning(f"Failed to parse created_at timestamp for topic {topic_id} ({created_at_str}): {e}")
                    created_at = datetime.now(timezone.utc)

                # Store topic
                self.db.store_issue(
                    issue_id=topic_id,
                    source="discourse",
                    content=raw_content,
                    created_at=created_at,
                    metadata={
                        "title": topic["title"],
                        "url": f"{self.base_url}/t/{topic.get('slug', topic_id)}/{topic_id}",
                        "tags": topic.get("tags", []),
                        "category_id": topic.get("category_id"),
                        "post_count": topic.get("posts_count", 0),
                        "reply_count": topic.get("reply_count", 0),
                        "views": topic.get("views", 0),
                        "like_count": topic.get("like_count", 0),
                        "author": first_post.get("username", ""),
                        "post_number": first_post.get("post_number", 1)
                    },
                    raw_response=topic
                )

                # Queue topic for processing
                self.db.queue_for_processing(
                    item_id=topic_id,
                    source_type='topic'
                )

                # Process attachments from topic body
                if raw_content:
                    self._process_attachments(topic_id, raw_content)

                processed_topics += 1

                # Log progress periodically
                if processed_topics % 10 == 0:
                    logger.info(f"Successfully processed {processed_topics}/{len(topics)} topics")

            except Exception as e:
                logger.error(f"Failed to process topic {topic_id}: {e}", exc_info=True)
                self.db.rollback()
                continue

        # 4. Collect and process posts (including their attachments)
        logger.info(f"Successfully processed {processed_topics} topics. Starting to collect posts...")
        self.collect_topic_posts(topics)

        return topics

    def collect_topic_posts(self, topics: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Collect posts for a list of topics"""
        all_posts = []
        processed_posts = 0
        logger.info("Collecting and processing posts for topics")
        for topic in topics:
            topic_id = str(topic['id'])
            logger.info(f"Collecting posts for topic {topic_id}")

            try:
                # Get posts for this topic
                posts_response = self._make_request(f"t/{topic_id}/posts.json")
                posts_data = posts_response.json()
                posts = posts_data.get("post_stream", {}).get("posts", [])

                for post in posts:
                    post_id = str(post['id'])
                    post_number = post.get('post_number', 0)

                    # Skip the first post as it's the topic content
                    if post_number == 1:
                        continue

                    # Get content from the post
                    content = post.get("cooked", "")  # Get HTML content
                    if not content:
                        content = post.get("raw", "")  # Fallback to raw content

                    # Parse the created_at timestamp
                    created_at_str = post.get("created_at")
                    try:
                        if isinstance(created_at_str, (int, float)):
                            created_at = datetime.fromtimestamp(created_at_str, tz=timezone.utc)
                        else:
                            # Parse ISO 8601 format
                            created_at = datetime.strptime(created_at_str, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"Failed to parse created_at timestamp for post {post_id} in topic {topic_id} ({created_at_str}): {e}")
                        created_at = datetime.now(timezone.utc)  # Fallback to current time

                    try:
                        # Store post
                        self.db.store_comment(
                            comment_id=post_id,
                            issue_id=topic_id,
                            author=post.get('username', ''),
                            created_at=created_at,
                            content=content,
                            metadata={
                                "url": f"{self.base_url}/t/{topic.get('slug', topic_id)}/{topic_id}/{post_number}",
                                "post_number": post_number,
                                "like_count": post.get('like_count', 0),
                                "accepted_answer": post.get('accepted_answer', False),
                                "name": post.get('name', ''),
                                "display_username": post.get('display_username', ''),
                                "reply_to_post_number": post.get('reply_to_post_number'),
                                "version": post.get('version', 1),
                                "trust_level": post.get('trust_level', 0)
                            },
                            raw_response=post
                        )

                        # Queue post for processing
                        self.db.queue_for_processing(
                            item_id=post_id,
                            source_type='comment'
                        )

                        # Process attachments from post
                        if content:
                            self._process_attachments(topic_id, content)

                        processed_posts += 1

                        if processed_posts % 20 == 0:
                            logger.info(f"Successfully processed {processed_posts} posts")

                        all_posts.append(post)
                    except Exception as e:
                        logger.error(f"Failed to process post {post_id} for topic {topic_id}: {e}", exc_info=True)
                        continue

            except Exception as e:
                logger.error(f"Failed to collect posts for topic {topic_id}: {e}", exc_info=True)
                continue

        logger.info(f"Successfully processed {processed_posts} posts total")
        return all_posts

    def _process_attachments(self, topic_id: str, content: str) -> None:
        """Process attachments from a topic or post"""
        logger.info(f"Starting attachment processing for topic {topic_id}")

        # Process Discourse attachments with class="attachment"
        attachment_links = re.findall(r'<a class="attachment"\s+href="([^"]+)"[^>]*>([^<]+)</a>', content)
        logger.info(f"Found {len(attachment_links)} attachment links in topic {topic_id}")
        for href, text in attachment_links:
            # Convert relative URL to absolute URL if needed
            if href.startswith('/'):
                url = f"{self.base_url}{href}"
            else:
                url = href

            logger.info(f"Processing attachment URL: {url} (filename: {text}) for topic {topic_id}")
            file_content = self._fetch_file_content(url)
            if file_content:
                # Use the original filename from the link text
                filename = text.strip()
                if not filename:
                    filename = self._get_filename_from_url(url)

                logger.info(f"Storing attachment as {filename}")
                self.db.store_issue_attachment(
                    issue_id=topic_id,
                    filename=filename,
                    content=file_content,
                    source_type='discourse_attachment',
                    url=url
                )
            else:
                logger.warning(f"No content retrieved from URL: {url}")

        # Process HTML code blocks (like <pre><code>)
        html_code_blocks = re.findall(r'<pre><code[^>]*>(.*?)</code></pre>', content, re.DOTALL)
        logger.info(f"Found {len(html_code_blocks)} HTML code blocks in topic {topic_id}")
        for block in html_code_blocks:
            # Remove any HTML entities (like &gt;, &lt;, etc.)
            decoded_block = block.replace('&gt;', '>').replace('&lt;', '<').replace('&amp;', '&')
            if self._is_likely_config(decoded_block):
                filename = f"code_block_{hashlib.md5(decoded_block.encode()).hexdigest()[:8]}.cfg"
                logger.info(f"Storing HTML code block as {filename}")
                self.db.store_issue_attachment(
                    issue_id=topic_id,
                    filename=filename,
                    content=decoded_block,
                    source_type='code_block',
                    url=None
                )

        # Process markdown code blocks
        markdown_blocks = re.findall(r'```.*?\n(.*?)```', content, re.DOTALL)
        logger.info(f"Found {len(markdown_blocks)} markdown code blocks in topic {topic_id}")
        for block in markdown_blocks:
            if self._is_likely_config(block):
                filename = f"code_block_{hashlib.md5(block.encode()).hexdigest()[:8]}.cfg"
                logger.info(f"Storing markdown code block as {filename}")
                self.db.store_issue_attachment(
                    issue_id=topic_id,
                    filename=filename,
                    content=block,
                    source_type='code_block',
                    url=None
                )

        # Process Discourse uploads
        discourse_uploads = re.findall(r'https?://[^/]+/uploads/(?:short-url|[^/]+/[^/]+)/[^\s\)\"\']+', content)
        logger.info(f"Found {len(discourse_uploads)} discourse_upload links in topic {topic_id}")
        for url in discourse_uploads:
            logger.info(f"Processing discourse_upload URL: {url} for topic {topic_id}")
            file_content = self._fetch_file_content(url)
            if file_content:
                filename = self._get_filename_from_url(url)
                self.db.store_issue_attachment(
                    issue_id=topic_id,
                    filename=filename,
                    content=file_content,
                    url=url,
                    source_type="discourse_upload"
                )
            else:
                logger.warning(f"No content retrieved from URL: {url}")

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
        """Fetch content from a URL"""
        try:
            # Check if the URL is a valid Discourse upload link
            if '/uploads/short-url/' not in url:
                logger.warning(f"Invalid upload URL: {url}")
                return None

            logger.info(f"Fetching content from: {url}")
            response = self.session.get(url, timeout=10, allow_redirects=True)  # Follow redirects
            response.raise_for_status()  # Raise an error for bad responses
            return response.text
        except requests.exceptions.HTTPError as e:
            logger.error(f"Failed to fetch content from {url}: {e}", exc_info=True)
            return None
        except Exception as e:
            logger.error(f"An unexpected error occurred: {e}", exc_info=True)
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