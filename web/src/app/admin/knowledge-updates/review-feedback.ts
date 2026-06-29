export type AnswerRating = "good" | "needs_improvement";

export type ReviewFeedbackPanelMode = "proposal" | "learning";

export interface ReviewFeedbackPanelState {
  mode: ReviewFeedbackPanelMode;
  title: string;
  badge: string;
  summary: string;
  description: string;
  visibleSections: string[];
  showFeedbackTags: boolean;
}

const ADMIN_SECTION_NAMES = new Set(["Review Notes", "Last Change Summary"]);

function splitMarkdownSections(markdown: string): Record<string, string> {
  const sections: Record<string, string[]> = {};
  let currentSection: string | null = null;
  const body = stripFrontmatter(markdown).replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  for (const line of body.split("\n")) {
    if (line.startsWith("## ")) {
      currentSection = line.slice(3).trim();
      sections[currentSection] = sections[currentSection] ?? [];
      continue;
    }
    if (currentSection) {
      sections[currentSection].push(line);
    }
  }
  return Object.fromEntries(
    Object.entries(sections).map(([section, lines]) => [
      section,
      lines.join("\n").trim(),
    ]),
  );
}

function stripFrontmatter(markdown: string): string {
  const value = markdown.trim();
  if (!value.startsWith("---")) return value;
  const end = value.indexOf("\n---", 3);
  if (end === -1) return value;
  return value.slice(end + 4).trim();
}

export function changedMarkdownSections(
  beforeMarkdown: string | null | undefined,
  afterMarkdown: string,
): string[] {
  const before = splitMarkdownSections(beforeMarkdown ?? "");
  const after = splitMarkdownSections(afterMarkdown);
  const names = new Set([...Object.keys(before), ...Object.keys(after)]);
  return Array.from(names).filter((name) => (before[name] ?? "") !== (after[name] ?? ""));
}

export function supportKnowledgeSections(sections: string[]): string[] {
  return sections.filter((section) => !ADMIN_SECTION_NAMES.has(section));
}

export function inferFeedbackTags(
  changedSections: string[],
  answerRating: AnswerRating | null,
): string[] {
  const tags = new Set<string>();
  if (changedSections.length === 0 && answerRating !== "needs_improvement") {
    tags.add("good_generation");
  }
  if (answerRating === "needs_improvement") {
    tags.add("factual_correction");
  }
  if (changedSections.includes("Canonical Support Answer")) {
    tags.add("factual_correction");
  }
  if (changedSections.includes("Applies When")) {
    tags.add("scope_narrowing");
  }
  if (changedSections.includes("Do Not Say")) {
    tags.add("missing_caveat");
  }
  if (changedSections.includes("Evidence / Sources")) {
    tags.add("source_support");
  }
  return Array.from(tags);
}

export function feedbackTagsForApproval(
  feedbackTags: string[],
  reviewerChangedSections: string[],
  answerRating: AnswerRating | null,
): string[] {
  return feedbackTags.length > 0
    ? feedbackTags
    : inferFeedbackTags(reviewerChangedSections, answerRating);
}

function sectionCountSummary(prefix: string, sections: string[]): string {
  if (sections.length === 0) return `${prefix} no support sections`;
  return `${prefix} ${sections.length} support section${sections.length === 1 ? "" : "s"}`;
}

export function deriveReviewFeedbackPanelState({
  proposalChangedSections,
  reviewerChangedSections,
  feedbackTags,
  futureGeneratorNote,
  answerRating,
}: {
  proposalChangedSections: string[];
  reviewerChangedSections: string[];
  feedbackTags: string[];
  futureGeneratorNote: string | null | undefined;
  answerRating: AnswerRating | null;
}): ReviewFeedbackPanelState {
  const hasReviewerSignal =
    reviewerChangedSections.length > 0 ||
    feedbackTags.length > 0 ||
    Boolean(futureGeneratorNote?.trim()) ||
    answerRating !== null;

  if (!hasReviewerSignal) {
    return {
      mode: "proposal",
      title: "Proposed update",
      badge: "Review first",
      summary: sectionCountSummary("Draft touches", proposalChangedSections),
      description:
        "This describes what the generated draft would change. It is not saved as learning feedback until you review the page.",
      visibleSections: proposalChangedSections,
      showFeedbackTags: false,
    };
  }

  return {
    mode: "learning",
    title: "Learning signal",
    badge: "After your review",
    summary:
      reviewerChangedSections.length > 0
        ? `You changed ${reviewerChangedSections.length} section${reviewerChangedSections.length === 1 ? "" : "s"}`
        : "No material document edits detected",
    description:
      "We save this signal with your final decision for future LLM Wiki drafts; it is not added to customer-facing RAG.",
    visibleSections: reviewerChangedSections,
    showFeedbackTags: true,
  };
}
