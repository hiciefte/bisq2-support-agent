"""Compatibility imports for the former training service package.

New code imports app.services.knowledge. Alias module objects so existing
operational imports and patched attributes still address the same implementation.
"""

import importlib
import sys

from app.services.knowledge import (
    AnswerComparisonEngine,
    BisqSyncStateManager,
)
from app.services.knowledge import CalibrationStatus as UnifiedCalibrationStatus
from app.services.knowledge import (
    ComparisonResult,
    FilterResult,
    MatrixExportParser,
    MatrixSyncService,
)
from app.services.knowledge import PipelineComparisonResult as UnifiedComparisonResult
from app.services.knowledge import (
    ProcessingResult,
    QAPair,
    SubstantiveAnswerFilter,
    extract_json_from_llm_response,
)
from app.services.knowledge.candidate_repository import (
    KnowledgeCandidate as UnifiedFAQCandidate,
)
from app.services.knowledge.candidate_repository import (
    KnowledgeCandidateRepository as UnifiedFAQCandidateRepository,
)
from app.services.knowledge.knowledge_extractor import (
    ExtractedKnowledge as ExtractedFAQ,
)
from app.services.knowledge.knowledge_extractor import (
    KnowledgeExtractionResult as FAQExtractionResult,
)
from app.services.knowledge.knowledge_extractor import (
    KnowledgeExtractor as UnifiedFAQExtractor,
)
from app.services.knowledge.knowledge_pipeline_service import (
    KnowledgePipelineService as UnifiedPipelineService,
)

__all__ = [
    "BisqSyncStateManager",
    "AnswerComparisonEngine",
    "ComparisonResult",
    "extract_json_from_llm_response",
    "ExtractedFAQ",
    "FAQExtractionResult",
    "FilterResult",
    "MatrixExportParser",
    "MatrixSyncService",
    "ProcessingResult",
    "QAPair",
    "SubstantiveAnswerFilter",
    "UnifiedCalibrationStatus",
    "UnifiedComparisonResult",
    "UnifiedFAQCandidate",
    "UnifiedFAQCandidateRepository",
    "UnifiedFAQExtractor",
    "UnifiedPipelineService",
]

_MODULE_ALIASES = {
    "unified_repository": "candidate_repository",
    "unified_pipeline_service": "knowledge_pipeline_service",
    "unified_faq_extractor": "knowledge_extractor",
    "comparison_engine": "comparison_engine",
    "validation": "validation",
    "substantive_filter": "substantive_filter",
    "ingest": "ingest",
    "ingest.matrix_sync_service": "ingest.matrix_sync_service",
    "ingest.bisq2_sync_service": "ingest.bisq2_sync_service",
}
for _legacy, _canonical in _MODULE_ALIASES.items():
    _module = importlib.import_module(f"app.services.knowledge.{_canonical}")
    sys.modules[f"{__name__}.{_legacy}"] = _module
    if "." not in _legacy:
        globals()[_legacy] = _module
