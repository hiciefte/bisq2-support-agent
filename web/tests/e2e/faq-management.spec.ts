import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { selectCategory, API_BASE_URL, ADMIN_API_KEY, WEB_BASE_URL, loginAsAdmin, waitForApiReady } from "./utils";

// Global type declaration for console error tracking
declare global {
    interface Window {
        consoleErrors: string[];
    }
}

/**
 * FAQ Management Tests
 *
 * These tests verify that FAQ CRUD operations work correctly,
 * particularly focusing on the permission issues that cause
 * FAQ deletion to fail after container restarts.
 */

test.describe("FAQ Management", () => {
    // Increase timeout for tests that run after container restart tests
    test.setTimeout(90000);

    // FAQ card selector constant - used throughout tests
    // Note: Use base classes only (no border-border) as it's conditionally applied
    const FAQ_CARD_SELECTOR = ".bg-card.border.rounded-lg";
    const SELECTED_FAQ_CARD_SELECTOR = ".bg-card.rounded-lg.ring-2";

    // Track created FAQs for cleanup
    const createdFaqQuestions: string[] = [];

    // Helper function to create FAQ and track for cleanup
    const createAndTrackFaq = async (
        page: Page,
        question: string,
        answer: string,
        category: string = "General",
        skipTracking: boolean = false
    ) => {
        const createResponsePromise = page.waitForResponse(
            (response) =>
                response.url().includes("/admin/faqs") &&
                response.request().method() === "POST",
            { timeout: 30000 }
        );
        await page.click('button:has-text("Add New FAQ")');
        await page.fill("input#question", question);
        await page.fill("textarea#answer", answer);
        if (category !== "General") {
            await selectCategory(page, category);
        }
        await page.click('button:has-text("Add FAQ")');
        const createResponse = await createResponsePromise;
        expect(createResponse.ok()).toBeTruthy();
        await page.getByRole("dialog", { name: "Add New FAQ" }).waitFor({
            state: "hidden",
            timeout: 30000,
        });

        const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${question}")`);
        await faqCard.waitFor({ state: "visible", timeout: 30000 });

        // Track for cleanup (unless test will delete it itself)
        if (!skipTracking) {
            createdFaqQuestions.push(question);
        }

        return faqCard;
    };

    test.beforeEach(async ({ page, context, request }) => {
        // Clear cookies to ensure clean authentication state
        await context.clearCookies();

        // Wait for API to be ready (important after container restart tests)
        await waitForApiReady(request);

        // Inject console error tracking BEFORE navigation
        await page.addInitScript(() => {
            window.consoleErrors = [];
            const originalError = console.error;
            console.error = (...args: any[]) => {
                window.consoleErrors.push(args.map(String).join(" "));
                originalError.apply(console, args);
            };
        });

        await loginAsAdmin(page, ADMIN_API_KEY, WEB_BASE_URL);
        await page.click('a[href="/admin/manage-faqs"]');
        await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 30000 });
        await Promise.any([
            page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 5000 }),
            page.waitForSelector('button:has-text("Add New FAQ")', { timeout: 5000 }),
        ]);
    });

    test.afterEach(async ({ page, request }) => {
        // Clean up created FAQs to prevent database pollution
        for (const question of createdFaqQuestions) {
            try {
                // Find the FAQ by question text using API
                const response = await request.get(`${API_BASE_URL}/admin/faqs`, {
                    headers: {
                        "x-api-key": ADMIN_API_KEY,
                    },
                });

                if (response.ok()) {
                    const data = await response.json();
                    const faq = data.faqs?.find((f: any) => f.question === question);
                    if (faq) {
                        // Delete the FAQ via API
                        await request.delete(`${API_BASE_URL}/admin/faqs/${faq.id}`, {
                            headers: {
                                "x-api-key": ADMIN_API_KEY,
                            },
                        });
                    }
                }
            } catch (error) {
                // Ignore cleanup errors - test already completed
                console.log(`Cleanup failed for FAQ: ${question}`, error);
            }
        }

        // Clear the tracking array for next test
        createdFaqQuestions.splice(0);
    });

    test("should display existing FAQs", async ({ page }) => {
        // Wait for FAQ cards to load
        await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

        // Verify FAQ cards exist
        const faqCards = await page.locator(FAQ_CARD_SELECTOR).count();
        expect(faqCards).toBeGreaterThan(0);
    });

    test("should create a new FAQ", async ({ page }) => {
        // Create a test FAQ and track for cleanup
        const testQuestion = `Test FAQ Question ${Date.now()}`;
        const faqCard = await createAndTrackFaq(
            page,
            testQuestion,
            "Test FAQ Answer for E2E testing"
        );
        await expect(faqCard).toBeVisible({ timeout: 30000 });
    });

    test("should edit an existing FAQ", async ({ page }) => {
        // Create a test FAQ to edit and track for cleanup
        const testQuestion = `FAQ to be edited ${Date.now()}`;
        const faqCard = await createAndTrackFaq(page, testQuestion, "Original answer");

        // Select the FAQ card and enter edit mode via the stable keyboard shortcut path.
        await faqCard.click();
        await expect(page.locator(`${SELECTED_FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`)).toBeVisible({
            timeout: 5000,
        });
        await page.keyboard.press("Enter");

        // Wait for inline edit mode to activate (textarea becomes visible)
        await page.locator("textarea").first().waitFor({ state: "visible", timeout: 5000 });

        // In inline edit mode, the FAQ card is replaced with a Card component containing editable fields
        // Find the textarea in the edit form (it's the only textarea visible on the page)
        const inlineAnswerField = page.locator("textarea").first();
        await inlineAnswerField.waitFor({ state: "visible", timeout: 5000 });
        await inlineAnswerField.clear();
        await inlineAnswerField.fill("Updated answer via E2E test");

        // Save changes by clicking the "Save" button (text button, not icon)
        const saveButton = page.getByRole("button", { name: "Save", exact: true });
        const updateResponsePromise = page.waitForResponse(
            (response) =>
                response.url().includes("/admin/faqs/") &&
                response.request().method() === "PUT",
            { timeout: 30000 }
        );
        await saveButton.click({ timeout: 5000 });
        const updateResponse = await updateResponsePromise;
        expect(updateResponse.ok()).toBeTruthy();

        // Wait for save operation to complete (Save button disappears, view mode returns)
        await expect(saveButton).toBeHidden({ timeout: 30000 });

        // Re-query for the FAQ card after save (the list may refresh and locator becomes stale)
        const updatedFaqCard = page.locator(
            `${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`
        );

        // Wait for the updated content to appear in the FAQ card
        await expect(updatedFaqCard).toContainText("Updated answer", { timeout: 30000 });
    });

    test("should delete a FAQ (CRITICAL: Tests permission issue)", async ({ page }) => {
        // Create a test FAQ to delete (skip tracking since test deletes it)
        const testQuestion = `FAQ to be deleted ${Date.now()}`;
        const faqCard = await createAndTrackFaq(
            page,
            testQuestion,
            "This FAQ will be deleted",
            "General",
            true
        );

        // Select the FAQ card and trigger deletion via the stable keyboard shortcut path.
        await faqCard.click();
        await page.keyboard.press("d");

        // Wait for AlertDialog to appear and click Continue
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        const continueButton = dialog.getByRole("button", { name: "Continue" });
        await continueButton.click();

        // Wait for dialog to close after deletion
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // Verify FAQ is removed from list
        const deletedFaq = page.locator(
            `${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`
        );
        await expect(deletedFaq).toHaveCount(0, { timeout: 10000 });

        // CRITICAL: Verify no permission errors in console
        const logs = await page.evaluate(() => {
            return window.consoleErrors || [];
        });
        const hasPermissionError = logs.some(
            (log: string) => log.includes("Permission denied") || log.includes("EACCES")
        );
        expect(hasPermissionError).toBe(false);
    });

    test("should filter FAQs by category", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(FAQ_CARD_SELECTOR);

        // Use the new smart filter chip (always visible)
        const categoryChip = page.locator("text=All Categories").first();
        await categoryChip.click();

        // Wait for dropdown to appear
        await page.waitForSelector('[role="option"]', { timeout: 5000 });

        // Select first category (skip "All Categories")
        const categoryOptions = page.locator('[role="option"]');
        const optionCount = await categoryOptions.count();

        if (optionCount > 1) {
            // Click second option (first real category)
            await categoryOptions.nth(1).click();

            // Wait for dropdown to close after selection
            await page.waitForSelector('[role="option"]', { state: "hidden", timeout: 5000 });

            // Verify FAQs are filtered (at least one result)
            const faqCards = page.locator(FAQ_CARD_SELECTOR);
            await expect(faqCards.first()).toBeVisible({ timeout: 10000 });
            const count = await faqCards.count();
            expect(count).toBeGreaterThan(0);
        }
    });

    test("should search FAQs by text", async ({ page }) => {
        // First, create a FAQ with a unique searchable term
        const searchTerm = "BisqSearchTest";
        const testQuestion = `${searchTerm} Question ${Date.now()}`;
        await createAndTrackFaq(
            page,
            testQuestion,
            "This FAQ is for testing the search functionality"
        );

        // Now test the search functionality
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill(searchTerm);

        // Wait for search results to show our FAQ (debounced search completes)
        const faqCards = page.locator(FAQ_CARD_SELECTOR);
        await expect(faqCards.first()).toContainText(searchTerm, { timeout: 5000 });

        const count = await faqCards.count();

        expect(count).toBeGreaterThan(0);

        // Verify the search result contains our test FAQ
        const firstCard = await faqCards.first().textContent();
        expect(firstCard?.toLowerCase()).toContain(searchTerm.toLowerCase());
    });

    test("should verify FAQ deletion persists after page reload", async ({ page }) => {
        // Create a test FAQ
        const testQuestion = `Persistence test ${Date.now()}`;
        const faqCard = await createAndTrackFaq(page, testQuestion, "Testing persistence");
        await faqCard.click();
        await page.keyboard.press("d");

        // Wait for dialog and confirm
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 15000 });
        const continueButton = dialog.getByRole("button", { name: "Continue" });
        await continueButton.waitFor({ state: "visible", timeout: 5000 });
        await continueButton.click();

        // Wait for dialog to close after deletion
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // Wait for FAQ to be removed from DOM
        const deletedFaqCheck = page.locator(
            `${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`
        );
        await expect(deletedFaqCheck).toHaveCount(0, { timeout: 10000 });

        // Reload page
        await page.reload();

        // Wait for FAQ management page to reload
        await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });

        // Wait for FAQ cards or "Add New FAQ" button to appear
        await Promise.race([
            page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 5000 }).catch(() => null),
            page.waitForSelector('button:has-text("Add New FAQ")', { timeout: 5000 }),
        ]);

        // Verify FAQ is still gone (tests that deletion was persisted to disk)
        const deletedFaq = page.locator(
            `${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`
        );
        await expect(deletedFaq).toHaveCount(0);
    });

    test("should handle concurrent FAQ operations", async ({ page, context }) => {
        // Open second admin page in same context (shares cookies)
        const page2 = await context.newPage();
        await page2.goto(`${WEB_BASE_URL}/admin`);

        // Since we share the browser context, we should already be authenticated
        // Wait for the authenticated UI to appear (will redirect to /admin/overview)
        await page2.waitForSelector("nav a[href='/admin/overview']", { timeout: 10000 });
        await page2.click('a[href="/admin/manage-faqs"]');
        await page2.waitForSelector("text=FAQ", { timeout: 10000 });

        const testQuestion = `Concurrent test ${Date.now()}`;
        await createAndTrackFaq(page, testQuestion, "Testing concurrent access");

        // Refresh second page and verify FAQ appears
        await page2.reload();
        await page2.waitForSelector(FAQ_CARD_SELECTOR);
        const faqOnPage2 = page2.locator(
            `${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`
        );
        await expect(faqOnPage2).toBeVisible();

        // Cleanup
        await page2.close();
    });

    test("should verify FAQ with confirmation dialog", async ({ page }) => {
        const testQuestion = `FAQ for verification test ${Date.now()}`;
        const faqCard = await createAndTrackFaq(
            page,
            testQuestion,
            "This FAQ will be verified"
        );

        // Verify initial state - Badge component with "Verified" text should NOT exist
        // Use more specific selector for the Badge component (not the answer text)
        const verifiedBadge = faqCard.locator('.inline-flex.items-center:has-text("Verified")');
        await expect(verifiedBadge).toHaveCount(0);

        await faqCard.click();
        await page.keyboard.press("v");

        // Wait for confirmation dialog
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        await expect(dialog).toContainText("Verify this FAQ?");
        await expect(dialog).toContainText("This action is irreversible");

        // Click confirm button and wait for dialog to close
        const confirmButton = dialog.getByRole("button", { name: "Verify FAQ" });
        await confirmButton.click();

        // Wait for dialog to close after verification
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // Verify Badge component with "Verified" text is now visible
        const verifiedBadgeAfter = faqCard.locator(
            '.inline-flex.items-center:has-text("Verified")'
        );
        await expect(verifiedBadgeAfter).toBeVisible({ timeout: 10000 });

        // Verify button is no longer exposed once verified.
        const verifyButtonAfter = faqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfter).toHaveCount(0);
    });

    test("should persist verification status after page reload", async ({ page }) => {
        const testQuestion = `FAQ for persistence test ${Date.now()}`;
        const faqCard = await createAndTrackFaq(
            page,
            testQuestion,
            "Testing verification persistence"
        );
        await faqCard.click();
        await page.keyboard.press("v");

        // Confirm in dialog - use dialog role selector
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });

        // Click confirm button and wait for dialog to close
        const confirmButton = dialog.getByRole("button", { name: "Verify FAQ" });
        await confirmButton.click();

        // Wait for dialog to close after verification
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // Verify badge shows "Verified"
        const verifiedBadge = faqCard.locator("text=Verified");
        await expect(verifiedBadge).toBeVisible({ timeout: 10000 });

        // Reload page
        await page.reload();
        await page.waitForSelector(FAQ_CARD_SELECTOR);

        // Find FAQ card again after reload
        const faqCardAfterReload = page.locator(
            `${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`
        );

        // Verify badge still shows "Verified" (tests persistence to disk)
        const verifiedBadgeAfterReload = faqCardAfterReload.locator("text=Verified");
        await expect(verifiedBadgeAfterReload).toBeVisible();

        // Verify button is still hidden (can't unverify)
        const verifyButtonAfterReload = faqCardAfterReload.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfterReload).toHaveCount(0);
    });

    test("should display verification button for unverified FAQs only", async ({ page }) => {
        const testQuestion = `Unverified FAQ test ${Date.now()}`;
        const unverifiedFaqCard = await createAndTrackFaq(
            page,
            testQuestion,
            "This FAQ is unverified"
        );

        // Check that "Verify FAQ" button exists for unverified FAQ
        await unverifiedFaqCard.click();
        const verifyButton = unverifiedFaqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButton).toBeVisible();

        // Now verify the FAQ
        await page.keyboard.press("v");

        // Wait for dialog and confirm
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });

        // Click confirm button and wait for dialog to close
        const confirmButton = dialog.getByRole("button", { name: "Verify FAQ" });
        await confirmButton.click();

        // Wait for dialog to close after verification
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // After verification, the button should no longer be visible
        const verifyButtonAfter = unverifiedFaqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfter).toHaveCount(0, { timeout: 10000 });

        // Verified badge should be visible
        const verifiedBadge = unverifiedFaqCard.locator(
            '.inline-flex.items-center:has-text("Verified")'
        );
        await expect(verifiedBadge).toBeVisible();
    });

    test("should cancel verification when dialog is cancelled", async ({ page }) => {
        const testQuestion = `FAQ for cancel test ${Date.now()}`;
        const faqCard = await createAndTrackFaq(page, testQuestion, "Testing cancellation");
        await faqCard.click();
        await page.keyboard.press("v");

        // Wait for dialog
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        await expect(dialog).toContainText("Verify this FAQ?");

        // Click Cancel button (use exact match and first() to handle multiple buttons)
        const cancelButton = dialog.getByRole("button", { name: "Cancel", exact: true }).first();
        await cancelButton.click();

        // Wait for dialog to close
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // Verify FAQ is still unverified (no badge)
        const verifiedBadge = faqCard.locator("text=Verified");
        await expect(verifiedBadge).toHaveCount(0);

        // Verify button should still be visible
        const verifyButtonAfter = faqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfter).toBeVisible();
    });
});
