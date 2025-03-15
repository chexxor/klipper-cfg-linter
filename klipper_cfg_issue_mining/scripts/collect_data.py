#!/usr/bin/env python3
import os
import argparse
from datetime import datetime, timedelta
import logging
from pathlib import Path
import json
import sys

from klipper_cfg_issue_mining.collectors.github_collector import GitHubCollector
from klipper_cfg_issue_mining.collectors.discourse_collector import DiscourseCollector
from klipper_cfg_issue_mining.storage.database import Database
from klipper_cfg_issue_mining.processing.pipeline import ProcessingPipeline

# Usage:
# # Set GitHub token
# export GITHUB_TOKEN=your_token_here
# # Set Discourse cookie (copy from browser dev tools - make sure to get _t cookie)
# export DISCOURSE_COOKIE='_t=your_cookie_value_here'
# # Set Anthropic API key
# export ANTHROPIC_API_KEY=your_key_here
# # Collect last 24 hours of data
# python3 -m scripts.collect_data
# # Collect data since specific date
# python3 -m scripts.collect_data --since 2024-01-01
# # Specify database path
# python3 -m scripts.collect_data --db-path /path/to/data.db
# # Force reprocess all items
# python3 -m klipper_cfg_issue_mining.scripts.collect_data --force-reprocess

# Set up logger at the module level
logger = logging.getLogger(__name__)

def setup_logging():
    """Configure logging for the collector"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('collection_processing.log')
        ]
    )

def process_collected_data(db: Database, pipeline: ProcessingPipeline, batch_size: int = 100):
    """Process newly collected data through the pipeline"""
    try:
        unprocessed = db.get_unprocessed_items(batch_size)
        logger.info(f"Found {len(unprocessed)} items to process")

        for item in unprocessed:
            try:
                item_id = str(item['id'])  # Ensure string type
                logger.info(f"Processing item {item_id}")
                pipeline.process_item(item_id, item['source_type'])
            except Exception as e:
                logger.error(f"Failed to process item {item_id}: {e}", exc_info=True)
                continue

    except Exception as e:
        logger.error(f"Error in process_collected_data: {e}", exc_info=True)
        raise

def collect_github_data(db: Database, pipeline: ProcessingPipeline, token: str, since: datetime = None):
    """Collect and process GitHub data"""
    collector = GitHubCollector(token, db)
    try:
        # Phase 1: Collect all issues
        logger.info(f"Phase 1: Collecting issues from GitHub since {since}")
        issues = collector.collect_issues(since=since)
        logger.info(f"Found {len(issues)} issues")

        # Update collection log
        db.update_collection_log(
            source="github",
            items_collected=len(issues)
        )

    except Exception as e:
        logger.error(f"Error in collect_github_data: {e}", exc_info=True)
        db.update_collection_log(
            source="github",
            items_collected=0,
            status=f"error: {str(e)}"
        )
        raise

def collect_discourse_data(db: Database, pipeline: ProcessingPipeline, cookie_string: str, since: datetime = None):
    """Collect and process Discourse data"""
    collector = DiscourseCollector(cookie_string, db)
    try:
        # Phase 1: Collect all topics
        logger.info(f"Phase 1: Collecting topics from Discourse since {since}")
        topics = collector.collect_topics(since=since)
        logger.info(f"Found {len(topics)} topics")

        # Update collection log
        db.update_collection_log(
            source="discourse",
            items_collected=len(topics),
            metadata={
                "since": since.isoformat() if since else None,
                "topics_collected": len(topics)
            }
        )

    except Exception as e:
        logger.error(f"Error in collect_discourse_data: {e}", exc_info=True)
        db.update_collection_log(
            source="discourse",
            items_collected=0,
            status=f"error: {str(e)}",
            metadata={
                "since": since.isoformat() if since else None,
                "error": str(e)
            }
        )
        raise

def collect_data(db: Database, pipeline: ProcessingPipeline, source: str, since: datetime):
    """Collect data from the specified source and process it"""
    if source == "github":
        github_token = os.environ.get("GITHUB_TOKEN")
        if not github_token:
            raise ValueError("GITHUB_TOKEN environment variable is required")
        collect_github_data(db, pipeline, github_token, since)
    elif source == "discourse":
        discourse_cookie = os.environ.get("DISCOURSE_COOKIE")
        if not discourse_cookie:
            raise ValueError(
                "DISCOURSE_COOKIE environment variable is required. "
                "Get this from your browser's developer tools - "
                "look for the '_t' cookie when logged into the forum."
            )
        collect_discourse_data(db, pipeline, discourse_cookie, since)

def retry_empty_analysis(db: Database, pipeline: ProcessingPipeline, limit: int = 100):
    """Retry processing for items with empty analysis results"""
    try:
        items = db.get_items_with_empty_analysis(limit)
        logger.info(f"Found {len(items)} items with empty analysis to retry")

        for item in items:
            try:
                item_id = str(item['id'])
                logger.info(f"Resetting and reprocessing item {item_id}")

                # Reset the processing status
                db.reset_processing_status(item_id)

                # Reprocess the item
                pipeline.process_item(item_id, item['source_type'])

                logger.info(f"Successfully reprocessed item {item_id}")
            except Exception as e:
                logger.error(f"Failed to reprocess item {item['id']}: {e}", exc_info=True)
                continue

    except Exception as e:
        logger.error(f"Error in retry_empty_analysis: {e}", exc_info=True)
        raise

def run_collection_and_processing(args):
    """Controller function to manage data collection and processing"""
    # Initialize database and pipeline
    db = Database(args.db_path)
    anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable is required")
    pipeline = ProcessingPipeline(db, anthropic_api_key)

    # Handle reset flag
    if args.reset_last_run:
        logger.info(f"Clearing last run timestamp for {args.source}")
        db.clear_last_run(args.source)

    # Handle retry flag
    if args.retry_empty_analysis:
        logger.info("Retrying items with empty analysis results")
        retry_empty_analysis(db, pipeline, args.retry_limit)
        return

    # Determine the collection timestamp
    if args.since:
        since = datetime.strptime(args.since, "%Y-%m-%d")
    elif args.force_full:
        since = None
        logger.info("Forcing full collection")
    else:
        # If no date provided, use last run or 24 hours ago
        since = db.get_last_run(args.source) or (datetime.utcnow() - timedelta(days=1))
        if since:
            logger.info(f"Collecting data since {since}")

    # Collect and process data
    if not args.process_only:
        collect_data(db, pipeline, args.source, since)

    # Handle force reprocess flag
    if args.force_reprocess:
        logger.info("Forcing reprocessing of all items")
        since_date = datetime.strptime(args.since, "%Y-%m-%d") if args.since else None
        items_to_reprocess = db.get_all_issues_for_reprocessing(since=since_date)
        logger.info(f"Found {len(items_to_reprocess)} items to reprocess")
        for item in items_to_reprocess:
            db.queue_for_processing(item['id'], item['source'])
            # Reset the processing status
            db.reset_processing_status(item['id'])

    process_collected_data(db, pipeline, args.batch_size)

def main():
    setup_logging()

    parser = argparse.ArgumentParser(description="Collect and process Klipper configuration data")
    parser.add_argument("--source", choices=["github", "discourse"], default="github",
                       help="Data source to collect from")
    parser.add_argument("--since", type=str,
                       help="Collect data since this date (YYYY-MM-DD)")
    parser.add_argument("--db-path", type=str, default="collected_data.db",
                       help="Path to SQLite database")
    parser.add_argument("--reset-last-run", action="store_true",
                       help="Clear the last run timestamp and collect all data")
    parser.add_argument("--force-full", action="store_true",
                       help="Ignore last run and collect all data (doesn't clear timestamp)")
    parser.add_argument("--batch-size", type=int, default=100,
                       help="Number of items to process in each batch")
    parser.add_argument("--process-only", action="store_true",
                       help="Only process existing unprocessed data, skip collection")
    parser.add_argument("--retry-empty-analysis", action="store_true",
                       help="Retry processing for items with empty analysis results")
    parser.add_argument("--retry-limit", type=int, default=100,
                       help="Maximum number of items to retry")
    parser.add_argument("--force-reprocess", action="store_true",
                    help="Force reprocess all items, resetting their processing status")
    args = parser.parse_args()

    run_collection_and_processing(args)

if __name__ == "__main__":
    main()
