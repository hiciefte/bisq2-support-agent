import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { selectCategory, API_BASE_URL, ADMIN_API_KEY, WEB_BASE_URL } from "./utils";

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
    // FAQ card selector constant - used throughout tests
    const FAQ_CARD_SELECTOR = ".bg-card.border.border-border.rounded-lg";

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
        await page.click('button:has-text("Add New FAQ")');
        await page.fill("input#question", question);
        await page.fill("textarea#answer", answer);
        await selectCategory(page, category);
        await page.click('button:has-text("Add FAQ")');

        // Track for cleanup (unless test will delete it itself)
        if (!skipTracking) {
            createdFaqQuestions.push(question);
        }
    };

    test.beforeEach(async ({ page }) => {
        // Inject console error tracking BEFORE navigation
        await page.addInitScript(() => {
            window.consoleErrors = [];
            const originalError = console.error;
            console.error = (...args: any[]) => {
                window.consoleErrors.push(args.map(String).join(" "));
                originalError.apply(console, args);
            };
        });

        // Navigate to admin page (redirects to /admin/overview)
        await page.goto(`${WEB_BASE_URL}/admin`);

        // Wait for login form to appear
        await page.waitForSelector('input[type="password"]', { timeout: 10000 });

        // Login with admin API key
        await page.fill('input[type="password"]', ADMIN_API_KEY);
        await page.click('button:has-text("Login")');

        // Wait for authenticated UI to appear (sidebar with navigation)
        await page.waitForSelector("text=Admin Dashboard", { timeout: 10000 });

        // Navigate to FAQ management
        await page.click('a[href="/admin/manage-faqs"]');

        // Wait for FAQ management page to load - look for specific heading
        await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });

        // Wait for either FAQ cards to appear OR "Add New FAQ" button (if no FAQs exist)
        await Promise.race([
            page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 5000 }).catch(() => null),
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
        await createAndTrackFaq(page, testQuestion, "Test FAQ Answer for E2E testing");

        // Wait for Sheet to close (form is hidden after successful submission)
        // The API reindexes the vector store which can take several seconds
        await page.waitForSelector('form >> text="Add New FAQ"', {
            state: "hidden",
            timeout: 15000,
        });

        // Wait for the FAQ list to refresh and FAQ to appear
        const faqCard = page.locator(`text="${testQuestion}"`);
        await expect(faqCard).toBeVisible({ timeout: 10000 });
    });

    test("should edit an existing FAQ", async ({ page }) => {
        // Create a test FAQ to edit and track for cleanup
        const testQuestion = `FAQ to be edited ${Date.now()}`;
        await createAndTrackFaq(page, testQuestion, "Original answer");

        // Wait for form to close and FAQ to appear
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });

        // Find the newly created FAQ card
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 10000 });

        // Hover to show action buttons and click edit (enters inline edit mode)
        await faqCard.hover();
        const editButton = faqCard.locator('[data-testid="edit-faq-button"]');
        await editButton.click({ timeout: 5000 });

        // Wait for inline edit mode to activate (textarea becomes visible)
        await page.locator("textarea").first().waitFor({ state: "visible", timeout: 5000 });

        // In inline edit mode, the FAQ card is replaced with a Card component containing editable fields
        // Find the textarea in the edit form (it's the only textarea visible on the page)
        const inlineAnswerField = page.locator("textarea").first();
        await inlineAnswerField.waitFor({ state: "visible", timeout: 5000 });
        await inlineAnswerField.clear();
        await inlineAnswerField.fill("Updated answer via E2E test");

        // Save changes by clicking the "Save" button (text button, not icon)
        const saveButton = page.locator('button:has-text("Save")');
        await saveButton.click({ timeout: 5000 });

        // Wait for save operation to complete (Save button disappears, view mode returns)
        // The API reindexes the vector store which can take several seconds
        await expect(saveButton).toBeHidden({ timeout: 15000 });

        // Wait for the updated content to appear in the FAQ card
        await expect(faqCard).toContainText("Updated answer", { timeout: 10000 });
    });

    test("should delete a FAQ (CRITICAL: Tests permission issue)", async ({ page }) => {
        // Create a test FAQ to delete (skip tracking since test deletes it)
        const testQuestion = `FAQ to be deleted ${Date.now()}`;
        await createAndTrackFaq(page, testQuestion, "This FAQ will be deleted", "General", true);

        // Wait for form to close and FAQ to appear (same pattern as persistence test)
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });

        // Wait for FAQ card to appear in the list
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 10000 });

        // Click delete button using test ID (reliable selector that won't break with UI changes)
        await faqCard.hover();
        const deleteButton = faqCard.locator('[data-testid="delete-faq-button"]');
        await deleteButton.click();

        // Wait for AlertDialog to appear and click Continue
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        const continueButton = dialog.getByRole("button", { name: "Continue" });
        await continueButton.click();

        // Wait for dialog to close after deletion
        await dialog.waitFor({ state: "hidden", timeout: 5000 });

        // Verify FAQ is removed from list
        const deletedFaq = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
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
        await page.click('button:has-text("Add New FAQ")');
        await page.waitForSelector('form >> text="Add New FAQ"', { timeout: 5000 });

        const searchTerm = "BisqSearchTest";
        const testQuestion = `${searchTerm} Question ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "This FAQ is for testing the search functionality");
        await selectCategory(page, "General");

        await page.click('button[type="submit"]:has-text("Add FAQ")');
        await page.waitForSelector('form >> text="Add New FAQ"', {
            state: "hidden",
            timeout: 15000,
        });

        // Track for cleanup
        createdFaqQuestions.push(testQuestion);

        // Wait for the created FAQ to appear in the list
        const createdFaq = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await createdFaq.waitFor({ state: "visible", timeout: 10000 });

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
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `Persistence test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Testing persistence");
        await selectCategory(page, "General");
        await page.click('button:has-text("Add FAQ")');

        // Wait for form to close and FAQ to appear
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });

        // Wait for FAQ card to appear in the list
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 10000 });

        // Click delete button using test ID (reliable selector that won't break with UI changes)
        await faqCard.hover();
        const deleteButton = faqCard.locator('[data-testid="delete-faq-button"]');
        await deleteButton.click();

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
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
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
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await expect(deletedFaq).toHaveCount(0);
    });

    test("should handle concurrent FAQ operations", async ({ page, context }) => {
        // Open second admin page in same context (shares cookies)
        const page2 = await context.newPage();
        await page2.goto(`${WEB_BASE_URL}/admin`);

        // Since we share the browser context, we should already be authenticated
        // Wait for the authenticated UI to appear (will redirect to /admin/overview)
        await page2.waitForSelector("text=Admin Dashboard", { timeout: 10000 });
        await page2.click('a[href="/admin/manage-faqs"]');
        await page2.waitForSelector("text=FAQ", { timeout: 10000 });

        // Create FAQ on first page
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `Concurrent test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Testing concurrent access");
        await selectCategory(page, "General");
        await page.click('button:has-text("Add FAQ")');

        // Track for cleanup
        createdFaqQuestions.push(testQuestion);

        // Wait for FAQ to appear in the first page
        const newFaqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await newFaqCard.waitFor({ state: "visible", timeout: 15000 });

        // Refresh second page and verify FAQ appears
        await page2.reload();
        await page2.waitForSelector(FAQ_CARD_SELECTOR);
        const faqOnPage2 = page2.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await expect(faqOnPage2).toBeVisible();

        // Cleanup
        await page2.close();
    });

    test("should verify FAQ with confirmation dialog", async ({ page }) => {
        // Create a test FAQ to verify
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `FAQ for verification test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "This FAQ will be verified");
        await selectCategory(page, "General");

        // Click submit button and wait for dialog to close
        await page.waitForSelector('button[type="submit"]:has-text("Add FAQ")', {
            state: "visible",
            timeout: 5000,
        });
        await page.click('button[type="submit"]:has-text("Add FAQ")');

        // Track for cleanup
        createdFaqQuestions.push(testQuestion);

        // Wait for form dialog to close (Add New FAQ button becomes visible again)
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });

        // Find the newly created FAQ card - wait for it to exist
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 10000 });

        // Verify initial state - Badge component with "Verified" text should NOT exist
        // Use more specific selector for the Badge component (not the answer text)
        const verifiedBadge = faqCard.locator('.inline-flex.items-center:has-text("Verified")');
        await expect(verifiedBadge).toHaveCount(0);

        // Verify "Verify FAQ" button is visible
        const verifyButton = faqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButton).toBeVisible();

        // Click verify button
        await verifyButton.click();

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

        // Verify "Verify FAQ" button is no longer visible (can't toggle back)
        const verifyButtonAfter = faqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfter).toHaveCount(0);
    });

    test("should persist verification status after page reload", async ({ page }) => {
        // Create a test FAQ
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `FAQ for persistence test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Testing verification persistence");
        await selectCategory(page, "General");

        // Click submit button and wait for dialog to close
        await page.waitForSelector('button[type="submit"]:has-text("Add FAQ")', {
            state: "visible",
            timeout: 5000,
        });
        await page.click('button[type="submit"]:has-text("Add FAQ")');

        // Track for cleanup
        createdFaqQuestions.push(testQuestion);

        // Wait for form dialog to close and FAQ card to appear
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 10000 });

        // Find and click verify button
        const verifyButton = faqCard.locator('button:has-text("Verify FAQ")');
        await verifyButton.click();

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
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );

        // Verify badge still shows "Verified" (tests persistence to disk)
        const verifiedBadgeAfterReload = faqCardAfterReload.locator("text=Verified");
        await expect(verifiedBadgeAfterReload).toBeVisible();

        // Verify button is still hidden (can't unverify)
        const verifyButtonAfterReload = faqCardAfterReload.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfterReload).toHaveCount(0);
    });

    test("should display verification button for unverified FAQs only", async ({ page }) => {
        // Create an unverified test FAQ
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `Unverified FAQ test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "This FAQ is unverified");
        await selectCategory(page, "General");

        // Click submit button and wait for dialog to close
        await page.waitForSelector('button[type="submit"]:has-text("Add FAQ")', {
            state: "visible",
            timeout: 5000,
        });
        await page.click('button[type="submit"]:has-text("Add FAQ")');

        // Track for cleanup
        createdFaqQuestions.push(testQuestion);

        // Wait for form dialog to close
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });

        // Find the unverified FAQ card
        const unverifiedFaqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await unverifiedFaqCard.waitFor({ state: "visible", timeout: 10000 });

        // Check that "Verify FAQ" button exists for unverified FAQ
        const verifyButton = unverifiedFaqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButton).toBeVisible();

        // Now verify the FAQ
        await verifyButton.click();

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
        // Create a test FAQ
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `FAQ for cancel test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Testing cancellation");
        await selectCategory(page, "General");

        // Click submit button and wait for dialog to close
        await page.waitForSelector('button[type="submit"]:has-text("Add FAQ")', {
            state: "visible",
            timeout: 5000,
        });
        await page.click('button[type="submit"]:has-text("Add FAQ")');

        // Track for cleanup
        createdFaqQuestions.push(testQuestion);

        // Wait for form dialog to close
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });

        // Find the FAQ card
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 10000 });

        // Click verify button
        const verifyButton = faqCard.locator('button:has-text("Verify FAQ")');
        await verifyButton.click();

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
