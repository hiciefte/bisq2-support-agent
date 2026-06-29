import {
  deriveReviewFeedbackPanelState,
  feedbackTagsForApproval,
  inferFeedbackTags,
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
});
