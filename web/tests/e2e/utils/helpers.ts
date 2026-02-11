/**
 * Common test helper functions for E2E tests
 *
 * Provides reusable utilities to reduce code duplication across test files.
 */

import { APIRequestContext, expect, Page } from "@playwright/test";
import { API_BASE_URL } from "./env";

const SUBMIT_BUTTON_SELECTOR = "button[type=\"submit\"]";
const ENABLED_INPUT_SELECTOR = "input:not([disabled]), textarea:not([disabled])";
const PROSE_CHAT_SELECTOR = "div.prose-chat";
const ASSISTANT_AVATAR_SELECTOR = "img[alt=\"Bisq AI\"]";
const FEEDBACK_BUTTON_SELECTOR =
    "button[aria-label=\"Rate as helpful\"], button[aria-label=\"Rate as not helpful\"]";

interface LastBotResponseOptions {
    previousProseCount?: number;
    timeout?: number;
    minLength?: number;
    throwOnTransientApiError?: boolean;
}

/**
 * Dismiss the privacy notice if it appears
 *
 * @param page - Playwright page instance
 */
export async function dismissPrivacyNotice(page: Page): Promise<void> {
    const privacyButton = page.locator("button:has-text(\"I Understand\")");
    if (await privacyButton.isVisible()) {
        await privacyButton.click();
    }
}

/**
 * Submit a chat message and return current prose-chat count baseline.
 *
 * @param page - Playwright page instance
 * @param message - Message text to submit
 * @param timeout - Timeout to wait for enabled submit state (default: 5000)
 * @returns prose-chat count captured before submitting
 */
export async function submitChatMessage(
    page: Page,
    message: string,
    timeout: number = 5000,
): Promise<number> {
    const trimmedMessage = message.trim();
    if (!trimmedMessage) {
        throw new Error("submitChatMessage requires a non-empty message.");
    }

    const previousProseCount = await page.locator(PROSE_CHAT_SELECTOR).count();
    const inputField = page.getByRole("textbox");
    await inputField.click();
    await inputField.pressSequentially(trimmedMessage, { delay: 50 });
    await page.waitForSelector(`${SUBMIT_BUTTON_SELECTOR}:not([disabled])`, { timeout });
    await page.click(SUBMIT_BUTTON_SELECTOR);

    return previousProseCount;
}

/**
 * Wait for the latest assistant response and return its visible text.
 *
 * Uses prose-chat count growth to avoid returning stale text from a prior response.
 *
 * @param page - Playwright page instance
 * @param options - Waiting and validation options
 */
export async function getLastBotResponse(
    page: Page,
    options: LastBotResponseOptions = {},
): Promise<string> {
    const {
        previousProseCount,
        timeout = 50000,
        minLength = 30,
        throwOnTransientApiError = true,
    } = options;

    await page.waitForSelector(ASSISTANT_AVATAR_SELECTOR, { timeout: 10000 });

    const baselineCount =
        typeof previousProseCount === "number"
            ? previousProseCount
            : await page.locator(PROSE_CHAT_SELECTOR).count();

    await page.waitForFunction(
        ([selector, baseline]) =>
            document.querySelectorAll(selector).length > baseline,
        [PROSE_CHAT_SELECTOR, baselineCount] as [string, number],
        { timeout },
    );

    const pollIntervalMs = 500;
    const maxAttempts = Math.max(1, Math.ceil(timeout / pollIntervalMs));

    let responseText = "";
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
        const proseElements = page.locator(PROSE_CHAT_SELECTOR);
        const count = await proseElements.count();
        if (count > baselineCount) {
            responseText = (await proseElements.nth(count - 1).innerText()).trim();
        }

        if (responseText.length >= minLength) {
            break;
        }
        await page.waitForTimeout(pollIntervalMs);
    }

    if (responseText.length < minLength) {
        throw new Error(
            `Bot response not received within ${timeout}ms. Got: "${responseText}"`,
        );
    }

    if (throwOnTransientApiError && /error occurred.*failed to fetch/i.test(responseText)) {
        throw new Error(`Transient API error: ${responseText}`);
    }

    return responseText;
}

/**
 * Wait for the assistant message to appear after sending a chat message.
 *
 * @param page - Playwright page instance
 * @param timeout - Maximum time to wait in milliseconds (default: 30000)
 */
export async function waitForAssistantMessage(
    page: Page,
    timeout: number = 30000,
): Promise<void> {
    await page.waitForSelector(ASSISTANT_AVATAR_SELECTOR, { timeout: Math.min(timeout, 10000) });
    await page.waitForSelector(PROSE_CHAT_SELECTOR, { timeout });

    await page.waitForSelector(ENABLED_INPUT_SELECTOR, { timeout });
    await page.waitForSelector(FEEDBACK_BUTTON_SELECTOR, { timeout });
}

/**
 * Wait for the API to be healthy and ready to accept requests.
 *
 * Polls the /health endpoint until it returns 200 status.
 *
 * @param requestContext - Playwright APIRequestContext or Page
 * @param timeout - Maximum time to wait in milliseconds (default: 60000)
 */
export async function waitForApiReady(
    requestContext: APIRequestContext | Page,
    timeout: number = 60000,
): Promise<void> {
    const request = "request" in requestContext ? requestContext.request : requestContext;

    await expect
        .poll(
            async () => {
                try {
                    const response = await request.get(`${API_BASE_URL}/health`);
                    return response.status();
                } catch {
                    return 0;
                }
            },
            { timeout, intervals: [1000, 2000, 3000] },
        )
        .toBe(200);
}

/**
 * Send a chat message and wait for the response rendering to complete.
 *
 * @param page - Playwright page instance
 * @param message - Message text to send
 * @param timeout - Maximum time to wait for response (default: 30000)
 */
export async function sendChatMessage(
    page: Page,
    message: string,
    timeout: number = 30000,
): Promise<void> {
    const previousProseCount = await submitChatMessage(page, message, Math.min(timeout, 5000));
    await getLastBotResponse(page, {
        previousProseCount,
        timeout,
    });
}

/**
 * Check if sources are visible in the last assistant message.
 *
 * @param page - Playwright page instance
 * @returns true if sources are displayed, false otherwise
 */
export async function hasVisibleSources(page: Page): Promise<boolean> {
    try {
        return await page.locator("text=Sources:").isVisible();
    } catch {
        return false;
    }
}

/**
 * Login to admin interface with retry logic for server recovery.
 *
 * @param page - Playwright page instance
 * @param apiKey - Admin API key for authentication
 * @param baseUrl - Base URL of the web application
 * @param maxRetries - Maximum number of retry attempts (default: 5)
 */
export async function loginAsAdmin(
    page: Page,
    apiKey: string,
    baseUrl: string,
    maxRetries: number = 5,
): Promise<void> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            await page.goto(`${baseUrl}/admin`, {
                waitUntil: "domcontentloaded",
                timeout: 20000,
            });

            let spinnerSeen = false;
            try {
                await page.waitForSelector("svg.animate-spin", {
                    state: "attached",
                    timeout: 2000,
                });
                spinnerSeen = true;
            } catch {
                // Spinner may not appear if auth check is fast.
            }
            if (spinnerSeen) {
                await page.waitForSelector("svg.animate-spin", {
                    state: "detached",
                    timeout: 30000,
                });
            }

            const loginInput = page.locator("input#apiKey");
            const dashboard = page
                .locator("text=Admin Dashboard")
                .or(page.locator("h1:has-text(\"Overview\")"));
            await loginInput.or(dashboard).first().waitFor({ timeout: 20000 });

            if (await dashboard.first().isVisible()) {
                console.log("loginAsAdmin: Already authenticated");
                return;
            }

            await page.fill("input#apiKey", apiKey);
            await page.click("button:has-text(\"Login\")");
            await dashboard.first().waitFor({ timeout: 15000 });
            return;
        } catch (error) {
            lastError = error as Error;
            console.log(
                `loginAsAdmin attempt ${attempt}/${maxRetries} failed: ${lastError.message}`,
            );
            if (attempt < maxRetries) {
                const delay = attempt * 3000;
                console.log(`Waiting ${delay}ms before retry...`);
                await new Promise((resolve) => setTimeout(resolve, delay));
            }
        }
    }

    throw lastError ?? new Error("loginAsAdmin failed with no retries configured");
}

/**
 * Navigate to FAQ management page with retry logic (assumes already logged in as admin)
 *
 * @param page - Playwright page instance
 * @param maxRetries - Maximum number of retry attempts (default: 3)
 */
export async function navigateToFaqManagement(
    page: Page,
    maxRetries: number = 3,
): Promise<void> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            const faqLink = page.locator("a[href=\"/admin/manage-faqs\"]").first();
            await faqLink.waitFor({ state: "visible", timeout: 15000 });
            await faqLink.click();
            await page.waitForSelector("text=FAQ", { timeout: 15000 });
            return;
        } catch (error) {
            lastError = error as Error;
            console.log(
                `navigateToFaqManagement attempt ${attempt}/${maxRetries} failed: ${lastError.message}`,
            );
            if (attempt < maxRetries) {
                const delay = attempt * 2000;
                await new Promise((resolve) => setTimeout(resolve, delay));
            }
        }
    }

    throw lastError ?? new Error("navigateToFaqManagement failed with no retries configured");
}

/**
 * Check for permission errors in API logs.
 *
 * @param logs - Docker compose logs output
 * @returns true if permission errors found, false otherwise
 */
export function hasPermissionErrors(logs: string): boolean {
    return (
        logs.includes("Permission denied") ||
        logs.includes("EACCES") ||
        logs.includes("[Errno 13]")
    );
}

/**
 * Navigate to feedback management page with retry logic (assumes already logged in as admin)
 *
 * @param page - Playwright page instance
 * @param maxRetries - Maximum number of retry attempts (default: 3)
 */
export async function navigateToFeedbackManagement(
    page: Page,
    maxRetries: number = 3,
): Promise<void> {
    let lastError: Error | null = null;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            const feedbackLink = page.locator("a[href=\"/admin/manage-feedback\"]").first();
            await feedbackLink.waitFor({ state: "visible", timeout: 15000 });
            await feedbackLink.click();
            await page.waitForURL("**/admin/manage-feedback", { timeout: 15000 });
            await Promise.race([
                page.waitForSelector("[class*=\"border-l-4\"]", { timeout: 15000 }),
                page.waitForSelector("text=No feedback found", { timeout: 15000 }),
                page.locator("h1:has-text(\"Feedback Management\")").waitFor({ timeout: 15000 }),
            ]);
            return;
        } catch (error) {
            lastError = error as Error;
            console.log(
                `navigateToFeedbackManagement attempt ${attempt}/${maxRetries} failed: ${lastError.message}`,
            );
            if (attempt < maxRetries) {
                const delay = attempt * 2000;
                await new Promise((resolve) => setTimeout(resolve, delay));
            }
        }
    }

    throw lastError ?? new Error("navigateToFeedbackManagement failed with no retries configured");
}
