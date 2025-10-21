# Multi-Source FAQ Extraction: Library Research and Modular Architecture Design

**Research Date**: 2025-10-21
**Objective**: Identify Python libraries and design patterns for extending Bisq2 Support Agent to extract FAQs from multiple sources (bisq.wiki, Telegram, Matrix, Discourse forum)

## Executive Summary

This research identifies mature Python libraries and architectural patterns for building a **modular, plugin-based FAQ extraction system** that can:
- Integrate with 4 new data sources (MediaWiki, Telegram, Matrix, Discourse)
- Use a reusable plugin architecture suitable for open-source publication
- Maintain the existing OpenAI-based FAQ extraction workflow
- Scale to additional sources without core system modifications

**Recommended Architecture**: Pluggy-based plugin system with Adapter pattern for source-specific integrations.

---

## 1. Source Integration Libraries

### 1.1 MediaWiki (bisq.wiki)

**Recommended: `pymediawiki`**
- **PyPI**: `pip install pymediawiki`
- **GitHub**: https://github.com/barrust/mediawiki
- **Last Updated**: Active (2024)
- **Key Features**:
  - Simple wrapper around MediaWiki API
  - Get article content, summaries, links, images
  - Search Wikipedia/MediaWiki sites
  - No direct XML dump parsing needed

**Example Usage**:
```python
from mediawiki import MediaWiki
wiki = MediaWiki(url='https://bisq.wiki/api.php')
page = wiki.page('Support')
content = page.content  # Full page text
summary = page.summary  # Brief summary
```

**Alternative: `mediawikiapi`** (similar features, slightly different API)

**For XML Dump Processing**: `MediaWiki Utilities` (mwutils)
- Best for offline processing of complete wiki dumps
- Your existing `process_wiki_dump.py` already handles this case

---

### 1.2 Telegram Integration

**Recommended: `python-telegram-bot`**
- **PyPI**: `pip install python-telegram-bot`
- **GitHub**: https://github.com/python-telegram-bot/python-telegram-bot
- **Version**: 21.x (active development, latest: v21.9)
- **Python Support**: 3.10+
- **Key Features**:
  - Full async/await support
  - Native support for Telegram Bot API 9.2
  - **Chat history retrieval** via `get_chat_history()`
  - Message export and archival
  - Webhook and polling modes

**Alternative: `Pyrogram`**
- **PyPI**: `pip install pyrogram`
- **GitHub**: https://github.com/pyrogram/pyrogram
- **Key Features**:
  - MTProto API client (not just Bot API)
  - Can access **user account chats** (not just bot chats)
  - `get_chat_history()` method for message retrieval
  - Better for scraping existing group conversations

**Recommendation**:
- Use **Pyrogram** if you need to access existing Telegram group history
- Use **python-telegram-bot** if implementing a new bot that monitors ongoing conversations

**Example Usage (Pyrogram)**:
```python
from pyrogram import Client

app = Client("bisq_support", api_id=API_ID, api_hash=API_HASH)

async def get_messages():
    async with app:
        async for message in app.get_chat_history("bisq_support_group"):
            print(message.text)
```

---

### 1.3 Matrix Chat Integration

**Recommended: `matrix-nio`**
- **PyPI**: `pip install matrix-nio[e2e]`
- **GitHub**: https://github.com/poljar/matrix-nio
- **Status**: Actively maintained, recommended by Matrix.org
- **Key Features**:
  - Modern async/await API
  - End-to-end encryption support (E2EE)
  - Message history via `sync()` and `room_messages()`
  - Event timeline access

**Example Usage**:
```python
from nio import AsyncClient

client = AsyncClient("https://matrix.org", "@user:matrix.org")

# Get room messages
response = await client.room_messages(
    room_id="!roomid:matrix.org",
    start="",
    limit=100
)

for event in response.chunk:
    if hasattr(event, 'body'):
        print(event.body)  # Message text
```

**Alternative: `matrix-python-sdk`** (deprecated, lightly maintained)

---

### 1.4 Discourse Forum (bisq.community)

**Recommended: `pydiscourse`**
- **PyPI**: `pip install pydiscourse`
- **GitHub**: https://github.com/pydiscourse/pydiscourse
- **Latest Version**: 1.7.0 (April 2024)
- **Status**: Actively maintained
- **Key Features**:
  - Complete Discourse API wrapper
  - Topic and post retrieval
  - User activity tracking
  - Command-line interface (`pydiscoursecli`)
  - Recent updates for larger requests (body-based params)

**Example Usage**:
```python
from pydiscourse import DiscourseClient

client = DiscourseClient(
    'https://bisq.community',
    api_username='username',
    api_key='your_api_key'
)

# Get latest topics
topics = client.topics_by('support_staff')

# Get posts in a topic
topic = client.topic('topic_id')
for post in topic['post_stream']['posts']:
    print(post['cooked'])  # HTML content
    print(post['raw'])     # Markdown content
```

**Alternative: `discourse` by samamorgan** (less popular, similar features)

---

## 2. Plugin Architecture Frameworks

### 2.1 Pluggy (Recommended)

**PyPI**: `pip install pluggy`
**GitHub**: https://github.com/pytest-dev/pluggy
**Used By**: pytest, tox, devpi

**Why Pluggy**:
- ✅ Lightweight and battle-tested (powers pytest)
- ✅ Hook-based architecture (perfect for FAQ extraction pipeline)
- ✅ Easy plugin registration
- ✅ No complex entry point configuration required
- ✅ Excellent documentation

**Architecture**:
```python
import pluggy

# Define hook specification
hookspec = pluggy.HookspecMarker("faq_extractor")
hookimpl = pluggy.HookimplMarker("faq_extractor")

class FAQSourceSpec:
    @hookspec
    def extract_conversations(self, start_date, end_date):
        """Extract conversations from source"""

    @hookspec
    def get_source_name(self):
        """Return source identifier"""

# Plugin implementation
class TelegramSource:
    @hookimpl
    def extract_conversations(self, start_date, end_date):
        # Telegram-specific extraction logic
        return conversations

    @hookimpl
    def get_source_name(self):
        return "telegram"

# Plugin manager
pm = pluggy.PluginManager("faq_extractor")
pm.add_hookspecs(FAQSourceSpec)
pm.register(TelegramSource())

# Call hooks
results = pm.hook.extract_conversations(start_date="2024-01-01", end_date="2024-12-31")
```

---

### 2.2 Stevedore (Alternative)

**PyPI**: `pip install stevedore`
**GitHub**: https://github.com/openstack/stevedore
**Used By**: OpenStack projects

**Why Stevedore**:
- ✅ Built on setuptools entry points
- ✅ Strong integration with Python packaging
- ✅ Multiple loading patterns (drivers, named extensions, extension managers)
- ❌ More complex setup (requires setup.py configuration)
- ❌ Heavier than Pluggy for simple use cases

**Use Case**: Choose if you want plugins distributed as separate PyPI packages.

---

## 3. Recommended Modular Architecture

### 3.1 System Overview

```
bisq2-support-agent/
├── api/
│   ├── app/
│   │   ├── services/
│   │   │   ├── faq_service.py           # Existing orchestrator
│   │   │   ├── simplified_rag_service.py
│   │   │   └── sources/                 # NEW: Plugin directory
│   │   │       ├── __init__.py
│   │   │       ├── base.py              # Abstract base class
│   │   │       ├── bisq_websocket.py    # Existing (refactored)
│   │   │       ├── telegram.py          # NEW
│   │   │       ├── matrix.py            # NEW
│   │   │       ├── discourse.py         # NEW
│   │   │       └── mediawiki.py         # NEW
│   │   └── core/
│   │       └── plugin_manager.py        # NEW: Pluggy integration
```

---

### 3.2 Abstract Base Class (Adapter Pattern)

**File**: `api/app/services/sources/base.py`

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Optional
from datetime import datetime

class FAQSourceAdapter(ABC):
    """
    Abstract base class for FAQ source plugins.

    Each source adapter must implement methods to:
    1. Extract conversations/content
    2. Identify the source
    3. Validate configuration
    """

    @abstractmethod
    def get_source_name(self) -> str:
        """Return unique source identifier (e.g., 'telegram', 'matrix')"""
        pass

    @abstractmethod
    def extract_conversations(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """
        Extract conversations/messages from the source.

        Returns:
            List of conversation dicts with format:
            {
                'conversation_id': str,
                'messages': [
                    {
                        'msg_id': str,
                        'sender': str,
                        'content': str,
                        'timestamp': datetime,
                        'is_support_staff': bool
                    }
                ],
                'metadata': {
                    'source': str,
                    'channel': str,
                    'tags': List[str]
                }
            }
        """
        pass

    @abstractmethod
    def validate_config(self) -> bool:
        """Validate source configuration (API keys, credentials, etc.)"""
        pass

    def get_metadata(self) -> Dict:
        """Optional: Return source-specific metadata"""
        return {
            'source': self.get_source_name(),
            'version': '1.0.0',
            'capabilities': []
        }
```

---

### 3.3 Plugin Manager (Pluggy Integration)

**File**: `api/app/core/plugin_manager.py`

```python
import pluggy
from typing import List, Dict
from datetime import datetime
from app.services.sources.base import FAQSourceAdapter

# Hook specifications
hookspec = pluggy.HookspecMarker("faq_sources")
hookimpl = pluggy.HookimplMarker("faq_sources")

class FAQSourceHooks:
    """Hook specifications for FAQ source plugins"""

    @hookspec
    def get_source_adapter(self) -> FAQSourceAdapter:
        """Return the source adapter instance"""

class FAQSourceManager:
    """Manages FAQ source plugins using Pluggy"""

    def __init__(self):
        self.pm = pluggy.PluginManager("faq_sources")
        self.pm.add_hookspecs(FAQSourceHooks)
        self._load_plugins()

    def _load_plugins(self):
        """Discover and register all source plugins"""
        # Import all source modules
        from app.services.sources import (
            bisq_websocket,
            telegram,
            matrix,
            discourse,
            mediawiki
        )

        # Register each plugin
        for module in [bisq_websocket, telegram, matrix, discourse, mediawiki]:
            if hasattr(module, 'register_plugin'):
                module.register_plugin(self.pm)

    def get_all_sources(self) -> List[FAQSourceAdapter]:
        """Get all registered source adapters"""
        results = self.pm.hook.get_source_adapter()
        return [r for r in results if r is not None]

    def get_source(self, source_name: str) -> FAQSourceAdapter:
        """Get specific source adapter by name"""
        for source in self.get_all_sources():
            if source.get_source_name() == source_name:
                return source
        raise ValueError(f"Source '{source_name}' not found")

    def extract_all_conversations(
        self,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict[str, List[Dict]]:
        """Extract conversations from all sources"""
        results = {}
        for source in self.get_all_sources():
            if source.validate_config():
                source_name = source.get_source_name()
                results[source_name] = source.extract_conversations(start_date, end_date)
        return results
```

---

### 3.4 Example Plugin Implementation: Telegram

**File**: `api/app/services/sources/telegram.py`

```python
from typing import List, Dict, Optional
from datetime import datetime
from pyrogram import Client
from app.services.sources.base import FAQSourceAdapter
from app.core.config import settings

class TelegramSourceAdapter(FAQSourceAdapter):
    """Telegram group message extraction adapter"""

    def __init__(self):
        self.api_id = settings.TELEGRAM_API_ID
        self.api_hash = settings.TELEGRAM_API_HASH
        self.group_id = settings.TELEGRAM_GROUP_ID
        self.support_staff_ids = settings.TELEGRAM_SUPPORT_STAFF_IDS or []
        self.client = None

    def get_source_name(self) -> str:
        return "telegram"

    def validate_config(self) -> bool:
        """Check if Telegram credentials are configured"""
        return bool(self.api_id and self.api_hash and self.group_id)

    async def _init_client(self):
        """Initialize Pyrogram client"""
        if not self.client:
            self.client = Client(
                "bisq_support_telegram",
                api_id=self.api_id,
                api_hash=self.api_hash
            )

    def extract_conversations(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict]:
        """Extract messages from Telegram group"""
        import asyncio
        return asyncio.run(self._extract_conversations_async(start_date, end_date))

    async def _extract_conversations_async(
        self,
        start_date: Optional[datetime],
        end_date: Optional[datetime]
    ) -> List[Dict]:
        """Async implementation of conversation extraction"""
        await self._init_client()
        conversations = []

        async with self.client:
            # Group messages by conversation thread
            current_conversation = None
            messages_buffer = []

            async for message in self.client.get_chat_history(self.group_id):
                # Filter by date range
                if start_date and message.date < start_date:
                    break
                if end_date and message.date > end_date:
                    continue

                # Check if message is from support staff
                is_support = str(message.from_user.id) in self.support_staff_ids

                msg_data = {
                    'msg_id': str(message.id),
                    'sender': message.from_user.username or str(message.from_user.id),
                    'content': message.text or '',
                    'timestamp': message.date,
                    'is_support_staff': is_support
                }

                # Simple conversation grouping: messages within 1 hour
                if not current_conversation:
                    current_conversation = {
                        'conversation_id': f"tg_{message.id}",
                        'messages': [msg_data],
                        'metadata': {
                            'source': 'telegram',
                            'channel': self.group_id,
                            'tags': []
                        }
                    }
                else:
                    time_diff = (current_conversation['messages'][-1]['timestamp'] -
                                message.date).total_seconds()

                    if abs(time_diff) < 3600:  # 1 hour threshold
                        current_conversation['messages'].append(msg_data)
                    else:
                        # Save current conversation and start new one
                        conversations.append(current_conversation)
                        current_conversation = {
                            'conversation_id': f"tg_{message.id}",
                            'messages': [msg_data],
                            'metadata': {
                                'source': 'telegram',
                                'channel': self.group_id,
                                'tags': []
                            }
                        }

            # Add last conversation
            if current_conversation:
                conversations.append(current_conversation)

        return conversations

    def get_metadata(self) -> Dict:
        return {
            'source': 'telegram',
            'version': '1.0.0',
            'capabilities': ['message_history', 'user_mentions', 'media_files']
        }

# Plugin registration function
def register_plugin(plugin_manager):
    """Register this plugin with the manager"""
    from app.core.plugin_manager import hookimpl

    class TelegramPlugin:
        @hookimpl
        def get_source_adapter(self) -> FAQSourceAdapter:
            return TelegramSourceAdapter()

    plugin_manager.register(TelegramPlugin())
```

---

### 3.5 Integration with Existing FAQService

**Modifications to**: `api/app/services/faq_service.py`

```python
from app.core.plugin_manager import FAQSourceManager

class FAQService:
    def __init__(self, settings):
        self.settings = settings
        # ... existing initialization ...

        # NEW: Initialize plugin manager
        self.source_manager = FAQSourceManager()

    def extract_faqs_from_all_sources(
        self,
        start_date: datetime = None,
        end_date: datetime = None
    ) -> Dict[str, int]:
        """
        Extract FAQs from all configured sources.

        Returns:
            Dict mapping source names to FAQ count extracted
        """
        results = {}

        # Get conversations from all sources
        all_conversations = self.source_manager.extract_all_conversations(
            start_date=start_date,
            end_date=end_date
        )

        # Process each source's conversations
        for source_name, conversations in all_conversations.items():
            faq_count = 0

            for conversation in conversations:
                # Use existing FAQ extraction logic
                faq = self._extract_faq_from_conversation(conversation)

                if faq:
                    # Add source metadata
                    faq['metadata']['source'] = source_name

                    # Save to existing repository
                    self.faq_repository.add_faq(faq)
                    faq_count += 1

            results[source_name] = faq_count

        return results

    def _extract_faq_from_conversation(self, conversation: Dict) -> Optional[Dict]:
        """
        Existing FAQ extraction logic (works with any source).

        This method already exists in your codebase and uses OpenAI
        to analyze conversations and extract Q&A pairs.
        """
        # Your existing implementation here
        pass
```

---

## 4. Configuration Management

**File**: `api/app/core/config.py` (additions)

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # Telegram Configuration
    TELEGRAM_API_ID: Optional[str] = None
    TELEGRAM_API_HASH: Optional[str] = None
    TELEGRAM_GROUP_ID: Optional[str] = None
    TELEGRAM_SUPPORT_STAFF_IDS: Optional[List[str]] = None

    # Matrix Configuration
    MATRIX_HOMESERVER: Optional[str] = None
    MATRIX_USER_ID: Optional[str] = None
    MATRIX_ACCESS_TOKEN: Optional[str] = None
    MATRIX_ROOM_IDS: Optional[List[str]] = None

    # Discourse Configuration
    DISCOURSE_URL: str = "https://bisq.community"
    DISCOURSE_API_KEY: Optional[str] = None
    DISCOURSE_API_USERNAME: Optional[str] = None
    DISCOURSE_CATEGORY_IDS: Optional[List[int]] = None

    # MediaWiki Configuration
    MEDIAWIKI_API_URL: str = "https://bisq.wiki/api.php"
    MEDIAWIKI_PAGES: Optional[List[str]] = None

    class Config:
        env_file = ".env"
```

**File**: `docker/.env` (additions)

```bash
# Telegram Integration
TELEGRAM_API_ID=your_api_id
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_GROUP_ID=@bisq_support
TELEGRAM_SUPPORT_STAFF_IDS=user1,user2,user3

# Matrix Integration
MATRIX_HOMESERVER=https://matrix.org
MATRIX_USER_ID=@bot:matrix.org
MATRIX_ACCESS_TOKEN=your_token
MATRIX_ROOM_IDS=!room1:matrix.org,!room2:matrix.org

# Discourse Integration
DISCOURSE_URL=https://bisq.community
DISCOURSE_API_KEY=your_api_key
DISCOURSE_API_USERNAME=support_bot
DISCOURSE_CATEGORY_IDS=5,12,18

# MediaWiki Integration
MEDIAWIKI_API_URL=https://bisq.wiki/api.php
MEDIAWIKI_PAGES=Support,FAQ,Troubleshooting
```

---

## 5. Publishing as Open-Source Library

### 5.1 Package Structure

To make this reusable for other open-source projects:

```
bisq2-faq-extractor/  (Separate repository)
├── pyproject.toml
├── README.md
├── LICENSE (MIT)
├── src/
│   └── faq_extractor/
│       ├── __init__.py
│       ├── core/
│       │   ├── plugin_manager.py
│       │   └── base.py
│       ├── sources/
│       │   ├── telegram.py
│       │   ├── matrix.py
│       │   ├── discourse.py
│       │   └── mediawiki.py
│       └── extractors/
│           ├── openai_extractor.py
│           └── base_extractor.py
├── tests/
└── examples/
    └── basic_usage.py
```

### 5.2 PyPI Package Configuration

**File**: `pyproject.toml`

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "faq-extractor"
version = "0.1.0"
description = "Modular FAQ extraction from multiple chat/forum sources"
readme = "README.md"
license = {text = "MIT"}
authors = [
    {name = "Bisq Network", email = "support@bisq.network"}
]
keywords = ["faq", "chatbot", "support", "telegram", "matrix", "discourse"]
classifiers = [
    "Development Status :: 4 - Beta",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]
requires-python = ">=3.11"
dependencies = [
    "pluggy>=1.5.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
]

[project.optional-dependencies]
telegram = ["pyrogram>=2.0.0", "tgcrypto>=1.2.0"]
matrix = ["matrix-nio[e2e]>=0.25.0"]
discourse = ["pydiscourse>=1.7.0"]
mediawiki = ["pymediawiki>=0.7.0"]
openai = ["openai>=1.0.0", "langchain>=0.1.0"]
all = [
    "pyrogram>=2.0.0",
    "tgcrypto>=1.2.0",
    "matrix-nio[e2e]>=0.25.0",
    "pydiscourse>=1.7.0",
    "pymediawiki>=0.7.0",
    "openai>=1.0.0",
    "langchain>=0.1.0",
]

[project.urls]
Homepage = "https://github.com/bisq-network/faq-extractor"
Repository = "https://github.com/bisq-network/faq-extractor"
"Bug Tracker" = "https://github.com/bisq-network/faq-extractor/issues"
```

### 5.3 Example Usage for Other Projects

**File**: `examples/basic_usage.py`

```python
"""
Example: Using faq-extractor in your own project
"""
from faq_extractor import FAQSourceManager, OpenAIExtractor
from datetime import datetime, timedelta

# 1. Initialize plugin manager
source_manager = FAQSourceManager()

# 2. Extract conversations from all sources
end_date = datetime.now()
start_date = end_date - timedelta(days=30)

conversations = source_manager.extract_all_conversations(
    start_date=start_date,
    end_date=end_date
)

# 3. Extract FAQs using OpenAI
extractor = OpenAIExtractor(api_key="your_openai_key")

for source_name, convos in conversations.items():
    print(f"Processing {len(convos)} conversations from {source_name}")

    for convo in convos:
        faq = extractor.extract_faq(convo)
        if faq:
            print(f"  Q: {faq['question']}")
            print(f"  A: {faq['answer'][:100]}...")
```

---

## 6. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
1. ✅ Create abstract base class `FAQSourceAdapter`
2. ✅ Implement Pluggy-based `FAQSourceManager`
3. ✅ Refactor existing Bisq WebSocket integration to use adapter pattern
4. ✅ Add plugin discovery and registration
5. ✅ Update `FAQService` to use plugin manager

### Phase 2: Source Integrations (Week 3-4)
1. ✅ Implement `TelegramSourceAdapter` with Pyrogram
2. ✅ Implement `DiscourseSourceAdapter` with pydiscourse
3. ✅ Implement `MatrixSourceAdapter` with matrix-nio
4. ✅ Implement `MediaWikiSourceAdapter` with pymediawiki
5. ✅ Add configuration management for all sources

### Phase 3: Testing & Documentation (Week 5)
1. ✅ Write unit tests for each adapter
2. ✅ Write integration tests with mocked APIs
3. ✅ Create comprehensive documentation
4. ✅ Add example configurations

### Phase 4: Packaging & Release (Week 6)
1. ✅ Extract core functionality to separate package
2. ✅ Set up CI/CD pipeline (GitHub Actions)
3. ✅ Publish to PyPI as `faq-extractor`
4. ✅ Create example projects
5. ✅ Announce to open-source community

---

## 7. Architectural Benefits

### 7.1 For Bisq2 Support Agent Project
- **Extensibility**: Add new sources without modifying core code
- **Maintainability**: Each source isolated in its own module
- **Testability**: Mock individual sources for unit tests
- **Configuration**: Enable/disable sources via environment variables
- **Scalability**: Parallel processing of multiple sources

### 7.2 For Open-Source Community
- **Reusability**: Other projects can use the same architecture
- **Modularity**: Install only needed source integrations
- **Documentation**: Clear examples for adding custom sources
- **Standard Interface**: Consistent API across all sources
- **Community Contributions**: Easy to add new source adapters

---

## 8. Comparison with Alternatives

### 8.1 Why Not Monolithic Integration?

**❌ Monolithic Approach**:
```python
class FAQService:
    def extract_from_telegram(self): ...
    def extract_from_matrix(self): ...
    def extract_from_discourse(self): ...
    def extract_from_mediawiki(self): ...
    # All logic in one file - hard to maintain
```

**✅ Plugin Approach**:
```python
class FAQService:
    def extract_from_all_sources(self):
        return self.source_manager.extract_all_conversations()
    # Each source in separate plugin - easy to extend
```

### 8.2 Why Pluggy Over Stevedore?

| Feature | Pluggy | Stevedore |
|---------|--------|-----------|
| Setup Complexity | Low | High (requires setup.py) |
| Learning Curve | Easy | Moderate |
| Documentation | Excellent | Good |
| Community | Large (pytest) | Smaller (OpenStack) |
| Use Case | Internal plugins | Distributed packages |
| Best For | **This project** | Large ecosystems |

---

## 9. Security Considerations

### 9.1 API Credentials
- **Never commit credentials to git**
- Use environment variables for all API keys
- Implement credential validation in `validate_config()`
- Use `.env.example` for documentation

### 9.2 Rate Limiting
- Implement rate limiting in each adapter
- Use exponential backoff for API calls
- Cache responses where appropriate
- Respect source-specific rate limits

### 9.3 Data Privacy
- **Follow existing privacy practices**:
  - Store only anonymized FAQs (no raw conversations in git)
  - Process personal data according to retention policy
  - Support GDPR-compliant data deletion
- Add privacy notices in documentation

---

## 10. References

### Libraries
- **python-telegram-bot**: https://github.com/python-telegram-bot/python-telegram-bot
- **Pyrogram**: https://github.com/pyrogram/pyrogram
- **matrix-nio**: https://github.com/poljar/matrix-nio
- **pydiscourse**: https://github.com/pydiscourse/pydiscourse
- **pymediawiki**: https://github.com/barrust/mediawiki
- **Pluggy**: https://github.com/pytest-dev/pluggy

### Design Patterns
- Adapter Pattern: https://refactoring.guru/design-patterns/adapter
- Plugin Architecture: https://alysivji.github.io/simple-plugin-system.html
- Abstract Base Classes: https://docs.python.org/3/library/abc.html

### Similar Projects
- **Lobe Chat**: Multi-source AI chat with RAG (https://github.com/lobehub/lobe-chat)
- **Casibase**: Enterprise AI knowledge base (https://github.com/casibase/casibase)
- **Agentic RAG Chatbot**: Modular RAG with multiple sources (https://github.com/ce3329/agentic-rag-chatbot)

---

## Conclusion

The recommended architecture uses:
1. **Pluggy** for plugin management (lightweight, proven)
2. **Adapter pattern** for source-specific integrations (clean separation)
3. **Abstract base class** for standardized interface (type safety)
4. **Modular package structure** for open-source publishing (reusability)

This design allows Bisq2 Support Agent to integrate 4 new sources while creating a reusable library for the broader open-source community.

**Next Steps**:
1. Review and approve architecture
2. Start Phase 1 implementation (foundation)
3. Incrementally add source adapters (one at a time)
4. Extract to separate package after validation
5. Publish to PyPI and announce to community
