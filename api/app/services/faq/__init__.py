"""FAQ service package for modular FAQ management."""

from app.services.faq.conversation_processor import ConversationProcessor
from app.services.faq.faq_extractor import FAQExtractor
from app.services.faq.faq_rag_loader import FAQRAGLoader

# Note: FAQRepository (JSONL-based) is deprecated but kept for migration.
# Use FAQRepositorySQLite from faq_repository_sqlite.py for new code.

__all__ = ["ConversationProcessor", "FAQRAGLoader", "FAQExtractor"]
