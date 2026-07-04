import {
  changedMarkdownSections,
  deriveReviewFeedbackPanelState,
  feedbackTagsForApproval,
  inferFeedbackTags,
  PREAMBLE_SECTION_KEY,
  supportKnowledgeSections,
} from "./review-feedback";

describe("knowledge update review feedback", () => {
  it("describes untouched generated drafts as proposed updates, not reviewer learning", () => {
    const state = deriveReviewFeedbackPanelState({
      proposalChangedSections: ["Canonical Support Answer", "Evidence / Sources"],
      reviewerChangedSections: [],
      feedbackTags: [],
      futureGeneratorNote: "",
      answerRating: null,
    });

    expect(state.mode).toBe("proposal");
    expect(state.title).toBe("Proposed update");
    expect(state.badge).toBe("Review first");
    expect(state.summary).toBe("Draft touches 2 support sections");
    expect(state.showFeedbackTags).toBe(false);
  });

  it("shows a learning signal only after reviewer edits or explicit feedback", () => {
    const state = deriveReviewFeedbackPanelState({
      proposalChangedSections: ["Canonical Support Answer", "Evidence / Sources"],
      reviewerChangedSections: ["Canonical Support Answer", "Evidence / Sources"],
      feedbackTags: [],
      futureGeneratorNote: "",
      answerRating: null,
    });

    expect(state.mode).toBe("learning");
    expect(state.title).toBe("Learning signal");
    expect(state.badge).toBe("After your review");
    expect(state.summary).toBe("You changed 2 sections");
    expect(state.showFeedbackTags).toBe(true);
  });

  it("infers good generation when no tag override is provided", () => {
    expect(feedbackTagsForApproval(null, [], null)).toEqual(["good_generation"]);
  });

  it("preserves an explicit empty feedback tag override", () => {
    expect(feedbackTagsForApproval([], ["Canonical Support Answer"], null)).toEqual([]);
  });

  it("records correction tags from reviewer-changed sections", () => {
    expect(
      inferFeedbackTags(["Canonical Support Answer", "Evidence / Sources"], null),
    ).toEqual(["factual_correction", "source_support"]);
  });

  describe("preamble edits before the first section header", () => {
    const beforeMarkdown = "# Old Title\n\n## Canonical Support Answer\nSame body";
    const afterMarkdown = "# New Title\n\n## Canonical Support Answer\nSame body";

    it("detects a preamble-only edit as a changed section", () => {
      expect(changedMarkdownSections(beforeMarkdown, afterMarkdown)).toEqual([
        PREAMBLE_SECTION_KEY,
      ]);
    });

    it("reports no changed sections when the preamble is untouched", () => {
      expect(changedMarkdownSections(beforeMarkdown, beforeMarkdown)).toEqual([]);
    });

    it("keeps frontmatter-only differences out of the section diff", () => {
      const withFrontmatter =
        "---\ntitle: a\n---\n# Title\n\n## Canonical Support Answer\nBody";
      const withOtherFrontmatter =
        "---\ntitle: b\n---\n# Title\n\n## Canonical Support Answer\nBody";
      expect(
        changedMarkdownSections(withFrontmatter, withOtherFrontmatter),
      ).toEqual([]);
    });

    it("treats a preamble-only reviewer edit as a learning signal, not good generation", () => {
      const reviewerChangedSections = supportKnowledgeSections(
        changedMarkdownSections(beforeMarkdown, afterMarkdown),
      );

      expect(inferFeedbackTags(reviewerChangedSections, null)).not.toContain(
        "good_generation",
      );

      const state = deriveReviewFeedbackPanelState({
        proposalChangedSections: [],
        reviewerChangedSections,
        feedbackTags: [],
        futureGeneratorNote: "",
        answerRating: null,
      });

      expect(state.mode).toBe("learning");
      expect(state.summary).toBe("You changed 1 section");
      expect(state.visibleSections).toEqual(["Document preamble"]);
    });
  });
});
