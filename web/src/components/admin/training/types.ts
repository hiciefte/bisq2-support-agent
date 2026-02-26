import type { Source } from "@/components/chat/types/chat.types";

export type RoutingCategory = "FULL_REVIEW" | "SPOT_CHECK" | "AUTO_APPROVE";

export type ProtocolType = "bisq_easy" | "multisig_v1" | "musig" | "all";

export interface CalibrationStatus {
    samples_collected: number;
    samples_required: number;
    is_complete: boolean;
    auto_approve_threshold: number;
    spot_check_threshold: number;
}

export interface QueueCounts {
    FULL_REVIEW: number;
    SPOT_CHECK: number;
    AUTO_APPROVE: number;
}

export interface UnifiedCandidate {
    id: number;
    source: string;
    source_event_id: string;
    source_timestamp: string;
    question_text: string;
    staff_answer: string;
    generated_answer: string | null;
    staff_sender: string | null;
    embedding_similarity: number | null;
    factual_alignment: number | null;
    contradiction_score: number | null;
    completeness: number | null;
    hallucination_risk: number | null;
    final_score: number | null;
    generation_confidence: number | null;
    llm_reasoning: string | null;
    routing: string;
    review_status: string;
    reviewed_by: string | null;
    reviewed_at: string | null;
    rejection_reason: string | null;
    faq_id: string | null;
    is_calibration_sample: boolean;
    created_at: string;
    updated_at: string | null;
    conversation_context: string | null;
    has_correction: boolean | null;
    is_multi_turn: boolean | null;
    message_count: number | null;
    needs_distillation: boolean | null;
    protocol: ProtocolType | null;
    edited_staff_answer: string | null;
    edited_question_text: string | null;
    category: string | null;
    generated_answer_sources: Source[] | null;
    original_user_question: string | null;
    original_staff_answer: string | null;
}

export type BatchCandidate = Pick<
    UnifiedCandidate,
    | "id"
    | "question_text"
    | "generated_answer"
    | "final_score"
    | "category"
    | "protocol"
    | "source"
>;

export interface SimilarFAQ {
    id: number;
    question: string;
    answer: string;
    similarity: number;
    category?: string | null;
}
