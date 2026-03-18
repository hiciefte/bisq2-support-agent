import {
  getInitialQuestionView,
  getInitialStaffAnswer,
  getInitialSuggestedAnswerView,
} from "./language-preference";

describe("escalation language preference helpers", () => {
  test("prefers localized views for non-English escalations with variants", () => {
    const snapshot = {
      user_language: "de",
      question: "How do I buy BTC with EUR?",
      question_original: "Wie kann ich BTC mit Euro kaufen?",
      ai_draft_answer: "Use Bisq Easy to buy BTC with EUR.",
      ai_draft_answer_original: "Nutze Bisq Easy, um BTC mit EUR zu kaufen.",
    };

    expect(getInitialQuestionView(snapshot)).toBe("original");
    expect(getInitialSuggestedAnswerView(snapshot)).toBe("localized");
    expect(getInitialStaffAnswer(snapshot)).toBe(
      "Use Bisq Easy to buy BTC with EUR.",
    );
  });

  test("normalizes underscore language codes before choosing localized views", () => {
    const snapshot = {
      user_language: "pt_BR",
      question: "How do I buy BTC with EUR?",
      question_original: "Como eu compro BTC com EUR?",
      ai_draft_answer: "Use Bisq Easy to buy BTC with EUR.",
      ai_draft_answer_original: "Use o Bisq Easy para comprar BTC com EUR.",
    };

    expect(getInitialQuestionView(snapshot)).toBe("original");
    expect(getInitialSuggestedAnswerView(snapshot)).toBe("localized");
    expect(getInitialStaffAnswer(snapshot)).toBe(
      "Use Bisq Easy to buy BTC with EUR.",
    );
  });

  test("keeps canonical defaults for English escalations", () => {
    const snapshot = {
      user_language: "en",
      question: "How do I buy BTC with EUR?",
      question_original: "How do I buy BTC with EUR?",
      ai_draft_answer: "Use Bisq Easy to buy BTC with EUR.",
      ai_draft_answer_original: "Use Bisq Easy to buy BTC with EUR.",
    };

    expect(getInitialQuestionView(snapshot)).toBe("canonical");
    expect(getInitialSuggestedAnswerView(snapshot)).toBe("canonical");
    expect(getInitialStaffAnswer(snapshot)).toBe(
      "Use Bisq Easy to buy BTC with EUR.",
    );
  });
});
