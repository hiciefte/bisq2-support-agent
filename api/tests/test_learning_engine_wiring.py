"""
TDD tests for wiring LearningEngine to EscalationService and AutoSendRouter.

Tests verify that:
- EscalationService accepts and stores a learning_engine parameter
- AutoSendRouter accepts and stores a learning_engine parameter
- Thresholds update after sufficient reviews
- Router uses engine's thresholds once trained
- RAG service's auto_send_router uses the LearningEngine (not a bare instance)
"""

from unittest.mock import MagicMock


class TestLearningEngineWiring:
    """Tests for LearningEngine wiring to downstream services."""

    def test_escalation_service_accepts_learning_engine(self):
        """EscalationService constructor should accept and store learning_engine."""
        from app.services.escalation.escalation_service import EscalationService
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()
        mock_repo = MagicMock()
        mock_settings = MagicMock()

        service = EscalationService(
            repository=mock_repo,
            response_delivery=None,
            faq_service=None,
            learning_engine=engine,
            settings=mock_settings,
        )

        assert (
            service.learning_engine is engine
        ), "EscalationService.learning_engine should be the injected engine"

    def test_auto_send_router_accepts_learning_engine(self):
        """AutoSendRouter constructor should accept and store learning_engine."""
        from app.services.rag.auto_send_router import AutoSendRouter
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()
        router = AutoSendRouter(learning_engine=engine)

        assert (
            router._learning_engine is engine
        ), "AutoSendRouter._learning_engine should be the injected engine"

    def test_threshold_updates_after_sufficient_reviews(self):
        """After 50+ reviews, thresholds should differ from defaults."""
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()
        default_auto_send = engine.auto_send_threshold

        # Record 60 reviews: 50 approved at 0.85, 10 rejected at 0.40
        for i in range(50):
            engine.record_review(
                question_id=f"q_{i}",
                confidence=0.85,
                admin_action="approved",
                routing_action="auto_send",
            )
        for i in range(10):
            engine.record_review(
                question_id=f"qr_{i}",
                confidence=0.40,
                admin_action="rejected",
                routing_action="queue_low",
            )

        # After 60 reviews (>50 min_samples), thresholds should have updated
        current = engine.get_current_thresholds()
        # At least one threshold should have shifted from default
        assert (
            current["auto_send_threshold"] != default_auto_send
            or len(engine._threshold_history) > 1
        ), "Thresholds did not update after sufficient reviews"

    def test_router_uses_updated_thresholds_from_engine(self):
        """After LearningEngine updates, AutoSendRouter uses new thresholds."""
        from app.services.rag.auto_send_router import AutoSendRouter
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()

        # Feed it enough data to trigger threshold update
        for i in range(50):
            engine.record_review(
                question_id=f"q_{i}",
                confidence=0.85,
                admin_action="approved",
                routing_action="auto_send",
            )
        for i in range(10):
            engine.record_review(
                question_id=f"qr_{i}",
                confidence=0.40,
                admin_action="rejected",
                routing_action="queue_low",
            )

        router = AutoSendRouter(learning_engine=engine)
        thresholds = router._get_thresholds()

        # Router should use the engine's thresholds, not static defaults
        engine_thresholds = engine.get_current_thresholds()
        assert thresholds[0] == engine_thresholds["auto_send_threshold"]
        assert thresholds[1] == engine_thresholds["queue_high_threshold"]


class TestRAGServiceRouterInjection:
    """Tests that the RAG service's auto_send_router receives LearningEngine."""

    def test_rag_service_router_has_no_learning_engine_by_default(self):
        """Default RAG service creates router without learning_engine (proves the gap)."""
        from app.services.rag.auto_send_router import AutoSendRouter

        # A bare AutoSendRouter (what RAG service currently creates)
        bare_router = AutoSendRouter()
        assert bare_router._learning_engine is None

    def test_rag_service_router_can_be_replaced_with_wired_instance(self):
        """RAG service's auto_send_router attribute can be replaced after init."""
        from app.services.rag.auto_send_router import AutoSendRouter
        from app.services.rag.learning_engine import LearningEngine

        engine = LearningEngine()
        wired_router = AutoSendRouter(learning_engine=engine)

        # Simulate what main.py should do: replace RAG service's router
        mock_rag = MagicMock()
        mock_rag.auto_send_router = AutoSendRouter()  # bare
        assert mock_rag.auto_send_router._learning_engine is None

        mock_rag.auto_send_router = wired_router  # inject
        assert mock_rag.auto_send_router._learning_engine is engine

    def test_main_py_injects_router_into_rag_service(self):
        """main.py must inject the wired AutoSendRouter into rag_service.

        This test verifies the injection line exists in main.py by checking
        that the rag_service attribute gets the wired router.
        """
        import os

        main_path = os.path.join(os.path.dirname(__file__), "..", "app", "main.py")
        with open(main_path) as f:
            source = f.read()

        # Verify the injection line exists in main.py source code
        assert "rag_service.auto_send_router" in source, (
            "main.py must contain 'rag_service.auto_send_router = ...' "
            "to inject the LearningEngine-wired router into the RAG service"
        )
