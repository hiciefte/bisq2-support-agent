import { parseChatUiLabels } from "./ui-labels";

describe("parseChatUiLabels", () => {
    test("returns labels for a complete bundle", () => {
        expect(
            parseChatUiLabels({
                helpful_prompt: "Helpful?",
                helpful_thank_you: "Thanks",
                staff_helpful_prompt: "Staff helpful?",
                staff_response_label: "Staff response",
                support_team_notified: "Support notified",
            }),
        ).toEqual({
            helpful_prompt: "Helpful?",
            helpful_thank_you: "Thanks",
            staff_helpful_prompt: "Staff helpful?",
            staff_response_label: "Staff response",
            support_team_notified: "Support notified",
        });
    });

    test("rejects partial bundles", () => {
        expect(
            parseChatUiLabels({
                helpful_prompt: "Helpful?",
                support_team_notified: "Support notified",
            }),
        ).toBeUndefined();
    });
});
