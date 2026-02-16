import { expect, test } from "@playwright/test";
import { dismissPrivacyNotice, WEB_BASE_URL } from "./utils";

test.describe("Escalation rating token flow", () => {
    test("submits staff rating with the signed rate_token from poll response", async ({ page }) => {
        const escalationMessageId = "esc-msg-123";
        const expectedToken = "signed-rate-token-abc";
        let receivedRatingPayload: { rating?: number; rate_token?: string } | null = null;

        await page.addInitScript(() => {
            window.localStorage.clear();
        });

        await page.route("**/chat/stats", async route => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    average_response_time: 12,
                    last_24h_average_response_time: 12,
                }),
            });
        });

        await page.route("**/chat/query", async route => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    message_id: "assistant-msg-1",
                    answer: "I escalated this question to support.",
                    response_time: 1.2,
                    token_count: 42,
                    requires_human: true,
                    escalation_message_id: escalationMessageId,
                }),
            });
        });

        await page.route(`**/escalations/${escalationMessageId}/response`, async route => {
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({
                    status: "resolved",
                    resolution: "responded",
                    staff_answer: "Here is the staff answer.",
                    responded_at: "2026-02-15T10:00:00Z",
                    staff_answer_rating: null,
                    rate_token: expectedToken,
                }),
            });
        });

        await page.route(`**/escalations/${escalationMessageId}/rate`, async route => {
            receivedRatingPayload = route.request().postDataJSON();
            await route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ status: "ok" }),
            });
        });

        await page.goto(WEB_BASE_URL);
        await dismissPrivacyNotice(page);

        const input = page.getByRole("textbox");
        await input.click();
        await input.fill("Need human help");
        await page.click("button[type=\"submit\"]");

        const staffResponse = page.getByLabel("Staff response");
        await expect(staffResponse).toBeVisible({ timeout: 10000 });
        await expect(staffResponse).toContainText("Here is the staff answer.");

        const rateRequest = page.waitForRequest(
            request =>
                request.method() === "POST" &&
                request.url().includes(`/escalations/${escalationMessageId}/rate`)
        );

        await staffResponse.getByRole("button", { name: "Rate as helpful" }).click();
        await rateRequest;

        expect(receivedRatingPayload).toEqual({
            rating: 1,
            rate_token: expectedToken,
        });
        await expect(staffResponse).toContainText("Thank you for your feedback!");
    });
});
