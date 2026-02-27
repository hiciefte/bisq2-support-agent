const FOOTER_DIVIDER_REGEX = /\r?\n-{3,}\r?\n/g;
const CANONICAL_SUPPORT_FOOTER_SPLIT_REGEX = /\r?\n\r?\n---\r?\n/;
const FOOTER_MARKER_REGEX =
  /(^|\n)\s*(?:\*\*|__)?\s*(Answer\s*Quality|Confidence|Source\s*Mix|Sources?)\s*(?:\*\*|__)?(?:\s*:\s*.*)?\s*(?=\n|$)/i;
const FOOTER_ICON_REGEX = /bisq-icon:\/\/(?:faq|wiki)/i;

/**
 * Removes generated answer metadata footer sections from assistant responses.
 * This keeps the review UI focused on the core answer body and avoids duplicating
 * confidence/source summaries already rendered in structured UI blocks.
 */
export function stripGeneratedAnswerFooter(answer?: string): string {
  const text = (answer || "").trim();
  if (!text) return "";

  // Support markdown renderer appends metadata after a canonical `\n\n---\n`.
  // Prefer this deterministic split so channel-formatted footers are stripped
  // even when marker capitalization/formatting varies slightly.
  const canonicalMatch = text.match(CANONICAL_SUPPORT_FOOTER_SPLIT_REGEX);
  if (canonicalMatch && canonicalMatch.index !== undefined) {
    const splitIndex = canonicalMatch.index;
    const suffix = text.slice(splitIndex + canonicalMatch[0].length);
    if (FOOTER_MARKER_REGEX.test(suffix) || FOOTER_ICON_REGEX.test(suffix)) {
      const mainAnswer = text.slice(0, splitIndex).trimEnd();
      if (mainAnswer.length > 0) return mainAnswer;
    }
  }

  for (const match of text.matchAll(FOOTER_DIVIDER_REGEX)) {
    const dividerStart = match.index ?? -1;
    if (dividerStart < 0) continue;

    const divider = match[0] || "";
    const suffix = text.slice(dividerStart + divider.length);
    if (!FOOTER_MARKER_REGEX.test(suffix)) continue;

    const mainAnswer = text.slice(0, dividerStart).trimEnd();
    if (mainAnswer.length > 0) return mainAnswer;
  }

  return text;
}
