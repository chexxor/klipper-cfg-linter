# Data Collectors Documentation

## Overview
The collectors module is responsible for gathering configuration-related data from various sources. Each collector implements a common interface while handling source-specific requirements.

## Collectors

### 1. GitHub Collector (Implemented)
```python
from klipperlint.mining.collectors.github_collector import GitHubCollector

collector = GitHubCollector(token="your_github_token", db=database)
issues = collector.collect_issues(since=datetime.now() - timedelta(days=1))
```

#### Features
- [x] Collects all issues (not just labeled ones)
- [x] Extracts configuration snippets:
  - Inline code blocks
  - GitHub raw links
  - Gist links
  - Pastebin links
- [x] Processes issue comments
- [x] Handles pagination and rate limiting
- [x] Caches requests
- [x] Validates config snippets
- [x] Stores attachments separately
- [x] Queues items for processing

#### Methods
```python
def collect_issues(self, since: datetime = None) -> List[Dict[str, Any]]:
    """Collect issues since a given date"""

def collect_issue_comments(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collect comments for a list of issues"""

def _process_attachments(self, issue_id: str, content: str):
    """Process and store attachments from content"""

def _is_likely_config(self, content: str, language: str = "") -> bool:
    """Check if content looks like a Klipper config"""
```

#### Configuration
- `GITHUB_TOKEN`: Required for API authentication
- `DB_PATH`: Path to SQLite database
- Cache settings:
  - `expire_after`: 24 hours
  - `backend`: sqlite
  - `allowable_methods`: GET

#### Error Handling
- Request retries with exponential backoff
- Rate limit handling
- Invalid data validation
- Detailed error logging
- Exception recovery per issue/comment

### 2. Documentation Collector (Planned)
```python
from klipperlint.mining.collectors.docs_collector import DocsCollector

collector = DocsCollector(db=database)
references = collector.collect_config_reference()
```

#### Planned Features
- [ ] Scrape Klipper documentation
- [ ] Extract:
  - Configuration reference
  - Warning sections
  - Required vs optional parameters
  - Parameter constraints
  - Dependencies between settings
- [ ] Parse configuration examples
- [ ] Build parameter relationship graph

### 3. Discord Collector (Planned)
```python
from klipperlint.mining.collectors.discord_collector import DiscordCollector

collector = DiscordCollector(token="your_discord_token", db=database)
messages = collector.collect_messages(channel="config-help")
```

#### Planned Features
- [ ] Monitor specified channels
- [ ] Extract configuration discussions
- [ ] Track solutions and resolutions
- [ ] Handle message threading
- [ ] Privacy considerations
- [ ] Rate limiting

### 4. Reddit Collector (Planned)
```python
from klipperlint.mining.collectors.reddit_collector import RedditCollector

collector = RedditCollector(client_id="id", client_secret="secret", db=database)
posts = collector.collect_posts(subreddit="klippers")
```

#### Planned Features
- [ ] Collect configuration-related posts
- [ ] Track solutions in comments
- [ ] Handle cross-posts and links
- [ ] Filter by relevance and score

## Common Interface
All collectors implement or will implement:
```python
def collect(self, since: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Collect data from source"""
    pass

def process_content(self, content: str, item_id: str):
    """Process and store content"""
    pass

def extract_config(self, content: str) -> List[str]:
    """Extract configuration snippets"""
    pass
```

## Data Storage
- SQLite database with WAL mode
- Separate tables for:
  - Raw issues/comments
  - Attachments
  - Processing queue
  - Analysis results
- JSON for metadata storage
- Full response caching

## Error Handling
- Multi-level error recovery:
  - Per request
  - Per item
  - Per batch
- Detailed logging
- Status tracking
- Processing queue management

## Processing Pipeline
1. Data Collection
   - Fetch raw data
   - Store in database
2. Content Processing
   - Extract configs
   - Process attachments
   - Queue for analysis
3. Analysis
   - LLM-based analysis
   - Pattern detection
   - Impact assessment

## Next Steps
1. Add automated testing
2. Implement data validation
3. Add monitoring system
4. Begin documentation collector
5. Enhance error handling
6. Add data cleanup tools

## Privacy Considerations
- Personal information is stripped
- Usernames are anonymized
- Private messages are excluded
- Data retention policies are enforced
- Caching respects API terms
