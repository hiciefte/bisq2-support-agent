"""
Prompt Manager for RAG system prompt templates and chat history formatting.

This module handles:
- Chat history formatting from various input formats
- RAG prompt template creation with feedback integration
- Context-only prompt generation for fallback scenarios
"""

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Union

from app.core.config import Settings
from app.core.pii_utils import redact_for_logs
from app.prompts import error_messages
from app.prompts.runtime_policy import (
    build_answer_contract_block,
    build_ambiguous_support_workflow_block,
    build_bisq1_workflow_guardrails_block,
    build_context_only_policy_block,
    build_evidence_discipline_block,
    build_feedback_guidance_block,
    build_live_data_policy_block,
    build_live_data_rendering_block,
    build_prompt_priority_block,
    build_protocol_handling_block,
)
from app.prompts.soul import load_soul
from app.utils.instrumentation import instrument_stage, track_tokens_and_cost
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


@dataclass
class _SimplePrompt:
    template: str


@dataclass
class _SimpleMessage:
    prompt: _SimplePrompt


class SimpleChatPromptTemplate:
    """Lightweight prompt template with LangChain-compatible surface."""

    def __init__(self, template: str) -> None:
        self._template = template
        self.messages = [_SimpleMessage(prompt=_SimplePrompt(template=template))]

    @classmethod
    def from_template(cls, template: str) -> "SimpleChatPromptTemplate":
        return cls(template)

    def format(self, **kwargs: Any) -> str:
        result = self._template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result


class RAGPromptNotInitializedError(RuntimeError):
    """Raised when RAG chain is used before prompt initialization."""

    def __init__(self):
        super().__init__(
            "RAG prompt not initialized. Call create_rag_prompt() before using the RAG chain."
        )


class PromptManager:
    """Manager for RAG prompts and chat history formatting.

    This class handles:
    - Standardized chat history formatting
    - RAG prompt template creation
    - Context-only fallback prompts
    - RAG chain generation
    """

    def __init__(self, settings: Settings, feedback_service=None):
        """Initialize the prompt manager.

        Args:
            settings: Application settings for configuration
            feedback_service: Optional FeedbackService for prompt guidance
        """
        self.settings = settings
        self.feedback_service = feedback_service
        self.prompt: Optional[SimpleChatPromptTemplate] = None

        logger.info("Prompt manager initialized")

    def _format_message_by_role(self, role: str, content: str) -> Optional[str]:
        """Format a single message with role prefix.

        Args:
            role: The role of the message sender ('user' or 'assistant')
            content: The message content

        Returns:
            Formatted message string with prefix, or None if role is unknown
        """
        if role == "user":
            return f"Human: {content}"
        elif role == "assistant":
            return f"Assistant: {content}"
        else:
            logger.warning(
                f"Unknown exchange role in chat history: {role}. Expected 'user' or 'assistant'."
            )
            return None

    def format_chat_history(
        self, chat_history: List[Union[Dict[str, str], Any]]
    ) -> str:
        """Format chat history from various input formats into standard string format.

        Handles both ChatMessage objects (with role/content attributes) and
        dictionary formats (with user/assistant or role/content keys).

        Args:
            chat_history: List of chat exchanges in various formats

        Returns:
            Formatted chat history string with "Human:" and "Assistant:" prefixes
        """
        if not chat_history or len(chat_history) == 0:
            return ""

        formatted_history = []
        # Use only the most recent MAX_CHAT_HISTORY_LENGTH exchanges
        recent_history = chat_history[-self.settings.MAX_CHAT_HISTORY_LENGTH :]

        for exchange in recent_history:
            # Check if this is a ChatMessage object with role/content attributes
            if hasattr(exchange, "role") and hasattr(exchange, "content"):
                formatted = self._format_message_by_role(
                    exchange.role, exchange.content
                )
                if formatted:
                    formatted_history.append(formatted)
            # Check if this is a dictionary with role/content keys (standard format)
            elif (
                isinstance(exchange, dict)
                and "role" in exchange
                and "content" in exchange
            ):
                formatted = self._format_message_by_role(
                    exchange["role"], exchange["content"]
                )
                if formatted:
                    formatted_history.append(formatted)
            else:
                logger.warning(
                    f"Unknown exchange type in chat history: {type(exchange)}"
                )

        return "\n".join(formatted_history)

    def create_rag_prompt(self) -> SimpleChatPromptTemplate:
        """Create the RAG prompt template with feedback integration.

        Incorporates feedback guidance if available and creates a template
        optimized for Bisq 2 support with version awareness.

        Returns:
            Prompt template configured for RAG queries
        """
        # Get prompt guidance from the FeedbackService if available
        guidance_items: list[str] = []
        if self.feedback_service:
            guidance = self.feedback_service.get_prompt_guidance()
            if guidance:
                guidance_items = [str(item).strip() for item in guidance if str(item).strip()]
                if guidance_items:
                    logger.info("Added prompt guidance: %s", " | ".join(guidance_items))

        # Prepend soul personality layer
        soul_text = load_soul()
        prompt_sections = [
            soul_text,
            build_prompt_priority_block(),
            build_evidence_discipline_block(),
            build_bisq1_workflow_guardrails_block(),
            build_ambiguous_support_workflow_block(),
            build_protocol_handling_block(),
            build_live_data_policy_block(),
            build_live_data_rendering_block(),
            build_answer_contract_block(),
            build_feedback_guidance_block(guidance_items),
            "Question: {question}\n\nChat History: {chat_history}\n\nContext: {context}\n\nAnswer:",
        ]
        system_template = "\n\n---\n\n".join(
            section for section in prompt_sections if section
        )

        # Create the prompt template
        self.prompt = SimpleChatPromptTemplate.from_template(system_template)
        logger.info(f"Custom RAG prompt created with {len(system_template)} characters")

        return self.prompt

    def create_context_only_prompt(self, question: str, chat_history_str: str) -> str:
        """Create a prompt for answering from conversation context only.

        Used when no relevant documents are found but conversation history exists.

        Args:
            question: The user's question
            chat_history_str: Formatted chat history string

        Returns:
            Prompt string for context-only answering
        """
        # Detect protocol from question (Bisq 1 = Multisig v1 protocol)
        question_lower = question.lower()
        is_multisig_query = (
            "bisq 1" in question_lower
            or "bisq1" in question_lower
            or "multisig" in question_lower
        )

        soul_text = load_soul()
        context_sections = [
            soul_text,
            build_answer_contract_block(),
            build_context_only_policy_block(is_multisig_query),
            f"Previous Conversation:\n{chat_history_str}",
            f"Current Question: {question}",
            "Answer:",
        ]
        context_only_prompt = "\n\n---\n\n".join(
            section for section in context_sections if section
        )

        return context_only_prompt

    def create_rag_chain(
        self,
        llm: Any,
        retrieve_func: Callable[[str], List[Document]],
        format_docs_func: Callable[[List[Document]], str],
    ) -> Callable:
        """Create the RAG chain function for query processing.

        Args:
            llm: Initialized language model instance
            retrieve_func: Function to retrieve documents with version priority
            format_docs_func: Function to format retrieved documents

        Returns:
            Callable RAG chain function
        """

        @instrument_stage("generation")
        def generate_response(
            question: str,
            chat_history: Union[List[Union[Dict[str, str], Any]], None] = None,
        ) -> str:
            """Generate response using RAG pipeline.

            Args:
                question: User's question
                chat_history: Optional chat history

            Returns:
                Generated response string
            """
            # Initialize response_start_time at the beginning to avoid reference before assignment
            response_start_time = time.time()

            try:
                if not question:
                    return error_messages.NO_QUESTION

                # Preprocess the question
                preprocessed_question = question.strip()

                # Log the question with privacy protection
                logger.info(
                    f"Processing question: {redact_for_logs(preprocessed_question)}"
                )

                # Set default chat history
                if chat_history is None:
                    chat_history = []

                # Format chat history for the prompt
                chat_history_str = self.format_chat_history(chat_history)

                # Retrieve relevant documents with version priority
                docs = retrieve_func(preprocessed_question)

                logger.info(f"Retrieved {len(docs)} relevant documents")

                # Format documents for the prompt
                context = format_docs_func(docs)

                # Check context length and truncate if necessary to fit in prompt
                if len(context) > self.settings.MAX_CONTEXT_LENGTH:
                    logger.warning(
                        f"Context too long: {len(context)} chars, truncating to {self.settings.MAX_CONTEXT_LENGTH}"
                    )
                    # Try to truncate at last sentence boundary to avoid cutting mid-sentence
                    truncated = context[: self.settings.MAX_CONTEXT_LENGTH]
                    last_period = truncated.rfind(". ")
                    # Only use sentence boundary if we don't lose more than 20% of content
                    # Explicit check for -1 (not found) to document intent clearly
                    if (
                        last_period != -1
                        and last_period > self.settings.MAX_CONTEXT_LENGTH * 0.8
                    ):
                        context = truncated[: last_period + 1]
                    else:
                        context = truncated

                # Log the complete prompt and context for debugging
                logger.debug("=== DEBUG: Complete Prompt and Context ===")
                logger.debug(f"Question: {redact_for_logs(preprocessed_question)}")
                logger.debug(f"Chat History: {redact_for_logs(chat_history_str)}")
                logger.debug("Context:")
                logger.debug(redact_for_logs(context))
                logger.debug("=== End Debug Log ===")

                # Ensure prompt is initialized before formatting
                if self.prompt is None:
                    raise RAGPromptNotInitializedError()

                # Format the prompt
                formatted_prompt = self.prompt.format(
                    question=preprocessed_question,
                    chat_history=chat_history_str,
                    context=context,
                )

                # Log prompt metadata only (avoid logging full content for PII/compliance)
                logger.debug(
                    f"Formatted prompt ready - length: {len(formatted_prompt)} chars, "
                    f"has context: {bool(context)}"
                )

                # Generate response (instrumented for monitoring)
                generation_start = time.time()
                response_text = llm.invoke(formatted_prompt)
                _ = time.time() - generation_start  # generation_time for future use

                response_content = (
                    response_text.content
                    if hasattr(response_text, "content")
                    else str(response_text)
                )

                # Track token usage and cost if available
                if hasattr(response_text, "usage") and response_text.usage:
                    usage = response_text.usage
                    track_tokens_and_cost(
                        input_tokens=usage.get("prompt_tokens", 0),
                        output_tokens=usage.get("completion_tokens", 0),
                        input_cost_per_token=self.settings.OPENAI_INPUT_COST_PER_TOKEN,
                        output_cost_per_token=self.settings.OPENAI_OUTPUT_COST_PER_TOKEN,
                    )
                    logger.debug(
                        f"Token usage: {usage.get('prompt_tokens', 0)} input + "
                        f"{usage.get('completion_tokens', 0)} output = "
                        f"{usage.get('total_tokens', 0)} total"
                    )

                # Calculate response time
                response_time = time.time() - response_start_time

                # Log response information with privacy protection
                if response_content:
                    logger.info(
                        f"Response generated in {response_time:.2f}s, length: {len(response_content)}"
                    )

                    # Log sample in non-production
                    is_production = self.settings.ENVIRONMENT.lower() == "production"
                    if not is_production:
                        sample = (
                            response_content[: self.settings.MAX_SAMPLE_LOG_LENGTH]
                            + "..."
                            if len(response_content)
                            > self.settings.MAX_SAMPLE_LOG_LENGTH
                            else response_content
                        )
                        logger.info(f"Content sample: {redact_for_logs(sample)}")
                    return response_content
                else:
                    logger.warning("Empty response received from LLM")
                    return error_messages.GENERATION_FAILED
            except Exception as e:
                logger.error(f"Error generating response: {e!s}", exc_info=True)
                return error_messages.TECHNICAL_ERROR

        logger.info("Custom RAG chain created successfully")
        return generate_response

    def get_prompt(self) -> Optional[SimpleChatPromptTemplate]:
        """Get the current prompt template.

        Returns:
            Prompt template or None if not yet created
        """
        return self.prompt

    def format_prompt_for_mcp(
        self, context: str, question: str, chat_history_str: str
    ) -> str:
        """Format the RAG prompt as a string for MCP tool invocation.

        Creates the prompt template if not already created, then formats it
        with the provided context, question, and chat history.

        Args:
            context: Formatted document context
            question: The user's question
            chat_history_str: Formatted chat history string

        Returns:
            Formatted prompt string ready for LLM invocation
        """
        # Ensure prompt template exists
        if self.prompt is None:
            self.create_rag_prompt()

        # Format and return the prompt string
        formatted_prompt = self.prompt.format(
            question=question,
            chat_history=chat_history_str,
            context=context,
        )

        logger.debug(f"Formatted MCP prompt - length: {len(formatted_prompt)} chars")

        return formatted_prompt
