/**
 * Chat interface type definitions
 */

export interface Message {
    id: string
    content: string
    role: "user" | "assistant"
    timestamp: Date
    rating?: number
    sources?: Array<{
        title: string
        type: string
        content: string
    }>
    metadata?: {
        response_time: number
        token_count: number
    }
    isThankYouMessage?: boolean
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
