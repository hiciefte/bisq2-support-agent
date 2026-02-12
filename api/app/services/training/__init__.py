"""Auto-training pipeline for extracting and validating Q&A pairs from Matrix."""

from app.channels.plugins.bisq2.client.sync_state import BisqSyncStateManager
from app.models.training import QAPair
from app.services.training.comparison_engine import (
    AnswerComparisonEngine,
    ComparisonResult,
    extract_json_from_llm_response,
)
from app.services.training.matrix_export_parser import MatrixExportParser
from app.services.training.matrix_sync_service import MatrixSyncService
from app.services.training.substantive_filter import (
    FilterResult,
    SubstantiveAnswerFilter,
)
from app.services.training.unified_faq_extractor import (
    ExtractedFAQ,
    FAQExtractionResult,
    UnifiedFAQExtractor,
)
from app.services.training.unified_pipeline_service import (
    ComparisonResult as UnifiedComparisonResult,
)
from app.services.training.unified_pipeline_service import (
    ProcessingResult,
    UnifiedPipelineService,
)
from app.services.training.unified_repository import (
    CalibrationStatus as UnifiedCalibrationStatus,
)
from app.services.training.unified_repository import (
    UnifiedFAQCandidate,
    UnifiedFAQCandidateRepository,
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
