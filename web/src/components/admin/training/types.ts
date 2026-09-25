/** Compatibility exports for callers using the former training module. */
export type {
    BatchCandidate,
    CalibrationStatus,
    KnowledgeCandidate,
    ProtocolType,
    QueueCounts,
    RoutingCategory,
    SimilarFAQ,
} from "../knowledge-updates/types";

/** @deprecated Use KnowledgeCandidate from admin/knowledge-updates/types. */
export type UnifiedCandidate = import("../knowledge-updates/types").KnowledgeCandidate;
