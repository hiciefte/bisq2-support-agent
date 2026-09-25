import type { KnowledgeCandidate } from "@/components/admin/knowledge-updates/types";

export function candidateEvaluationLabel(candidate: Pick<KnowledgeCandidate, "generated_answer" | "final_score">): string {
  if (!candidate.generated_answer?.trim()) return "Not evaluated";
  if (candidate.final_score === null) return "Comparison generated · not scored";
  return `Comparison score: ${Math.round(candidate.final_score * 100)}%`;
}
