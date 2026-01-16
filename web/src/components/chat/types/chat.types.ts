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
}

export interface ExplanationResponse {
    success: boolean
    message: string
    detected_issues?: string[]
}
