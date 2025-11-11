"""
Prompt Manager for RAG system prompt templates and chat history formatting.

This module handles:
- Chat history formatting from various input formats
- RAG prompt template creation with feedback integration
- Context-only prompt generation for fallback scenarios
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional, Union

from app.core.config import Settings
from app.utils.instrumentation import instrument_stage, track_tokens_and_cost
from app.utils.logging import redact_pii
from langchain_core.documents import Document
from langchain_core.prompts import ChatPromptTemplate

logger = logging.getLogger(__name__)


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
        self.prompt: Optional[ChatPromptTemplate] = None

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
            # Check if this is a dictionary with user/assistant keys (legacy format)
            elif isinstance(exchange, dict):
                user_msg = exchange.get("user", "")
                ai_msg = exchange.get("assistant", "")
                if user_msg:
                    formatted_history.append(f"Human: {user_msg}")
                if ai_msg:
                    formatted_history.append(f"Assistant: {ai_msg}")
            else:
                logger.warning(
                    f"Unknown exchange type in chat history: {type(exchange)}"
                )

        return "\n".join(formatted_history)

    def create_rag_prompt(self) -> ChatPromptTemplate:
        """Create the RAG prompt template with feedback integration.

        Incorporates feedback guidance if available and creates a template
        optimized for Bisq 2 support with version awareness.

        Returns:
            ChatPromptTemplate configured for RAG queries
        """
        # Get prompt guidance from the FeedbackService if available
        additional_guidance = ""
        if self.feedback_service:
            guidance = self.feedback_service.get_prompt_guidance()
            if guidance:
                # Join guidance list into a single string with proper formatting
                guidance_text = "\n".join(f"- {item}" for item in guidance)
                additional_guidance = (
                    f"\n\nIMPORTANT GUIDANCE BASED ON USER FEEDBACK:\n{guidance_text}"
                )
                logger.info(f"Added prompt guidance: {guidance_text}")

        # Custom system template with version-aware conditional logic
        system_template = f"""You are a support assistant primarily focused on Bisq 2, but with knowledge of Bisq 1 when relevant.

VERSION HANDLING INSTRUCTIONS:
Your PRIMARY focus is Bisq 2. When the user doesn't specify a version, assume they're asking about Bisq 2.

1. If the user asks about Bisq 2 (default) or doesn't specify a version:
   - Prioritize content marked with [VERSION: Bisq 2]
   - Use content marked with [VERSION: Both] or [VERSION: General] as secondary sources
   - IGNORE content marked with [VERSION: Bisq 1] unless it provides essential context

2. If the user explicitly asks about Bisq 1 (mentions "Bisq 1" or "Bisq1"):
   - First check if you have [VERSION: Bisq 1] or [VERSION: Both] content in the context below
   - IF YES: Provide the information and add this note: "Note: This information is for Bisq 1. For Bisq 2 support, please ask specifically about Bisq 2."
   - IF NO: Respond: "I don't have specific information about that for Bisq 1 in my knowledge base. However, I can help you with Bisq 2 questions. Would you like information about Bisq 2 instead, or do you need help finding Bisq 1 resources?"

3. If the user asks to compare versions or wants information about both:
   - Use all available content and clearly label which version each piece of information applies to
   - Highlight key differences when available

RESPONSE GUIDELINES:
- Always be clear about which version you're discussing
- Keep answers concise (2-3 sentences maximum)
- If you don't know the answer for the requested version, say so clearly{additional_guidance}

Question: {{question}}

Chat History: {{chat_history}}

Context: {{context}}

Answer:"""

        # Create the prompt template
        self.prompt = ChatPromptTemplate.from_template(system_template)
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
        # Detect version from question
        question_lower = question.lower()
        is_bisq1_query = "bisq 1" in question_lower or "bisq1" in question_lower

        if is_bisq1_query:
            context_only_prompt = f"""You are a support assistant for Bisq. A user has asked a question about Bisq 1, but no relevant documents were found in the knowledge base.

IMPORTANT: Only answer if the question can be answered based on the previous conversation below. If the question is about a NEW topic not covered in the conversation history, you MUST inform them appropriately.

Previous Conversation:
{chat_history_str}

Current Question: {question}

Instructions:
- If the answer is clearly in the conversation above, provide it with a note: "Note: This information is for Bisq 1."
- If this is a follow-up about something mentioned in the conversation, answer based on that context
- If this is a NEW topic about Bisq 1 not in the conversation, respond: "I don't have specific information about that for Bisq 1 in my knowledge base. However, I can help you with Bisq 2 questions. Would you like information about Bisq 2 instead, or do you need help finding Bisq 1 resources?"
- Keep your answer to 2-3 sentences maximum

Answer:"""
        else:
            context_only_prompt = f"""You are a Bisq 2 support assistant. A user has asked a follow-up question, but no relevant documents were found in the knowledge base.

IMPORTANT: Only answer if the question can be answered based on the previous conversation below. If the question is about a NEW topic not covered in the conversation history, you MUST say you don't have information.

Previous Conversation:
{chat_history_str}

Current Question: {question}

Instructions:
- If the answer is clearly in the conversation above, provide it concisely
- If this is a follow-up about something mentioned in the conversation, answer based on that context
- If this is a NEW topic not in the conversation, respond: "I don't have information about that in our knowledge base"
- Keep your answer to 2-3 sentences maximum

Answer:"""

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
                    return "I'm sorry, I didn't receive a question. How can I help you with Bisq 2?"

                # Preprocess the question
                preprocessed_question = question.strip()

                # Log the question with privacy protection
                logger.info(f"Processing question: {redact_pii(preprocessed_question)}")

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
                logger.debug(f"Question: {redact_pii(preprocessed_question)}")
                logger.debug(f"Chat History: {redact_pii(chat_history_str)}")
                logger.debug("Context:")
                logger.debug(redact_pii(context))
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
                        logger.info(f"Content sample: {redact_pii(sample)}")
                    return response_content
                else:
                    logger.warning("Empty response received from LLM")
                    return "I apologize, but I couldn't generate a proper response based on the available information."
            except Exception as e:
                logger.error(f"Error generating response: {e!s}", exc_info=True)
                return "I apologize, but I'm having technical difficulties processing your request. Please try again later."

        logger.info("Custom RAG chain created successfully")
        return generate_response

    def get_prompt(self) -> Optional[ChatPromptTemplate]:
        """Get the current prompt template.

        Returns:
            ChatPromptTemplate or None if not yet created
        """
        return self.prompt
