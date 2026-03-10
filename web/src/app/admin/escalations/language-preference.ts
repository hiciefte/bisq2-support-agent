export type EscalationLanguageSnapshot = {
  user_language?: string | null;
  question?: string | null;
  question_original?: string | null;
  ai_draft_answer?: string | null;
  ai_draft_answer_original?: string | null;
};

export type QuestionView = "canonical" | "original";
export type SuggestedAnswerView = "canonical" | "localized";

function normalize(value: string | null | undefined): string {
  return (value || "").trim();
}

function normalizeLanguageCode(value: string | null | undefined): string {
  const normalized = normalize(value).toLowerCase();
  if (!normalized) return "";
  return normalized.split("-", 1)[0] || normalized;
}

export function getCanonicalQuestion(snapshot: EscalationLanguageSnapshot): string {
  return normalize(snapshot.question) || normalize(snapshot.question_original);
}

export function getLocalizedQuestion(snapshot: EscalationLanguageSnapshot): string {
  return normalize(snapshot.question_original) || normalize(snapshot.question);
}

export function getCanonicalDraftAnswer(snapshot: EscalationLanguageSnapshot): string {
  return normalize(snapshot.ai_draft_answer) || normalize(snapshot.ai_draft_answer_original);
}

export function getLocalizedDraftAnswer(snapshot: EscalationLanguageSnapshot): string {
  return normalize(snapshot.ai_draft_answer_original) || normalize(snapshot.ai_draft_answer);
}

export function prefersLocalizedEscalationContent(
  snapshot: EscalationLanguageSnapshot,
): boolean {
  const language = normalizeLanguageCode(snapshot.user_language);
  return Boolean(language) && language !== "en";
}

export function getInitialQuestionView(
  snapshot: EscalationLanguageSnapshot,
): QuestionView {
  const canonical = getCanonicalQuestion(snapshot);
  const localized = getLocalizedQuestion(snapshot);
  if (prefersLocalizedEscalationContent(snapshot) && localized && localized !== canonical) {
    return "original";
  }
  return "canonical";
}

export function getInitialSuggestedAnswerView(
  snapshot: EscalationLanguageSnapshot,
): SuggestedAnswerView {
  const canonical = getCanonicalDraftAnswer(snapshot);
  const localized = getLocalizedDraftAnswer(snapshot);
  if (prefersLocalizedEscalationContent(snapshot) && localized && localized !== canonical) {
    return "localized";
  }
  return "canonical";
}

export function getInitialStaffAnswer(
  snapshot: EscalationLanguageSnapshot,
): string {
  const suggestedView = getInitialSuggestedAnswerView(snapshot);
  if (suggestedView === "localized") {
    const localized = getLocalizedDraftAnswer(snapshot);
    if (localized) {
      return localized;
    }
  }
  return getCanonicalDraftAnswer(snapshot);
}
