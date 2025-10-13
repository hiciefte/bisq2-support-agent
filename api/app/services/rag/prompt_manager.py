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
from app.utils.logging import redact_pii
from langchain.prompts import ChatPromptTemplate
from langchain_core.documents import Document

logger = logging.getLogger(__name__)


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
                role = exchange.role
                content = exchange.content
                if role == "user":
                    formatted_history.append(f"Human: {content}")
                elif role == "assistant":
                    formatted_history.append(f"Assistant: {content}")
                else:
                    logger.warning(
                        f"Unknown exchange role in chat history: {role}. Expected 'user' or 'assistant'."
                    )
            # Check if this is a dictionary with role/content keys (standard format)
            elif (
                isinstance(exchange, dict)
                and "role" in exchange
                and "content" in exchange
            ):
                role = exchange["role"]
                content = exchange["content"]
                if role == "user":
                    formatted_history.append(f"Human: {content}")
                elif role == "assistant":
                    formatted_history.append(f"Assistant: {content}")
                else:
                    logger.warning(
                        f"Unknown exchange role in chat history: {role}. Expected 'user' or 'assistant'."
                    )
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

        # Custom system template with proper sections for context, chat history, and question
        system_template = f"""You are an assistant for question-answering tasks about Bisq 2.

IMPORTANT: You are a Bisq 2 support assistant.
Pay special attention to content marked with [VERSION: Bisq 2] as it is specifically about Bisq 2.
If content is marked with [VERSION: Bisq 1], it refers to the older version of Bisq and may not be applicable to Bisq 2.
Content marked with [VERSION: Both] contains information relevant to both versions.
Content marked with [VERSION: General] is general information that may apply to both versions.

Always prioritize Bisq 2 specific information in your answers.
If you don't know the answer, just say that you don't know.
Use three sentences maximum and keep the answer concise.{additional_guidance}

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
                    context = context[: self.settings.MAX_CONTEXT_LENGTH]

                # Log the complete prompt and context for debugging
                logger.info("=== DEBUG: Complete Prompt and Context ===")
                logger.info(f"Question: {redact_pii(preprocessed_question)}")
                logger.info(f"Chat History: {redact_pii(chat_history_str)}")
                logger.info("Context:")
                logger.info(redact_pii(context))
                logger.info("=== End Debug Log ===")

                # Format the prompt
                formatted_prompt = self.prompt.format(
                    question=preprocessed_question,
                    chat_history=chat_history_str,
                    context=context,
                )

                # Log formatted prompt at DEBUG level
                logger.debug("=== DEBUG: Complete Formatted Prompt ===")
                logger.debug(formatted_prompt)
                logger.debug("=== End Debug Log ===")

                # Generate response
                response_text = llm.invoke(formatted_prompt)
                response_content = (
                    response_text.content
                    if hasattr(response_text, "content")
                    else str(response_text)
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
