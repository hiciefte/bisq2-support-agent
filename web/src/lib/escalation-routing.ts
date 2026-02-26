export function normalizeRoutingReasonSourceCount(
    reason: string | null | undefined,
    sourceCount: number | null | undefined,
): string {
    const text = (reason || "").trim();
    if (!text) return "";
    if (typeof sourceCount !== "number" || sourceCount < 0) return text;

    const normalizedCountText =
        sourceCount === 1 ? "1 source found" : `${sourceCount} sources found`;

    return text.replace(/\b\d+\s+sources?\s+found\b/i, normalizedCountText);
}
