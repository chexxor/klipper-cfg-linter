import anthropic
import httpx
from requests_cache import CachedSession
from requests import Request
import logging
import os
import hashlib
import json
import sqlite3

logger = logging.getLogger(__name__)

class CachedAnthropicClient(anthropic.Anthropic):
    """Custom Anthropic client that uses CachedSession for requests"""
    def __init__(self, api_key: str, db_path: str = "collected_data.db", **kwargs):
        super().__init__(api_key=api_key, **kwargs)

        # Ensure we're using an absolute path to the database
        db_path = os.path.abspath(db_path)

        # Create a CachedSession using the main database
        self.cached_session = CachedSession(
            cache_name=db_path,
            backend="sqlite",
            expire_after=None,
            table_name="anthropic_cache",
            # Add cache key generation function
            cache_control=True,
            allowable_methods=['GET', 'POST']
        )

        # Create a custom httpx.Client that uses our cached session
        self._client = httpx.Client(
            transport=httpx.HTTPTransport(retries=2),
            timeout=60.0,
            headers={
                "anthropic-version": "2023-06-01",
                "x-api-key": api_key,
                "Accept-Encoding": "identity",
            }
        )

        # Override the _client's send method to use our cached session
        original_send = self._client.send
        def cached_send(request, **kwargs):
            # Generate a consistent cache key based on the request content
            cache_key = self._generate_cache_key(request)
            logger.debug(f"Generated cache key: {cache_key}")

            # Convert httpx.Request to requests.Request
            requests_request = self.cached_session.prepare_request(
                Request(
                    method=request.method,
                    url=str(request.url),
                    headers=dict(request.headers),
                    data=request.content
                )
            )

            # Add the cache key to the request
            requests_request.cache_key = cache_key

            # Use cached session to send request
            response = self.cached_session.send(requests_request, **kwargs)

            # Log whether this was a cache hit or miss
            if hasattr(response, 'from_cache') and response.from_cache:
                logger.info(f"Cache HIT for key: {cache_key}")
                logger.debug(f"Cached response retrieved for request: {request.content}")
            else:
                logger.info(f"Cache MISS for key: {cache_key}")
                logger.debug(f"New API call for request: {request.content}")

            # Convert requests.Response back to httpx.Response
            return httpx.Response(
                status_code=response.status_code,
                headers=dict(response.headers),
                content=response.content,
                request=request,
                extensions={
                    "http_version": "1.1",
                    "reason_phrase": response.reason.encode("ascii", errors="ignore")
                }
            )

        self._client.send = cached_send

    def _generate_cache_key(self, request) -> str:
        """Generate a consistent cache key based on the request content"""
        try:
            # Parse the request content as JSON
            if request.content:
                content = json.loads(request.content)
                # Extract only the messages content for the cache key
                if 'messages' in content:
                    messages_content = [msg.get('content', '') for msg in content['messages']]
                    # Create a string that only includes the actual message content
                    content_str = ''.join(messages_content)

                    # Create a hash of the content
                    content_hash = hashlib.md5(content_str.encode()).hexdigest()

                    # Create a cache key that includes the model and content hash
                    model = content.get('model', 'unknown')
                    cache_key = f"anthropic:{model}:{content_hash}"

                    return cache_key

            # Fallback to a basic cache key if we can't parse the content
            return f"anthropic:default:{hashlib.md5(request.content or b'').hexdigest()}"

        except Exception as e:
            logger.error(f"Error generating cache key: {e}", exc_info=True)
            # Fallback to a basic cache key
            return f"anthropic:error:{hashlib.md5(request.content or b'').hexdigest()}"

    def get_cache_stats(self):
        """Return statistics about cache usage"""
        try:
            with sqlite3.connect(self.cached_session.cache.db_path) as conn:
                # Get total number of cached responses
                total_cached = conn.execute("""
                    SELECT COUNT(*) FROM responses
                    WHERE key LIKE 'anthropic:%'
                """).fetchone()[0]

                # Get number of unique keys cached
                unique_keys = conn.execute("""
                    SELECT COUNT(DISTINCT key) FROM responses
                    WHERE key LIKE 'anthropic:%'
                """).fetchone()[0]

                # Get most recent entries
                recent_entries = conn.execute("""
                    SELECT key, expires
                    FROM responses
                    WHERE key LIKE 'anthropic:%'
                    ORDER BY expires DESC
                    LIMIT 5
                """).fetchall()

                stats = {
                    'total_cached': total_cached,
                    'unique_requests': unique_keys,
                    'recent_keys': [{'key': key, 'expires': exp} for key, exp in recent_entries]
                }

                logger.info(f"Anthropic API Cache statistics: {stats}")
                return stats

        except Exception as e:
            logger.error(f"Error getting cache stats: {e}", exc_info=True)
            return None