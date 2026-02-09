import { expect, Page, test } from "@playwright/test";
import {
    dismissPrivacyNotice,
    getLastBotResponse,
    submitChatMessage,
} from "./utils/helpers";

/**
 * Bisq Version Handling Tests
 *
 * These E2E tests verify that the chatbot correctly handles:
 * - Explicit Bisq 1 questions (answered with disclaimer when info available)
 * - Ambiguous questions (default to Bisq 2)
 * - Version switching in conversation
 * - Proper version disclaimers in responses
 */

const TEST_BASE_URL = process.env.BASE_URL || "http://localhost:3000";

const askQuestionAndGetResponse = async (page: Page, question: string): Promise<string> => {
    const previousProseCount = await submitChatMessage(page, question, 5000);
    return getLastBotResponse(page, { previousProseCount, timeout: 50000 });
};

test.describe("Bisq Version Handling", () => {
    // These tests make real LLM API calls and may fail due to transient API
    // errors ("failed to fetch") or slow responses. Retry once on failure.
    test.describe.configure({ retries: 1 });

    // LLM responses are non-deterministic and the API may be slow under load.
    // 90s accommodates submit + response wait + assertion overhead.
    test.setTimeout(90000);

    test.beforeEach(async ({ page }) => {
        await page.goto(TEST_BASE_URL);
        await dismissPrivacyNotice(page);
        await page.getByRole("textbox").waitFor({ state: "visible" });
    });

    test("should answer Bisq 1 questions with disclaimer when information is available", async ({
        page,
    }) => {
        const responseText = await askQuestionAndGetResponse(
            page,
            "How do I resolve a trade dispute in Bisq 1?",
        );
        const responseLower = responseText.toLowerCase();

        expect(responseLower).not.toContain(
            "i can only provide information about bisq 2",
        );
        expect(responseLower).not.toContain("sorry, but i can only");

        const hasValidResponse =
            responseLower.includes("bisq 1") ||
            responseLower.includes("bisq1") ||
            responseLower.includes(
                "don't have specific information about that for bisq 1",
            );

        expect(hasValidResponse).toBeTruthy();
    });

    test("should handle ambiguous questions appropriately", async ({ page }) => {
        const responseText = await askQuestionAndGetResponse(page, "How do I trade?");
        const responseLower = responseText.toLowerCase();

        const mentionsBisq2 = /bisq 2|bisq2|bisq easy/.test(responseLower);
        const asksClarification =
            /which|are you using|do you mean|bisq 1.*or.*bisq 2|bisq 2.*or.*bisq 1/.test(
                responseLower,
            );

        expect(mentionsBisq2).toBeTruthy();

        if (/bisq 1|bisq1/.test(responseLower)) {
            expect(asksClarification).toBeTruthy();
        }
    });

    test("should handle explicit Bisq 2 questions correctly", async ({ page }) => {
        const responseText = await askQuestionAndGetResponse(page, "What is Bisq 2?");
        const responseLower = responseText.toLowerCase();

        expect(responseLower).toMatch(/bisq 2|bisq2/);
        expect(responseLower).not.toContain("this information is for bisq 1");
    });

    test("should handle version switching in conversation", async ({ page }) => {
        await askQuestionAndGetResponse(page, "How do I start trading?");

        const secondResponse = await askQuestionAndGetResponse(page, "How about in Bisq 1?");
        const responseLower = secondResponse.toLowerCase();

        const handlesBisq1Context =
            responseLower.includes("bisq 1") ||
            responseLower.includes("bisq1") ||
            responseLower.includes(
                "don't have specific information about that for bisq 1",
            );

        expect(handlesBisq1Context).toBeTruthy();
    });

    test("should handle comparison questions between versions", async ({ page }) => {
        const responseText = await askQuestionAndGetResponse(
            page,
            "What is the difference between Bisq 1 and Bisq 2?",
        );
        const responseLower = responseText.toLowerCase();

        expect(responseLower).toMatch(/bisq 1|bisq1/);
        expect(responseLower).toMatch(/bisq 2|bisq2/);

        const hasComparison =
            responseLower.includes("difference") ||
            responseLower.includes("compared") ||
            responseLower.includes("whereas") ||
            responseLower.includes("contrast") ||
            responseLower.includes("unlike") ||
            responseLower.includes("on the other hand") ||
            responseLower.includes("rather") ||
            responseLower.includes("upgrade") ||
            responseLower.includes("successor") ||
            responseLower.includes("evolution");

        expect(hasComparison).toBeTruthy();
    });

    test("should handle Bisq 1 spelling variations", async ({ page }) => {
        const responseText = await askQuestionAndGetResponse(page, "How do I use Bisq1?");
        const responseLower = responseText.toLowerCase();

        const handlesBisq1 =
            responseLower.includes("bisq 1") ||
            responseLower.includes("bisq1") ||
            responseLower.includes("bisq") ||
            responseLower.includes("trading") ||
            responseLower.includes("bitcoin") ||
            responseLower.includes("exchange") ||
            responseLower.includes("don't have specific information") ||
            responseLower.includes("help") ||
            responseLower.includes("peer-to-peer");

        const refusesOutright =
            responseLower.includes("i cannot") ||
            responseLower.includes("i'm unable") ||
            responseLower.includes("not able to");

        expect(handlesBisq1).toBeTruthy();
        expect(refusesOutright).toBeFalsy();
    });

    test("should not refuse Bisq 1 questions outright", async ({ page }) => {
        const responseText = await askQuestionAndGetResponse(
            page,
            "Tell me about Bisq 1 mediation",
        );
        const responseLower = responseText.toLowerCase();

        expect(responseLower).not.toContain(
            "i'm sorry, but i can only provide information about bisq 2",
        );
        expect(responseLower).not.toContain("i can only help with bisq 2");

        const hasHelpfulResponse =
            responseLower.includes("bisq 1") ||
            responseLower.includes("bisq1") ||
            responseLower.includes("don't have specific information") ||
            responseLower.includes("would you like information about bisq 2");

        expect(hasHelpfulResponse).toBeTruthy();
    });
});
