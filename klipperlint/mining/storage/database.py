import sqlite3
from datetime import datetime
from pathlib import Path
import json
import logging
from typing import Optional, List, Dict, Any
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Database:
    def __init__(self, db_path: str = "collected_data.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database and handle migrations"""
        with sqlite3.connect(self.db_path) as conn:
            # Create tables if they don't exist
            conn.execute("""
                CREATE TABLE IF NOT EXISTS klipper_issues (
                    id TEXT PRIMARY KEY,
                    source TEXT,
                    created_at TIMESTAMP,
                    content TEXT,
                    metadata JSON,
                    raw_response JSON
                )
            """)

            # Create initial config_snippets table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS config_snippets (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT,
                    content TEXT,
                    problem_description TEXT,
                    source_type TEXT,
                    attachment_url TEXT,
                    attachment_content TEXT,
                    fetch_date TIMESTAMP,
                    FOREIGN KEY(issue_id) REFERENCES klipper_issues(id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS collection_log (
                    source TEXT,
                    last_run TIMESTAMP,
                    status TEXT,
                    items_collected INTEGER,
                    metadata JSON
                )
            """)

            # Add comments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS issue_comments (
                    id TEXT PRIMARY KEY,
                    issue_id TEXT,
                    author TEXT,
                    created_at TIMESTAMP,
                    content TEXT,
                    metadata JSON,
                    raw_response JSON,
                    FOREIGN KEY(issue_id) REFERENCES klipper_issues(id)
                )
            """)

            # Add processing status tracking
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processing_status (
                    item_id TEXT PRIMARY KEY,
                    source_type TEXT,
                    current_phase TEXT,
                    last_processed TIMESTAMP,
                    retries INTEGER DEFAULT 0,
                    error TEXT,
                    metadata JSON
                )
            """)

            # Add processed data tables
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processed_configs (
                    id TEXT PRIMARY KEY,
                    raw_config_id TEXT,
                    processed_content TEXT,
                    analysis_results JSON,
                    detected_patterns JSON,
                    validation_results JSON,
                    processing_date TIMESTAMP,
                    FOREIGN KEY(raw_config_id) REFERENCES config_snippets(id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS config_patterns (
                    id TEXT PRIMARY KEY,
                    pattern_type TEXT,  -- 'error', 'warning', 'best_practice'
                    frequency INTEGER,
                    impact_score FLOAT,
                    description TEXT,
                    examples JSON,
                    first_seen TIMESTAMP,
                    last_seen TIMESTAMP
                )
            """)

            # Add processing queue table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS processing_queue (
                    item_id TEXT PRIMARY KEY,
                    source_type TEXT,
                    queued_at TIMESTAMP,
                    priority INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'pending',
                    FOREIGN KEY(item_id) REFERENCES klipper_issues(id)
                )
            """)

            # Create index for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_queue_status
                ON processing_queue(status, priority DESC, queued_at ASC)
            """)

            # Create analysis results table with full_response column
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id VARCHAR(255) NOT NULL,
                    valid_sections JSONB,
                    invalid_sections JSONB,
                    parsing_errors JSONB,
                    analysis JSONB,
                    is_config_issue BOOLEAN,
                    relevance_score FLOAT,
                    full_response TEXT,
                    request_data TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add LLM requests table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    item_id VARCHAR(255) NOT NULL,
                    request_data TEXT,
                    full_response TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add attachments table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS issue_attachments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    issue_id TEXT NOT NULL,
                    filename TEXT,
                    content TEXT,
                    url TEXT,
                    source_type TEXT, -- 'code_block' or 'url'
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(issue_id) REFERENCES klipper_issues(id)
                )
            """)

            # Add index for faster lookups
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_attachments_issue_id
                ON issue_attachments(issue_id)
            """)

            # Handle migrations
            self._migrate_database(conn)

    def _migrate_database(self, conn: sqlite3.Connection):
        """Add new columns if they don't exist"""
        # Create mapping of tables to their existing columns
        existing_columns = {}

        # Get current columns for each table
        tables = ['config_snippets', 'klipper_issues', 'issue_comments']
        for table in tables:
            cursor = conn.execute(f"PRAGMA table_info({table})")
            existing_columns[table] = {row[1] for row in cursor.fetchall()}

        # Define new columns for each table
        migrations = {
            'config_snippets': {
                "problem_description": "TEXT",
                "source_type": "TEXT",
                "attachment_url": "TEXT",
                "attachment_content": "TEXT",
                "fetch_date": "TIMESTAMP"
            },
            'klipper_issues': {
                "raw_response": "JSON"
            },
            'issue_comments': {
                "raw_response": "JSON"
            }
        }

        # Apply migrations
        for table, columns in migrations.items():
            for column, type_ in columns.items():
                if column not in existing_columns[table]:
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {type_}")
                        logger.info(f"Added column {column} to {table} table")
                    except sqlite3.OperationalError as e:
                        logger.warning(f"Failed to add column {column} to {table}: {e}")

        # Check if full_response column exists in analysis_results table
        cursor = conn.execute("PRAGMA table_info(analysis_results)")
        columns = {row[1] for row in cursor.fetchall()}

        if "full_response" not in columns:
            try:
                conn.execute("ALTER TABLE analysis_results ADD COLUMN full_response TEXT")
                logger.info("Added full_response column to analysis_results table")
            except sqlite3.OperationalError as e:
                logger.warning(f"Failed to add full_response column to analysis_results: {e}")

    def _is_valid_issue_id(self, id_value: str) -> bool:
        """Validate issue ID format (numeric only)"""
        # If it's a comment ID, it will be in format "issue_comment"
        if '_' in id_value:
            issue_id, comment_id = id_value.split('_')
            return bool(re.match(r'^\d+$', issue_id) and re.match(r'^\d+$', comment_id))
        # Otherwise it should be a numeric issue ID
        return bool(re.match(r'^\d+$', id_value))

    def _is_valid_snippet_id(self, id_value: str) -> bool:
        """Validate snippet ID format (issue_id-index)"""
        pattern = r'^\d+-\d+$'
        return bool(re.match(pattern, id_value))

    def _extract_issue_id_from_snippet(self, snippet_id: str) -> str:
        """Extract the issue ID from a snippet ID"""
        if not self._is_valid_snippet_id(snippet_id):
            raise ValueError(f"Invalid snippet ID format: {snippet_id}")
        return snippet_id.split('-')[0]

    def store_issue(self, source: str, issue_id: str, content: str, created_at: datetime, metadata: dict, raw_response: dict):
        """Store an issue with its raw response data"""
        if not self._is_valid_issue_id(issue_id):
            logger.error(f"Invalid ID format: {issue_id}", exc_info=True)
            raise ValueError(f"Invalid ID format: {issue_id}")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO klipper_issues
                (id, source, created_at, content, metadata, raw_response)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (issue_id, source, created_at, content,
                 json.dumps(metadata), json.dumps(raw_response))
            )

    def store_config_snippet(self, snippet_id: str, issue_id: str, content: str,
                            problem_description: str, source_type: str = "inline",
                            attachment_url: Optional[str] = None,
                            attachment_content: Optional[str] = None):
        """Store a config snippet with validation"""
        if not self._is_valid_snippet_id(snippet_id):
            raise ValueError(f"Invalid snippet ID format: {snippet_id}")
        if not self._is_valid_issue_id(issue_id):
            raise ValueError(f"Invalid issue ID format: {issue_id}")

        # Verify the snippet's issue ID matches the provided issue ID
        snippet_issue_id = self._extract_issue_id_from_snippet(snippet_id)
        if snippet_issue_id != issue_id:
            raise ValueError(f"Snippet ID {snippet_id} does not match issue ID {issue_id}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO config_snippets
                    (id, issue_id, content, problem_description, source_type, attachment_url,
                     attachment_content, fetch_date)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (snippet_id, issue_id, content, problem_description, source_type,
                     attachment_url, attachment_content,
                     datetime.utcnow() if attachment_content else None)
                )
        except sqlite3.Error as e:
            logger.error(f"Error storing config snippet: {e}", exc_info=True)
            logger.debug(f"Data: {snippet_id}, {issue_id}, {content}, {problem_description}, {source_type}, {attachment_url}, {attachment_content}")

    def update_collection_log(self, source: str, items_collected: int, status: str = "success", metadata: dict = None):
        """Update collection log with optional metadata"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO collection_log
                (source, last_run, status, items_collected, metadata)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source, datetime.utcnow(), status, items_collected,
                 json.dumps(metadata) if metadata else None)
            )

    def get_last_run(self, source: str) -> datetime:
        logger.info(f"Getting last run for {source}")
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                "SELECT last_run FROM collection_log WHERE source = ? ORDER BY last_run DESC LIMIT 1",
                (source,)
            ).fetchone()
            logger.info(f"Last run for {source}: {result}")
            return datetime.fromisoformat(result[0]) if result else None

    def clear_last_run(self, source: str):
        """Clear the last run timestamp for a source"""
        logger.info(f"Clearing last run for {source}")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM collection_log WHERE source = ?",
                (source,)
            )
            logger.info(f"Cleared last run for {source}")

    def store_comment(self, comment_id: str, issue_id: str, author: str,
                     created_at: datetime, content: str, metadata: dict = None,
                     raw_response: dict = None):
        """Store an issue comment"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO issue_comments
                (id, issue_id, author, created_at, content, metadata, raw_response)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (comment_id, issue_id, author, created_at, content,
                 json.dumps(metadata) if metadata else None,
                 json.dumps(raw_response) if raw_response else None)
            )

    def update_processing_status(self, item_id: str, source_type: str = None,
                               current_phase: str = None, error: str = None,
                               metadata: dict = None):
        """Update processing status for an item"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO processing_status
                (item_id, source_type, current_phase, last_processed,
                 error, metadata, retries)
                VALUES (
                    ?, ?, ?, ?,
                    ?, ?, COALESCE((
                        SELECT retries + 1
                        FROM processing_status
                        WHERE item_id = ?
                    ), 0)
                )
            """, (item_id, source_type, current_phase, datetime.utcnow(),
                  error, json.dumps(metadata) if metadata else None, item_id))

    def get_processing_status(self, item_id: str) -> Optional[str]:
        """Get current processing phase for an item"""
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute(
                "SELECT current_phase FROM processing_status WHERE item_id = ?",
                (item_id,)
            ).fetchone()
            return result[0] if result else None

    def get_unprocessed_items(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get items that need processing"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT q.item_id as id, q.source_type, q.queued_at
                FROM processing_queue q
                LEFT JOIN processing_status s ON q.item_id = s.item_id
                WHERE q.status = 'pending'
                AND (s.current_phase IS NULL OR s.error IS NOT NULL)
                ORDER BY q.priority DESC, q.queued_at ASC
                LIMIT ?
            """, (limit,))
            return [dict(row) for row in cursor.fetchall()]

    def queue_for_processing(self, item_id: str, source_type: str, priority: int = 0):
        """Add an item to the processing queue"""
        if not self._is_valid_issue_id(item_id):
            raise ValueError(f"Invalid issue ID format: {item_id}")

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO processing_queue
                (item_id, source_type, queued_at, priority, status)
                VALUES (?, ?, ?, ?, 'pending')
            """, (item_id, source_type, datetime.utcnow(), priority))

    def get_issues(self, item_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch issues from the database."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT * FROM klipper_issues
                    WHERE id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (item_id, limit))
                issues = [dict(row) for row in cursor.fetchall()]
                if not issues:
                    logger.warning(f"No issues found for item_id: {item_id}")
                else:
                    logger.debug(f"Fetched issues for item_id {item_id}: {issues}")
                return issues
        except sqlite3.Error as e:
            logger.error(f"Error fetching issues for item_id {item_id}: {e}", exc_info=True)
            raise

    def get_comments(self, issue_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch comments for a specific issue."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM issue_comments
                WHERE issue_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (issue_id, limit))
            return [dict(row) for row in cursor.fetchall()]

    def get_config_snippets(self, issue_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch config snippets for a specific issue."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM config_snippets
                WHERE issue_id = ?
                ORDER BY fetch_date DESC
                LIMIT ?
            """, (issue_id, limit))
            return [dict(row) for row in cursor.fetchall()]

    def store_analysis_result(self, item_id, valid_sections, invalid_sections, parsing_errors,
                             analysis, is_config_issue, relevance_score):
        """Store analysis results in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO analysis_results
                    (item_id, valid_sections, invalid_sections, parsing_errors, analysis,
                     is_config_issue, relevance_score)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    item_id,
                    json.dumps(valid_sections),
                    json.dumps(invalid_sections),
                    json.dumps(parsing_errors),
                    json.dumps(analysis),
                    is_config_issue,
                    relevance_score
                ))
        except sqlite3.Error as e:
            logger.error(f"Error storing analysis result for item {item_id}: {e}", exc_info=True)
            raise

    def get_items_with_empty_analysis(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get items that have empty analysis results"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT ar.item_id as id, ps.source_type
                    FROM analysis_results ar
                    JOIN processing_status ps ON ar.item_id = ps.item_id
                    WHERE ar.analysis = '{}' OR ar.analysis IS NULL
                    LIMIT ?
                """, (limit,))
                return [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as e:
            logger.error(f"Error fetching items with empty analysis: {e}", exc_info=True)
            return []

    def reset_processing_status(self, item_id: str, reset_to_phase: str = None):
        """Reset the processing status for an item to allow reprocessing"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Reset the current phase
                conn.execute("""
                    UPDATE processing_status
                    SET current_phase = ?, error = NULL
                    WHERE item_id = ?
                """, (reset_to_phase, item_id))

                # Delete existing analysis results if needed
                conn.execute("""
                    DELETE FROM analysis_results
                    WHERE item_id = ?
                """, (item_id,))

                logger.info(f"Reset processing status for item {item_id} to phase {reset_to_phase}")
        except sqlite3.Error as e:
            logger.error(f"Error resetting processing status for item {item_id}: {e}", exc_info=True)

    def get_full_llm_response(self, item_id: str) -> Optional[str]:
        """Get the full LLM response for an item"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                result = conn.execute(
                    "SELECT full_response FROM analysis_results WHERE item_id = ? ORDER BY created_at DESC LIMIT 1",
                    (item_id,)
                ).fetchone()
                return result[0] if result else None
        except sqlite3.Error as e:
            logger.error(f"Error fetching full LLM response for item {item_id}: {e}", exc_info=True)
            return None

    def get_all_issues_for_reprocessing(self, since: datetime = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get all issues that are available for reprocessing, respecting the 'since' argument"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            query = """
                SELECT id, source FROM klipper_issues
            """

            # Add a condition for the 'since' argument if provided
            if since:
                query += " WHERE created_at >= ?"

            query += " LIMIT ?"

            params = []
            if since:
                params.append(since)
            params.append(limit)

            cursor = conn.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

    def mark_item_in_progress(self, item_id: str):
        """Mark an item as in progress in the processing queue."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE processing_queue
                SET status = 'in progress'
                WHERE item_id = ?
            """, (item_id,))

    def mark_item_completed(self, item_id: str):
        """Mark an item as completed in the processing queue."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE processing_queue
                SET status = 'completed'
                WHERE item_id = ?
            """, (item_id,))

    def mark_item_failed(self, item_id: str, error_message: str):
        """Mark an item as failed in the processing queue and log the error."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE processing_queue
                SET status = 'failed'
                WHERE item_id = ?
            """, (item_id,))

    def store_llm_data(self, item_id: str, request_data: str, full_response: str):
        """Store the LLM request and response data in the database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO llm_requests (item_id, request_data, full_response)
                    VALUES (?, ?, ?)
                """, (item_id, request_data, full_response))
        except sqlite3.Error as e:
            logger.error(f"Error storing LLM data for item {item_id}: {e}", exc_info=True)
            raise

    def store_issue_attachment(self, issue_id: str, filename: str, content: str,
                             url: str = None, source_type: str = None):
        """Store an attachment for an issue"""
        if not self._is_valid_issue_id(issue_id):
            raise ValueError(f"Invalid issue ID format: {issue_id}")

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO issue_attachments
                    (issue_id, filename, content, url, source_type)
                    VALUES (?, ?, ?, ?, ?)
                """, (issue_id, filename, content, url, source_type))
        except sqlite3.Error as e:
            logger.error(f"Error storing attachment for issue {issue_id}: {e}", exc_info=True)
            raise

    def get_issue_attachments(self, issue_id: str) -> List[Dict[str, Any]]:
        """Get all attachments for an issue"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("""
                SELECT * FROM issue_attachments
                WHERE issue_id = ?
                ORDER BY created_at DESC
            """, (issue_id,))
            return [dict(row) for row in cursor.fetchall()]

    def get_anthropic_cache_info(self):
        """Get information about the Anthropic cache"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                # Get total number of cached responses
                total = conn.execute("""
                    SELECT COUNT(*) FROM anthropic_cache
                """).fetchone()[0]

                # Get size of cache
                size = conn.execute("""
                    SELECT SUM(LENGTH(response)) FROM anthropic_cache
                """).fetchone()[0]

                # Get most recent cached responses
                recent = conn.execute("""
                    SELECT url, created FROM anthropic_cache
                    ORDER BY created DESC
                    LIMIT 5
                """).fetchall()

                cache_info = {
                    'total_entries': total,
                    'cache_size_bytes': size,
                    'recent_entries': recent
                }

                logger.info(f"Anthropic cache info: {cache_info}")
                return cache_info
        except sqlite3.Error as e:
            logger.error(f"Error getting cache info: {e}", exc_info=True)
            return None

    def get_llm_request(self, item_id: str) -> Optional[Dict[str, Any]]:
        """Get existing LLM request and response for an item"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute("""
                    SELECT request_data, full_response, created_at
                    FROM llm_requests
                    WHERE item_id = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (item_id,))

                result = cursor.fetchone()
                if result:
                    return dict(result)
                return None

        except sqlite3.Error as e:
            logger.error(f"Error fetching LLM request for item {item_id}: {e}", exc_info=True)
            return None