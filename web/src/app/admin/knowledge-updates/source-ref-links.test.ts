import { linkifySourceRefsInMarkdown } from "./source-ref-links";

describe("knowledge update source ref links", () => {
  it("turns backticked FAQ and wiki source refs into clickable markdown links", () => {
    const markdown = [
      "## Evidence / Sources",
      "",
      "- `faq:1071` confirms the trade wizard behavior.",
      "- `wiki:Bisq Easy` explains the protocol.",
    ].join("\n");

    const linked = linkifySourceRefsInMarkdown(markdown, {
      "faq:1071": "/faq/why-is-the-trade-wizard-not-working-for-me-34be1021",
      "wiki:Bisq Easy": "https://bisq.wiki/Bisq_Easy",
    });

    expect(linked).toContain(
      "[faq:1071](/faq/why-is-the-trade-wizard-not-working-for-me-34be1021)",
    );
    expect(linked).toContain("[wiki:Bisq Easy](https://bisq.wiki/Bisq_Easy)");
    expect(linked).not.toContain("`faq:1071`");
  });

  it("links slug FAQ refs and compact wiki refs without a resolver map", () => {
    const markdown = "- faq:known-slug-abcdef12\n- wiki:Reputation";

    const linked = linkifySourceRefsInMarkdown(markdown, {});

    expect(linked).toContain(
      "[faq:known-slug-abcdef12](/faq/known-slug-abcdef12)",
    );
    expect(linked).toContain("[wiki:Reputation](https://bisq.wiki/Reputation)");
  });

  it("leaves unresolved numeric FAQ refs unchanged", () => {
    expect(linkifySourceRefsInMarkdown("See `faq:1071`.", {})).toBe(
      "See `faq:1071`.",
    );
  });

  it("ignores malformed source URLs instead of breaking preview rendering", () => {
    expect(
      linkifySourceRefsInMarkdown("See `faq:broken`.", {}, [
        {
          type: "faq",
          title: "Broken source",
          content: "",
          url: "https://[bad-url",
        },
      ]),
    ).toBe("See [faq:broken](/faq/broken).");
  });
});
