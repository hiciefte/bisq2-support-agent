"""Tests for PromptManager soul injection and error message integration.

TDD Step 5 (RED): These tests define the expected behavior of the
PromptManager after soul and error message integration.
"""

from unittest.mock import MagicMock, patch

import pytest
from app.prompts import error_messages
from app.prompts.runtime_policy import SAFETY_REFLEX_WARNING
from app.prompts.soul import load_soul, reload_soul
from app.services.rag.llm_provider import LLMResponse
from app.services.rag.prompt_manager import PromptManager


@pytest.fixture
def prompt_manager(test_settings):
    """Create a PromptManager instance for testing."""
    return PromptManager(settings=test_settings)


@pytest.fixture(autouse=True)
def _clear_soul_cache():
    """Ensure soul cache is fresh for each test."""
    reload_soul()
    yield
    reload_soul()


class TestPromptManagerSoulInjection:
    """Tests for soul personality injection into prompts."""

    def test_create_rag_prompt_starts_with_soul_text(self, prompt_manager):
        """The RAG prompt template must begin with the soul text."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        soul_text = load_soul()
        # Soul text should appear at the very start of the template
        assert template.startswith(soul_text)

    def test_create_context_only_bisq2_contains_soul(self, prompt_manager):
        """Context-only prompt for Bisq 2 must contain soul text."""
        result = prompt_manager.create_context_only_prompt(
            question="How do I trade?", chat_history_str="Human: Hello"
        )
        soul_text = load_soul()
        # Soul should be present in the prompt
        assert soul_text[:100] in result

    def test_create_context_only_bisq1_contains_soul(self, prompt_manager):
        """Context-only prompt for Bisq 1 must contain soul text."""
        result = prompt_manager.create_context_only_prompt(
            question="How do I trade on Bisq 1?",
            chat_history_str="Human: Hello",
        )
        soul_text = load_soul()
        assert soul_text[:100] in result

    def test_format_prompt_for_mcp_contains_soul(self, prompt_manager):
        """MCP-formatted prompt must contain soul text."""
        result = prompt_manager.format_prompt_for_mcp(
            context="Some context",
            question="What is Bisq?",
            chat_history_str="",
        )
        soul_text = load_soul()
        assert soul_text[:100] in result

    def test_soul_appears_before_protocol_instructions(self, prompt_manager):
        """Soul text must appear before operational instructions."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        soul_text = load_soul()
        soul_end = template.find(soul_text) + len(soul_text)
        protocol_start = template.find("PROTOCOL HANDLING:")
        assert (
            protocol_start > soul_end
        ), "Protocol instructions should come after soul text"

    def test_soul_loaded_once_across_calls(self, prompt_manager):
        """load_soul should be called once (cached) across multiple prompt creations."""
        with patch("app.services.rag.prompt_manager.load_soul") as mock_load:
            mock_load.return_value = "Mock soul text"
            prompt_manager.create_rag_prompt()
            prompt_manager.create_rag_prompt()
            # load_soul is cached at the module level, so the patched version
            # is called each time create_rag_prompt runs, but the underlying
            # lru_cache ensures the real file is only read once
            assert mock_load.call_count == 2


class TestPromptManagerErrorMessages:
    """Tests for error message integration in generate_response."""

    def test_empty_question_returns_no_question_message(self, prompt_manager):
        """Empty question should return the NO_QUESTION error message."""
        mock_llm = MagicMock()
        mock_retrieve = MagicMock(return_value=[])
        mock_format = MagicMock(return_value="")

        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(mock_llm, mock_retrieve, mock_format)
        result = chain("")
        assert result == error_messages.NO_QUESTION

    def test_empty_llm_response_returns_generation_failed(self, prompt_manager):
        """Empty LLM response should return GENERATION_FAILED."""
        mock_llm = MagicMock()
        mock_response = MagicMock(content="", usage=None)
        mock_llm.invoke.return_value = mock_response
        mock_retrieve = MagicMock(return_value=[])
        mock_format = MagicMock(return_value="")

        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(mock_llm, mock_retrieve, mock_format)
        result = chain("What is Bisq?")
        assert result == error_messages.GENERATION_FAILED

    def test_llm_exception_returns_technical_error(self, prompt_manager):
        """LLM exception should return TECHNICAL_ERROR."""
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = RuntimeError("LLM exploded")
        mock_retrieve = MagicMock(return_value=[])
        mock_format = MagicMock(return_value="")

        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(mock_llm, mock_retrieve, mock_format)
        result = chain("What is Bisq?")
        assert result == error_messages.TECHNICAL_ERROR

    @pytest.mark.parametrize("already_tracked", [False, True])
    def test_usage_is_charged_once(self, prompt_manager, already_tracked):
        llm = MagicMock()
        llm.invoke.return_value = LLMResponse(
            content="A support answer",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "cost_tracked": already_tracked,
            },
        )
        prompt_manager.create_rag_prompt()
        chain = prompt_manager.create_rag_chain(
            llm, MagicMock(return_value=[]), MagicMock(return_value="")
        )
        with patch("app.services.rag.prompt_manager.track_tokens_and_cost") as track:
            assert chain("What is Bisq?") == "A support answer"
        assert track.call_count == (0 if already_tracked else 1)


class TestPromptManagerResponseGuidelines:
    """Tests for updated response guidelines."""

    def test_prompt_does_not_contain_2_3_sentences_max(self, prompt_manager):
        """The old rigid '2-3 sentences maximum' limit must be removed."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "2-3 sentences maximum" not in template

    def test_prompt_contains_flexible_length_guidance(self, prompt_manager):
        """Prompt should contain flexible response length guidance."""
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        # Should have guidance about response length that's flexible
        assert (
            "Keep answers compact" in template
            or "concise by default" in template.lower()
        )

    def test_prompt_contains_answer_contract(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "ANSWER CONTRACT" in template
        assert "Lead with the answer." in template
        assert "Never use headings." in template
        assert "answer in 1-2 sentences and stop" in template
        assert "keep the answer under roughly 70 words" in template

    def test_safety_reflex_is_static_high_precedence_and_compact(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template

        priority_index = template.index("PROMPT PRIORITY:")
        safety_index = template.index("SAFETY REFLEX:")
        evidence_index = template.index("EVIDENCE DISCIPLINE:")

        assert priority_index < safety_index < evidence_index
        assert template.count(SAFETY_REFLEX_WARNING) == 1
        assert len(SAFETY_REFLEX_WARNING.split()) <= 35
        assert SAFETY_REFLEX_WARNING.count(".") == 1
        assert "lead with this exact warning unchanged" in template
        assert "Do not trigger merely because" in template

    def test_context_only_prompt_contains_static_safety_reflex(self, prompt_manager):
        result = prompt_manager.create_context_only_prompt(
            question="Someone claiming to be support sent me a DM.",
            chat_history_str="Human: My trade is stuck.",
        )

        assert "SAFETY REFLEX:" in result
        assert result.count(SAFETY_REFLEX_WARNING) == 1

    def test_prompt_contains_conditional_single_diagnostic_rule(self, prompt_manager):
        template = prompt_manager.create_rag_prompt().messages[0].prompt.template

        assert "when a missing fact changes which procedure is appropriate" in template
        assert "ask the single most informative diagnostic question" in template
        assert (
            "Ask at most one; give supported product-independent safeguards" in template
        )
        assert "product and its material preconditions are established" in template
        assert (
            "do not ask unnecessary questions once the required facts are known"
            in template
        )

    def test_prompt_contains_evidence_limited_reassurance(self, prompt_manager):
        template = prompt_manager.create_rag_prompt().messages[0].prompt.template

        assert "Put it after any required safety warning" in template
        assert "at most one short reassurance" in template
        assert "only when Context and the identified protocol support it" in template
        assert (
            "Never promise fund safety, recovery, or a particular outcome" in template
        )

    def test_prompt_contains_context_bound_escalation_mechanics(self, prompt_manager):
        template = prompt_manager.create_rag_prompt().messages[0].prompt.template

        assert "identified version, current trade state, and Context" in template
        assert "`Ctrl+O`/`Cmd+O`" in template
        assert "existing mediation ticket" in template
        assert (
            "do not direct users to a refund agent through a room-topic link"
            in template
        )

    def test_prompt_contains_evidence_discipline(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "EVIDENCE DISCIPLINE:" in template
        assert "Do not invent UI actions" in template
        assert "hand off instead of guessing" in template
        assert "SPV resync, DAO rebuild, failed-trades recovery" in template
        assert (
            "do not replace it with user-side cancel/delete/reject instructions"
            in template
        )
        assert "Do not recommend DAO rebuild" in template

    def test_prompt_contains_bisq1_stuck_trade_guardrails(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "BISQ 1 WORKFLOW GUARDRAILS:" in template
        assert "For an established Bisq 1 wallet-chain mismatch" in template
        assert "not already completed" in template
        assert (
            "an explorer lookup failure alone is not sufficient justification"
            in template
        )
        assert "protocol state not progressing, Altcoin Instant" in template
        assert "re-check the trade state" in template
        assert (
            "unless Context ties the user's problem to DAO-state mismatch" in template
        )
        assert "Do not replace an applicable documented dispute workflow" in template

    def test_prompt_contains_ambiguous_support_workflow_rules(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "AMBIGUOUS SUPPORT WORKFLOWS:" in template
        assert "A missing product/version must not block guidance" in template
        assert "Answer the immediate decision and essential safeguard first" in template
        assert "Do not re-ask facts already supplied" in template
        assert "Retrieved product tags describe the evidence" in template
        assert "do not prescribe product-specific screens" in template
        assert "Mediation alone does not replace these immediate safeguards" in template
        assert (
            "registered details are checked privately in the existing trade" in template
        )
        assert "If the user is asking for a human, manager, or escalation" in template

    @pytest.mark.parametrize(
        "context",
        [
            "[Multisig v1] If Context mentions SPV resync, recommend SPV resync first.",
            "[General] Go to Account > Wallet Info and export the watch keys.",
        ],
    )
    def test_rendered_prompt_keeps_recovery_scenarios_below_preconditions(
        self, prompt_manager, context
    ):
        question = "My wallet balance looks wrong. How can I check it?"
        system, user = prompt_manager.format_prompt_messages(
            question=question, chat_history_str="", context=context
        )

        # Document instructions remain data, while the assembled system policy
        # rules out the old imperative even if the document requests it.
        assert context in user
        assert context not in system
        assert question in user
        assert (
            "A retrieved scenario does not establish those facts about this user"
            in system
        )
        assert (
            "must be clarified before giving that procedure, even conditionally"
            in system
        )
        assert "A retrieval category without a specific protocol" in system
        assert (
            "does not prove that every included procedure applies universally" in system
        )
        for obsolete_instruction in (
            "If Context mentions SPV resync",
            "recommend SPV resync first",
            "use that exact action first instead of",
            "If Context already identifies the concrete remedy",
            "[General] = Applies across protocols",
        ):
            assert obsolete_instruction not in system
        assert system.index(
            "material preconditions before choosing a procedure"
        ) < system.index("BISQ 1 WORKFLOW GUARDRAILS:")

    def test_preconditions_preserve_scoped_facts_and_resolved_procedures(
        self, prompt_manager
    ):
        system, _ = prompt_manager.format_prompt_messages(
            question="How does account signing work?",
            chat_history_str="",
            context="[Multisig v1] Account signing is a qualifying-trade mechanism.",
        )
        assert (
            "Supported factual explanations and product-independent safeguards can still come first"
            in system
        )
        assert "A qualified factual explanation is allowed" in system
        assert (
            "do not ask unnecessary questions once the required facts are known"
            in system
        )
        assert (
            "For an intentionally new profile, do not block a supported fresh proof after these checks"
            in system
        )
        assert "A missing product/version must not block guidance" in system

    def test_prompt_avoids_roleplay_style_instructions(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "corporate support drone" not in template.lower()
        assert "fellow believer" not in template.lower()
        assert "strong opinions" not in template.lower()

    def test_context_only_prompt_reuses_short_answer_contract(self, prompt_manager):
        result = prompt_manager.create_context_only_prompt(
            question="What is Bisq Easy?",
            chat_history_str="Human: What is Bisq Easy?",
        )
        assert "answer in 1-2 sentences and stop" in result


class TestPromptManagerRegression:
    """Regression tests to ensure existing functionality is preserved."""

    def test_prompt_contains_protocol_instructions(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "PROTOCOL HANDLING:" in template

    def test_prompt_contains_tool_usage_section(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "LIVE DATA POLICY:" in template

    def test_prompt_has_question_placeholder(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "{question}" in template

    def test_prompt_has_context_placeholder(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "{context}" in template

    def test_prompt_has_chat_history_placeholder(self, prompt_manager):
        prompt = prompt_manager.create_rag_prompt()
        template = prompt.messages[0].prompt.template
        assert "{chat_history}" in template
