import type { ChatUiLabels } from "../types/chat.types";

type JsonRecord = Record<string, unknown>;

const UI_LABEL_KEYS: Array<keyof ChatUiLabels> = [
    "helpful_prompt",
    "helpful_thank_you",
    "staff_helpful_prompt",
    "staff_response_label",
    "support_team_notified",
];

const isJsonRecord = (value: unknown): value is JsonRecord =>
    typeof value === "object" && value !== null;

export const parseChatUiLabels = (value: unknown): ChatUiLabels | undefined => {
    if (!isJsonRecord(value)) {
        return undefined;
    }

    const labels = Object.fromEntries(
        UI_LABEL_KEYS.map((key) => [key, value[key]]),
    ) as Record<keyof ChatUiLabels, unknown>;

    const hasCompleteBundle = UI_LABEL_KEYS.every(
        (key) => typeof labels[key] === "string",
    );

    if (!hasCompleteBundle) {
        return undefined;
    }

    return labels as ChatUiLabels;
};
