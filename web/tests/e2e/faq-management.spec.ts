import { test, expect } from "@playwright/test";
import { selectCategory } from "./utils";

/**
 * FAQ Management Tests
 *
 * These tests verify that FAQ CRUD operations work correctly,
 * particularly focusing on the permission issues that cause
 * FAQ deletion to fail after container restarts.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || "dev_admin_key";

test.describe("FAQ Management", () => {
    test.beforeEach(async ({ page }) => {
        // Navigate to admin page (redirects to /admin/overview)
        await page.goto("http://localhost:3000/admin");

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
            page
                .waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 5000 })
                .catch(() => null),
            page.waitForSelector('button:has-text("Add New FAQ")', { timeout: 5000 }),
        ]);
    });

    test("should display existing FAQs", async ({ page }) => {
        // Wait for FAQ cards to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

        // Verify FAQ cards exist
        const faqCards = await page.locator(".bg-card.border.border-border.rounded-lg").count();
        expect(faqCards).toBeGreaterThan(0);
    });

    test("should create a new FAQ", async ({ page }) => {
        // Click "Add New FAQ" button
        await page.click('button:has-text("Add New FAQ")');

        // Fill in the form with unique question
        const testQuestion = `Test FAQ Question ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Test FAQ Answer for E2E testing");
        await selectCategory(page, "General");

        // Submit form
        await page.click('button:has-text("Add FAQ")');

        // Wait for FAQ list to update
        await page.waitForTimeout(1000);

        // Verify FAQ appears in the list
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await expect(faqCard).toBeVisible();
    });

    test("should edit an existing FAQ", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

        // Find first FAQ card
        const firstFaqCard = page.locator(".bg-card.border.border-border.rounded-lg").first();

        // Click edit button - it's in the actions container on the right
        // Find all buttons, filter out "Verify FAQ" text button, get first remaining (Pencil)
        const allButtons = firstFaqCard.locator("button");
        const buttonCount = await allButtons.count();

        // Iterate to find the Pencil button (has no text, just icon)
        for (let i = 0; i < buttonCount; i++) {
            const btn = allButtons.nth(i);
            const text = await btn.textContent();
            // Pencil button has no text (or only whitespace)
            if (!text || text.trim().length === 0) {
                await btn.click();
                break;
            }
        }

        // Wait for edit form to open and form fields to be visible
        await page.waitForTimeout(500);
        const answerField = page.locator("textarea#answer");
        await answerField.waitFor({ state: "visible", timeout: 5000 });

        // Modify the answer
        await answerField.clear();
        await answerField.fill("Updated answer via E2E test");

        // Save changes
        await page.click('button:has-text("Save Changes")');

        // Wait for save to complete (form closes and data reloads)
        await page.waitForTimeout(2000);

        // Verify change persisted
        await page.reload();
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });
        const updatedCard = await page
            .locator(".bg-card.border.border-border.rounded-lg")
            .first()
            .textContent();
        expect(updatedCard).toContain("Updated answer");
    });

    test("should delete a FAQ (CRITICAL: Tests permission issue)", async ({ page }) => {
        // Create a test FAQ to delete (using same pattern as working persistence test)
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `FAQ to be deleted ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "This FAQ will be deleted");
        await selectCategory(page, "General");
        await page.click('button:has-text("Add FAQ")');

        // Wait for form to close and FAQ to appear (same pattern as persistence test)
        await page.waitForSelector('button:has-text("Add New FAQ")', {
            state: "visible",
            timeout: 10000,
        });
        await page.waitForTimeout(500);

        // Find FAQ card and wait for it to be visible
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 5000 });

        // Click delete button (Trash2 icon) - it's the second button with no text (first is Pencil)
        const allButtons = faqCard.locator("button");
        const buttonCount = await allButtons.count();
        let iconButtonIndex = 0;

        for (let i = 0; i < buttonCount; i++) {
            const btn = allButtons.nth(i);
            const text = await btn.textContent();
            if (!text || text.trim().length === 0) {
                if (iconButtonIndex === 1) {
                    // Second icon button is delete
                    await btn.click();
                    break;
                }
                iconButtonIndex++;
            }
        }

        // Wait for AlertDialog to appear and click Continue
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        const continueButton = dialog.getByRole("button", { name: "Continue" });
        await continueButton.click();

        // Wait for deletion to complete (form closes and data reloads)
        await page.waitForTimeout(2000);

        // Verify FAQ is removed from list
        const deletedFaq = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await expect(deletedFaq).toHaveCount(0);

        // CRITICAL: Verify no permission errors in console
        const logs = await page.evaluate(() => {
            // @ts-ignore
            return window.consoleErrors || [];
        });
        const hasPermissionError = logs.some(
            (log: string) => log.includes("Permission denied") || log.includes("EACCES")
        );
        expect(hasPermissionError).toBe(false);
    });

    test("should filter FAQs by category", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg");

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

            // Wait for filter to apply
            await page.waitForTimeout(1000);

            // Verify FAQs are filtered
            const faqCards = page.locator(".bg-card.border.border-border.rounded-lg");
            const count = await faqCards.count();
            expect(count).toBeGreaterThan(0);
        }
    });

    test("should search FAQs by text", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg");

        // Use the persistent inline search (always visible)
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill("Bisq");

        // Wait for debounced search (300ms debounce)
        await page.waitForTimeout(500);

        // Verify all visible FAQs contain search term
        const faqCards = page.locator(".bg-card.border.border-border.rounded-lg");
        const count = await faqCards.count();

        expect(count).toBeGreaterThan(0);

        for (let i = 0; i < Math.min(count, 5); i++) {
            const text = await faqCards.nth(i).textContent();
            expect(text?.toLowerCase()).toMatch(/bisq/i);
        }
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
        await page.waitForTimeout(500);

        // Find FAQ card and wait for it to be visible
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await faqCard.waitFor({ state: "visible", timeout: 5000 });

        // Click delete button (Trash2 icon) - it's the second button with no text
        const allButtons = faqCard.locator("button");
        const buttonCount = await allButtons.count();
        let iconButtonIndex = 0;

        for (let i = 0; i < buttonCount; i++) {
            const btn = allButtons.nth(i);
            const text = await btn.textContent();
            if (!text || text.trim().length === 0) {
                if (iconButtonIndex === 1) {
                    // Second icon button is delete
                    await btn.click();
                    break;
                }
                iconButtonIndex++;
            }
        }

        // Wait for dialog and confirm
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 15000 });
        const continueButton = dialog.getByRole("button", { name: "Continue" });
        await continueButton.waitFor({ state: "visible", timeout: 5000 });
        await continueButton.click();

        // Wait for deletion to complete
        await page.waitForTimeout(2000);

        // Reload page
        await page.reload();

        // Wait for FAQ management page to reload
        await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });

        // Wait for FAQ cards or "Add New FAQ" button to appear
        await Promise.race([
            page
                .waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 5000 })
                .catch(() => null),
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
        await page2.goto("http://localhost:3000/admin");

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
        await page.waitForTimeout(1000);

        // Refresh second page and verify FAQ appears
        await page2.reload();
        await page2.waitForSelector(".bg-card.border.border-border.rounded-lg");
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
        await page.waitForTimeout(1000);

        // Verify Badge component with "Verified" text is now visible
        const verifiedBadgeAfter = faqCard.locator(
            '.inline-flex.items-center:has-text("Verified")'
        );
        await expect(verifiedBadgeAfter).toBeVisible();

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
        await page.waitForTimeout(1000);

        // Verify badge shows "Verified"
        const verifiedBadge = faqCard.locator("text=Verified");
        await expect(verifiedBadge).toBeVisible();

        // Reload page
        await page.reload();
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg");

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
        await page.waitForTimeout(1000);

        // After verification, the button should no longer be visible
        const verifyButtonAfter = unverifiedFaqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfter).toHaveCount(0);

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
        await page.waitForSelector("text=Verify this FAQ?");
        await page.waitForTimeout(1000); // Wait for dialog animations

        // Click Cancel button
        await page.locator('[role="alertdialog"] button:has-text("Cancel")').click();
        await page.waitForTimeout(1000); // Wait for dialog to close

        // Verify FAQ is still unverified (no badge)
        const verifiedBadge = faqCard.locator("text=Verified");
        await expect(verifiedBadge).toHaveCount(0);

        // Verify button should still be visible
        const verifyButtonAfter = faqCard.locator('button:has-text("Verify FAQ")');
        await expect(verifyButtonAfter).toBeVisible();
    });
});
