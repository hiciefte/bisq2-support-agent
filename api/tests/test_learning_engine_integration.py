"""
TDD Tests for LearningEngine integration with the training pipeline.

These tests ensure LearningEngine routing terminology matches the pipeline
and that adaptive threshold learning works correctly.
"""

import tempfile
from pathlib import Path

import pytest
from app.services.rag.learning_engine import LaunchReadinessChecker, LearningEngine

# =============================================================================
# CYCLE 3: Routing Terminology Tests
# =============================================================================


class TestRoutingTerminology:
    """Test that LearningEngine returns pipeline-compatible routing values."""

    def test_routing_returns_auto_approve_for_high_confidence(self):
        """LearningEngine should return AUTO_APPROVE for high confidence."""
        engine = LearningEngine()
        # Default auto_send_threshold is 0.90 after fix
        result = engine.get_routing_recommendation(0.95)
        assert result == "AUTO_APPROVE"

    def test_routing_returns_spot_check_for_medium_confidence(self):
        """LearningEngine should return SPOT_CHECK for medium confidence."""
        engine = LearningEngine()
        # Between auto_approve (0.90) and spot_check (0.75)
        result = engine.get_routing_recommendation(0.80)
        assert result == "SPOT_CHECK"

    def test_routing_returns_full_review_for_low_confidence(self):
        """LearningEngine should return FULL_REVIEW for low confidence."""
        engine = LearningEngine()
        # Below spot_check threshold (0.75)
        result = engine.get_routing_recommendation(0.60)
        assert result == "FULL_REVIEW"

    def test_default_thresholds_match_pipeline_constants(self):
        """Default thresholds should match pipeline routing constants."""
        engine = LearningEngine()
        # These should match the pipeline's AUTO_APPROVE_THRESHOLD and SPOT_CHECK_THRESHOLD
        assert engine.auto_send_threshold == 0.90
        assert engine.queue_high_threshold == 0.75

    def test_routing_at_exact_auto_approve_threshold(self):
        """Confidence exactly at auto_approve threshold should return AUTO_APPROVE."""
        engine = LearningEngine()
        result = engine.get_routing_recommendation(0.90)
        assert result == "AUTO_APPROVE"

    def test_routing_at_exact_spot_check_threshold(self):
        """Confidence exactly at spot_check threshold should return SPOT_CHECK."""
        engine = LearningEngine()
        result = engine.get_routing_recommendation(0.75)
        assert result == "SPOT_CHECK"

    def test_routing_just_below_auto_approve(self):
        """Confidence just below auto_approve should return SPOT_CHECK."""
        engine = LearningEngine()
        result = engine.get_routing_recommendation(0.899)
        assert result == "SPOT_CHECK"

    def test_routing_just_below_spot_check(self):
        """Confidence just below spot_check should return FULL_REVIEW."""
        engine = LearningEngine()
        result = engine.get_routing_recommendation(0.749)
        assert result == "FULL_REVIEW"


# =============================================================================
# CYCLE 4: Persistence Tests (will be implemented in Cycle 4)
# =============================================================================


class TestLearningEnginePersistence:
    """Test LearningEngine state persistence."""

    @pytest.fixture
    def temp_db_path(self):
        """Create a temporary database path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir) / "test_unified.db"

    def test_save_and_load_state_preserves_thresholds(self, temp_db_path):
        """Thresholds persist across engine instances."""
        # Import repository here to avoid circular import
        from app.services.training.unified_repository import (
            UnifiedFAQCandidateRepository,
        )

        repo = UnifiedFAQCandidateRepository(str(temp_db_path))

        # Create engine and modify thresholds
        engine1 = LearningEngine()
        engine1.auto_send_threshold = 0.92
        engine1.queue_high_threshold = 0.78
        engine1.save_state(repo)

        # Create new engine and load state
        engine2 = LearningEngine()
        engine2.load_state(repo)

        assert engine2.auto_send_threshold == 0.92
        assert engine2.queue_high_threshold == 0.78

    def test_save_state_creates_learning_state_record(self, temp_db_path):
        """save_state creates a record in learning_state table."""
        from app.services.training.unified_repository import (
            UnifiedFAQCandidateRepository,
        )

        repo = UnifiedFAQCandidateRepository(str(temp_db_path))

        engine = LearningEngine()
        engine.save_state(repo)

        # Verify record was created
        state = repo.get_learning_state()
        assert state is not None
        assert "auto_send_threshold" in state

    def test_load_state_with_no_saved_state_uses_defaults(self, temp_db_path):
        """load_state with no saved state keeps default values."""
        from app.services.training.unified_repository import (
            UnifiedFAQCandidateRepository,
        )

        repo = UnifiedFAQCandidateRepository(str(temp_db_path))

        engine = LearningEngine()
        # Default values
        default_auto_send = engine.auto_send_threshold
        default_queue_high = engine.queue_high_threshold

        # Load with no saved state
        engine.load_state(repo)

        # Should keep defaults
        assert engine.auto_send_threshold == default_auto_send
        assert engine.queue_high_threshold == default_queue_high

    def test_review_history_is_persisted(self, temp_db_path):
        """Review history is saved and loaded correctly."""
        from app.services.training.unified_repository import (
            UnifiedFAQCandidateRepository,
        )

        repo = UnifiedFAQCandidateRepository(str(temp_db_path))

        engine1 = LearningEngine()
        # Record some reviews
        engine1.record_review(
            question_id="q1",
            confidence=0.85,
            admin_action="approved",
            routing_action="SPOT_CHECK",
        )
        engine1.record_review(
            question_id="q2",
            confidence=0.65,
            admin_action="rejected",
            routing_action="FULL_REVIEW",
        )
        engine1.save_state(repo)

        # Load into new engine
        engine2 = LearningEngine()
        engine2.load_state(repo)

        # Review history should be loaded
        metrics = engine2.get_learning_metrics()
        assert metrics["total_reviews"] == 2


# =============================================================================
# Basic Functionality Tests
# =============================================================================


class TestLearningEngineBasics:
    """Test basic LearningEngine functionality."""

    def test_record_review_increments_count(self):
        """Recording a review should increment the count."""
        engine = LearningEngine()
        initial_count = len(engine._review_history)

        engine.record_review(
            question_id="test_q1",
            confidence=0.85,
            admin_action="approved",
            routing_action="SPOT_CHECK",
        )

        assert len(engine._review_history) == initial_count + 1

    def test_get_learning_metrics_returns_correct_structure(self):
        """get_learning_metrics should return expected structure."""
        engine = LearningEngine()

        # Add some reviews
        engine.record_review("q1", 0.95, "approved", "AUTO_APPROVE")
        engine.record_review("q2", 0.80, "edited", "SPOT_CHECK")
        engine.record_review("q3", 0.60, "rejected", "FULL_REVIEW")

        metrics = engine.get_learning_metrics()

        assert "total_reviews" in metrics
        assert "approval_rate" in metrics
        assert "edit_rate" in metrics
        assert "rejection_rate" in metrics
        assert metrics["total_reviews"] == 3

    def test_get_current_thresholds_returns_dict(self):
        """get_current_thresholds should return a dictionary with threshold values."""
        engine = LearningEngine()
        thresholds = engine.get_current_thresholds()

        assert "auto_send_threshold" in thresholds
        assert "queue_high_threshold" in thresholds
        assert isinstance(thresholds["auto_send_threshold"], float)
        assert isinstance(thresholds["queue_high_threshold"], float)

    def test_reset_learning_restores_defaults(self):
        """reset_learning should restore default thresholds."""
        engine = LearningEngine()

        # Modify thresholds
        engine.auto_send_threshold = 0.92
        engine.queue_high_threshold = 0.78
        engine.record_review("q1", 0.85, "approved", "SPOT_CHECK")

        # Reset
        engine.reset_learning()

        # Should be back to defaults
        assert engine.auto_send_threshold == 0.90
        assert engine.queue_high_threshold == 0.75
        assert len(engine._review_history) == 0


# =============================================================================
# CYCLE 5: main.py Integration Tests
# =============================================================================


class TestLearningEngineMainIntegration:
    """Test LearningEngine integration in main.py lifespan."""

    @pytest.fixture
    def mock_settings(self, tmp_path):
        """Create mock settings with temporary data directory."""
        from unittest.mock import MagicMock

        settings = MagicMock()
        settings.DATA_DIR = str(tmp_path)
        settings.DEBUG = True
        settings.ENVIRONMENT = "test"
        return settings

    def test_learning_engine_exists_in_app_state(self):
        """learning_engine is available in app.state after startup."""
        # This test verifies the main.py integration pattern
        # We test by importing and checking the app has the expected attribute
        # after lifespan completes
        # The app should have learning_engine configured in lifespan
        # We check that the lifespan function references LearningEngine
        import inspect

        from app.main import lifespan

        source = inspect.getsource(lifespan)
        assert (
            "learning_engine" in source
        ), "lifespan should initialize learning_engine in app.state"

    def test_learning_engine_load_state_called_on_startup(self):
        """LearningEngine.load_state should be called during startup."""
        import inspect

        from app.main import lifespan

        source = inspect.getsource(lifespan)
        # Check that load_state is called during initialization
        assert (
            "load_state" in source
        ), "lifespan should call load_state to restore persisted thresholds"

    def test_learning_engine_save_state_called_on_shutdown(self):
        """LearningEngine.save_state should be called during shutdown."""
        import inspect

        from app.main import lifespan

        source = inspect.getsource(lifespan)
        # Check that save_state is called during shutdown
        assert (
            "save_state" in source
        ), "lifespan should call save_state to persist thresholds on shutdown"


# =============================================================================
# CYCLE 6: Record Feedback on Approve/Reject Tests
# =============================================================================


class TestApproveRejectRecordsFeedback:
    """Test that approve/reject endpoints record feedback to LearningEngine."""

    def test_approve_records_generation_confidence_to_learning_engine(self):
        """Approving records generation_confidence (not final_score) to LearningEngine."""
        # This test verifies the training.py integration pattern
        # We check that the approve endpoint code references learning_engine
        import inspect

        from app.routes.admin.training import approve_candidate

        source = inspect.getsource(approve_candidate)
        # Verify the approve endpoint calls learning_engine.record_review
        assert (
            "learning_engine" in source
        ), "approve_candidate should access learning_engine from app state"
        assert (
            "record_review" in source
        ), "approve_candidate should call record_review on learning_engine"

    def test_reject_records_generation_confidence_to_learning_engine(self):
        """Rejecting records generation_confidence (not final_score) to LearningEngine."""
        import inspect

        from app.routes.admin.training import reject_candidate

        source = inspect.getsource(reject_candidate)
        # Verify the reject endpoint calls learning_engine.record_review
        assert (
            "learning_engine" in source
        ), "reject_candidate should access learning_engine from app state"
        assert (
            "record_review" in source
        ), "reject_candidate should call record_review on learning_engine"

    def test_approve_uses_generation_confidence_not_final_score(self):
        """Approve should use generation_confidence, not final_score for learning."""
        import inspect

        from app.routes.admin.training import approve_candidate

        source = inspect.getsource(approve_candidate)
        # The confidence parameter should reference generation_confidence
        assert (
            "generation_confidence" in source
        ), "approve_candidate should use generation_confidence for learning, not final_score"


# =============================================================================
# CYCLE 7: Learning Endpoints Tests
# =============================================================================


class TestLearningEndpoints:
    """Test learning metrics and readiness endpoints exist in training routes."""

    def test_learning_metrics_endpoint_exists(self):
        """GET /admin/training/learning/metrics endpoint should exist."""
        from app.routes.admin.training import router

        # Check that the router has a route for /learning/metrics
        routes = [r.path for r in router.routes]
        assert "/learning/metrics" in routes or any(
            "/learning/metrics" in str(r.path) for r in router.routes
        ), "learning/metrics endpoint should be defined in training router"

    def test_learning_readiness_endpoint_exists(self):
        """GET /admin/training/learning/readiness endpoint should exist."""
        from app.routes.admin.training import router

        # Check that the router has a route for /learning/readiness
        routes = [r.path for r in router.routes]
        assert "/learning/readiness" in routes or any(
            "/learning/readiness" in str(r.path) for r in router.routes
        ), "learning/readiness endpoint should be defined in training router"

    def test_learning_metrics_returns_thresholds(self):
        """Learning metrics endpoint should return current_thresholds."""
        import inspect

        from app.routes.admin.training import get_learning_metrics

        source = inspect.getsource(get_learning_metrics)
        assert (
            "current_thresholds" in source or "get_current_thresholds" in source
        ), "get_learning_metrics should return current_thresholds"

    def test_learning_readiness_uses_checker(self):
        """Learning readiness endpoint should use LaunchReadinessChecker."""
        import inspect

        from app.routes.admin.training import get_launch_readiness

        source = inspect.getsource(get_launch_readiness)
        assert (
            "LaunchReadinessChecker" in source or "check_readiness" in source
        ), "get_launch_readiness should use LaunchReadinessChecker"


# =============================================================================
# CYCLE 8: Apply Learned Thresholds in Pipeline Tests
# =============================================================================


class TestPipelineUsesLearnedThresholds:
    """Test that the pipeline can use learned thresholds from LearningEngine."""

    def test_pipeline_accepts_learning_engine_parameter(self):
        """UnifiedPipelineService should accept optional learning_engine parameter."""
        import inspect

        from app.services.training.unified_pipeline_service import (
            UnifiedPipelineService,
        )

        # Check __init__ signature accepts learning_engine
        sig = inspect.signature(UnifiedPipelineService.__init__)
        params = list(sig.parameters.keys())
        assert (
            "learning_engine" in params
        ), "UnifiedPipelineService.__init__ should accept learning_engine parameter"

    def test_determine_routing_uses_learning_engine_when_available(self):
        """_determine_routing should use LearningEngine thresholds post-calibration."""
        import inspect

        from app.services.training.unified_pipeline_service import (
            UnifiedPipelineService,
        )

        source = inspect.getsource(UnifiedPipelineService._determine_routing)
        # Check that the function references learning_engine
        assert (
            "learning_engine" in source
        ), "_determine_routing should check self.learning_engine for threshold values"
        # Check that it uses get_routing_recommendation
        assert (
            "get_routing_recommendation" in source
        ), "_determine_routing should use learning_engine.get_routing_recommendation"


class TestLaunchReadinessChecker:
    """Test launch readiness checking."""

    def test_check_readiness_returns_expected_structure(self):
        """check_readiness should return expected structure."""
        engine = LearningEngine()
        checker = LaunchReadinessChecker(engine)

        result = checker.check_readiness()

        assert "is_ready" in result
        assert "readiness_score" in result
        assert "criteria" in result
        assert "recommendations" in result

    def test_not_ready_with_zero_reviews(self):
        """System should not be ready with zero reviews."""
        engine = LearningEngine()
        checker = LaunchReadinessChecker(engine)

        result = checker.check_readiness()

        assert result["is_ready"] is False
        assert result["criteria"]["sufficient_data"]["passed"] is False
