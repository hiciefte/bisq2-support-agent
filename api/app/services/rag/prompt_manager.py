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

        # Custom system template with protocol-aware conditional logic
        system_template = f"""You are a support assistant for Bisq, covering both Bisq Easy (the current Bisq 2 protocol) and Multisig v1 (the legacy Bisq 1 protocol).

PROTOCOL HANDLING INSTRUCTIONS:
The question below has been analyzed and categorized. The Context section contains protocol-tagged documents.
Pay CLOSE ATTENTION to the protocol tags in the context: [Bisq Easy], [Multisig v1], [MuSig], or [General].

Protocol mapping:
- [Bisq Easy] = Bisq 2's current trading protocol (reputation-based, no security deposits)
- [Multisig v1] = Bisq 1's legacy protocol (2-of-2 multisig with security deposits)
- [MuSig] = Future Bisq 2 protocol (not yet released)
- [General] = Applies to all protocols

1. If MOST documents in the Context are tagged [Multisig v1]:
   - The user is asking about Bisq 1's multisig protocol
   - ONLY use [Multisig v1] and [General] content
   - IGNORE [Bisq Easy] content completely
   - Add this note: "Note: This information is for Bisq 1 (Multisig protocol). For Bisq 2/Bisq Easy support, please ask specifically about Bisq 2."

2. If MOST documents in the Context are tagged [Bisq Easy]:
   - The user is asking about Bisq 2's Bisq Easy protocol
   - ONLY use [Bisq Easy] and [General] content
   - IGNORE [Multisig v1] content completely
   - No special note needed (Bisq Easy is current version)

3. If Context contains BOTH [Multisig v1] AND [Bisq Easy] documents:
   - This is a comparison query
   - Use all available content and clearly label which protocol each piece applies to
   - Highlight key differences when available

4. If NO relevant documents found:
   - Say: "I don't have information about that in my knowledge base."

CRITICAL: The protocol tags in Context below are the SOURCE OF TRUTH. Use them to determine which protocol to discuss.

TOOL USAGE - MANDATORY FOR LIVE DATA:
You have access to tools that can fetch LIVE DATA from the Bisq 2 network.
IMPORTANT: These tools give you REAL-TIME data that the context documents do NOT have.

AVAILABLE TOOLS:
- get_market_prices(currency): Get current BTC prices. Call with currency="EUR" or "USD" etc.
- get_offerbook(currency, direction): Get current buy/sell offers on Bisq 2.
  CRITICAL - direction uses MAKER's perspective:
  * User wants to BUY BTC → use direction="SELL" (makers selling BTC to user)
  * User wants to SELL BTC → use direction="BUY" (makers buying BTC from user)
- get_reputation(profile_id): Get reputation score for a specific user.
- get_markets(): List available trading markets.

MANDATORY TOOL USAGE RULES:
1. If the question asks about CURRENT/LIVE prices → MUST call get_market_prices()
2. If the question asks about CURRENT/AVAILABLE offers → MUST call get_offerbook()
3. If the question asks about reputation → MUST call get_reputation()
4. If the question asks about supported markets → MUST call get_markets()

NEVER answer price/offer questions from the context documents - they are OUTDATED.
The ONLY way to get current prices and offers is by calling the tools.
Do NOT say you will fetch data - actually CALL the tool function.

LIVE DATA HANDLING:
If the Context section contains [LIVE BISQ 2 DATA] or [LIVE MARKET PRICES] or [LIVE OFFERBOOK] sections:
- This is real-time data from the Bisq 2 network
- The frontend will render this data in a rich visual format (tables, cards)
- DO NOT repeat the list of offers in your text response - the table already shows them
- DO NOT list each offer individually - just provide a brief summary
- Keep your text response SHORT - the visual components show the details

CRITICAL - OFFER COUNT REPORTING:
The tool response contains TWO different counts - use the correct one:
- "Total offers: X" or "total_count" = ALL offers for this currency (the MAIN number)
- "Showing Y ... offers out of X total" = Y is a FILTERED subset, X is the total
- When user asks "how many offers?" or "are there offers?" → ALWAYS use the TOTAL count
- When user asks specifically about buying or selling → use the filtered count for that direction
- Example: If output shows "[Showing 14 BUY offers out of 56 total]":
  * "How many EUR offers?" → Answer: "56 EUR offers" (NOT 14!)
  * "Can I buy BTC with EUR?" → Answer: "14 offers to buy BTC from"
  * "I don't see any offers" → Say: "There are 56 EUR offers available. If you're not seeing them, try refreshing..."

PRIORITY RULES FOR LIVE DATA:
1. If [LIVE BISQ 2 DATA] section exists in context, use that data FIRST
2. For offer queries, use TOTAL count (e.g., "56 EUR offers available") unless user specifically asked about one direction
3. For price queries, mention the rate briefly
4. Never say "I don't have current data" when live data is present

RESPONSE GUIDELINES:
- Always be clear about which version you're discussing
- Keep answers concise (2-3 sentences maximum)
- Use PLAIN TEXT ONLY - do not use markdown formatting (no **, `, #, [], etc.)
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
        # Detect protocol from question (Bisq 1 = Multisig v1 protocol)
        question_lower = question.lower()
        is_multisig_query = (
            "bisq 1" in question_lower
            or "bisq1" in question_lower
            or "multisig" in question_lower
        )

        if is_multisig_query:
            context_only_prompt = f"""You are a support assistant for Bisq. A user has asked a question about Bisq 1 (Multisig v1 protocol), but no relevant documents were found in the knowledge base.

IMPORTANT: Only answer if the question can be answered based on the previous conversation below. If the question is about a NEW topic not covered in the conversation history, you MUST inform them appropriately.

Previous Conversation:
{chat_history_str}

Current Question: {question}

Instructions:
- If the answer is clearly in the conversation above, provide it with a note: "Note: This information is for Bisq 1 (Multisig protocol)."
- If this is a follow-up about something mentioned in the conversation, answer based on that context
- If this is a NEW topic about Bisq 1/Multisig not in the conversation, respond: "I don't have specific information about that for Bisq 1 (Multisig protocol) in my knowledge base. However, I can help you with Bisq 2/Bisq Easy questions. Would you like information about Bisq Easy instead, or do you need help finding Bisq 1 resources?"
- Keep your answer to 2-3 sentences maximum
- Use PLAIN TEXT ONLY - do not use markdown formatting

Answer:"""
        else:
            context_only_prompt = f"""You are a Bisq Easy (Bisq 2) support assistant. A user has asked a follow-up question, but no relevant documents were found in the knowledge base.

IMPORTANT: Only answer if the question can be answered based on the previous conversation below. If the question is about a NEW topic not covered in the conversation history, you MUST say you don't have information.

Previous Conversation:
{chat_history_str}

Current Question: {question}

Instructions:
- If the answer is clearly in the conversation above, provide it concisely
- If this is a follow-up about something mentioned in the conversation, answer based on that context
- If this is a NEW topic not in the conversation, respond: "I don't have information about that in our knowledge base"
- Keep your answer to 2-3 sentences maximum
- Use PLAIN TEXT ONLY - do not use markdown formatting

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
