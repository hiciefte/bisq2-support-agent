import { stripGeneratedAnswerFooter } from "./answer-format";

describe("stripGeneratedAnswerFooter", () => {
  it("strips markdown answer-quality footer with bold headings", () => {
    const input = [
      "Core answer paragraph.",
      "",
      "---",
      "",
      "**Answer quality**",
      "- Confidence: Needs verification (63%)",
      "- Source mix: 3 FAQs, 2 Wiki pages",
      "",
      "**Sources**",
      "- [Wiki] Bisq 2",
    ].join("\n");

    expect(stripGeneratedAnswerFooter(input)).toBe("Core answer paragraph.");
  });

  it("strips legacy footer markers with colon syntax", () => {
    const input = [
      "Another answer.",
      "",
      "---",
      "Answer quality: Needs verification",
      "Sources: foo",
    ].join("\n");

    expect(stripGeneratedAnswerFooter(input)).toBe("Another answer.");
  });

  it("keeps content when divider exists but no footer marker follows", () => {
    const input = [
      "Answer section",
      "",
      "---",
      "Follow-up explanation that is part of the answer.",
    ].join("\n");

    expect(stripGeneratedAnswerFooter(input)).toBe(input);
  });

  it("keeps content without divider", () => {
    const input = "Plain answer without metadata footer.";
    expect(stripGeneratedAnswerFooter(input)).toBe(input);
  });
});
