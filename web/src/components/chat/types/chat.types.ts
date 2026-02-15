/**
 * Chat interface type definitions
 */

/**
 * Source document metadata with wiki URL support
 */
export interface Source {
    title: string
    type: "wiki" | "faq"
    content: string
    protocol?: "bisq_easy" | "multisig_v1" | "all"
    /** Wiki URL (e.g., "https://bisq.wiki/Article#Section") */
    url?: string
    /** Section within article */
    section?: string
    /** 0.0-1.0 relevance score from vector search */
    similarity_score?: number
}

export interface Message {
    id: string
    content: string
    role: "user" | "assistant"
    timestamp: Date
    rating?: number
    sources?: Source[]
    metadata?: {
        response_time: number
        token_count: number
    }
    confidence?: number
    detected_version?: string
    version_confidence?: number
    isThankYouMessage?: boolean
    /** MCP tools used to fetch live Bisq 2 data (if any) */
    mcp_tools_used?: McpToolUsage[]
    /** Routing action from the RAG system (e.g., "needs_clarification", "auto_send", "queue_medium") */
    routing_action?: string
    /** Whether this message has been escalated for human review */
    requires_human?: boolean
    /** Message ID used for polling escalation status */
    escalation_message_id?: string
    /** Staff response received for an escalated question */
    staff_response?: {
        answer: string
        responded_at: string
        rating?: number
    }
    /** Escalation resolution set client-side after polling completes */
    escalation_resolution?: "responded" | "closed"
    escalation_resolved_at?: string
}

/**
 * Details about MCP tool usage for enhanced API typing
 */
export interface McpToolUsage {
    /** Tool name (e.g., 'get_market_prices', 'get_offerbook') */
    tool: string
    /** ISO timestamp when the tool was called */
    timestamp: string
    /** Raw result from the MCP tool (contains structured data like prices/offers) */
    result?: string
}

export interface FeedbackDialogState {
    isOpen: boolean
    messageId: string | null
    questionText: string
    answerText: string
}

export interface FeedbackIssue {
    id: string
    label: string
}

export interface FeedbackResponse {
    success: boolean
    message: string
    needs_feedback_followup?: boolean
    escalation_created?: boolean
    escalation_message_id?: string
}

export interface ExplanationResponse {
    success: boolean
    message: string
    detected_issues?: string[]
}
