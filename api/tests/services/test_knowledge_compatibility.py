"""Legacy imports must share objects and patch targets with knowledge services."""

import importlib
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

MODULES = [
    ("unified_repository", "candidate_repository"),
    ("unified_pipeline_service", "knowledge_pipeline_service"),
    ("unified_faq_extractor", "knowledge_extractor"),
    ("comparison_engine", "comparison_engine"),
    ("validation", "validation"),
    ("substantive_filter", "substantive_filter"),
    ("ingest", "ingest"),
    ("ingest.matrix_sync_service", "ingest.matrix_sync_service"),
    ("ingest.bisq2_sync_service", "ingest.bisq2_sync_service"),
]


@pytest.mark.parametrize("legacy,canonical", MODULES)
def test_legacy_modules_are_identical(legacy, canonical):
    assert importlib.import_module(
        f"app.services.training.{legacy}"
    ) is importlib.import_module(f"app.services.knowledge.{canonical}")


@pytest.mark.parametrize("legacy_first", [True, False])
def test_import_order_preserves_nested_module_identity(legacy_first):
    """A clean interpreter catches duplicate modules hidden by the test cache."""
    ordered = ["training", "knowledge"] if legacy_first else ["knowledge", "training"]
    code = f"""
import importlib
for package in {ordered!r}:
    importlib.import_module('app.services.' + package)
for legacy, canonical in {MODULES!r}:
    assert importlib.import_module('app.services.training.' + legacy) is importlib.import_module('app.services.knowledge.' + canonical)
from app.services.training.ingest import matrix_sync_service as legacy_matrix
from app.services.knowledge.ingest import matrix_sync_service as canonical_matrix
assert legacy_matrix is canonical_matrix
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize(
    "legacy,canonical",
    [
        ("UnifiedFAQCandidate", "KnowledgeCandidate"),
        ("UnifiedFAQCandidateRepository", "KnowledgeCandidateRepository"),
        ("UnifiedFAQExtractor", "KnowledgeExtractor"),
        ("UnifiedPipelineService", "KnowledgePipelineService"),
        ("ExtractedFAQ", "ExtractedKnowledge"),
        ("FAQExtractionResult", "KnowledgeExtractionResult"),
        ("UnifiedCalibrationStatus", "CalibrationStatus"),
        ("UnifiedComparisonResult", "PipelineComparisonResult"),
    ],
)
def test_legacy_public_classes_are_identical(legacy, canonical):
    old = importlib.import_module("app.services.training")
    new = importlib.import_module("app.services.knowledge")
    assert getattr(old, legacy) is getattr(new, canonical)
    assert legacy in old.__all__
    assert legacy not in new.__all__


def test_legacy_patch_target_changes_active_implementation():
    canonical = importlib.import_module("app.services.knowledge.knowledge_extractor")
    original = canonical.time
    sentinel = object()
    with patch("app.services.training.unified_faq_extractor.time", sentinel):
        assert canonical.time is sentinel
    assert canonical.time is original


def test_legacy_wildcard_exports_only_public_contract():
    legacy = importlib.import_module("app.services.training")
    namespace = {}
    exec("from app.services.training import *", namespace)
    assert set(namespace) - {"__builtins__"} == set(legacy.__all__)
    assert {"QAPair", "MatrixSyncService", "ProcessingResult"} <= set(namespace)
    assert not {"sys", "importlib", "KnowledgeExtractor"} & set(namespace)
