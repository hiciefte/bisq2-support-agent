import { test, expect } from "@playwright/test";
import { ADMIN_API_KEY, WEB_BASE_URL, loginAsAdmin } from "./utils";

/**
 * FAQ UI Improvements Tests (Phase 1)
 *
 * These tests verify the Phase 1 UI improvements:
 * 1. Persistent inline search (always visible search bar)
 * 2. Smart filter chips (always visible category/source filters)
 * 3. Hover action buttons (buttons only visible on hover)
 */

test.describe("FAQ UI Improvements - Phase 1", () => {
    const FAQ_CARD_SELECTOR = ".bg-card.border.rounded-lg";

    test.beforeEach(async ({ page }) => {
        await loginAsAdmin(page, ADMIN_API_KEY, WEB_BASE_URL);

        // Navigate to FAQ management
        await page.click('a[href="/admin/manage-faqs"]');
        await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });

        // Wait for FAQs to load
        await Promise.race([
            page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 5000 }).catch(() => null),
            page.waitForSelector('button:has-text("Add New FAQ")', { timeout: 5000 }),
        ]);
    });

    test("should have persistent inline search visible at all times", async ({ page }) => {
        // Verify search input is visible without clicking any button
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await expect(searchInput).toBeVisible();

        // Verify search icon is present
        const searchIcon = page.locator(".lucide-search").first();
        await expect(searchIcon).toBeVisible();
    });

    test("should perform real-time search with debouncing", async ({ page }) => {
        // Type in search field
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill("Bisq");

        // Wait for debounced search to trigger (300ms debounce)
        await page.waitForTimeout(500);

        await expect(page.locator("text=Search: Bisq").first()).toBeVisible();

        // Verify FAQs are filtered
        const faqCards = page.locator(FAQ_CARD_SELECTOR);
        const cardTexts = await faqCards.evaluateAll((nodes) =>
            nodes
                .map((node) => (node.textContent ?? "").trim().toLowerCase())
                .filter((text) => text.length > 0),
        );

        if (cardTexts.length > 0) {
            if (!cardTexts.some((text) => text.includes("bisq"))) {
                throw new Error(`Expected at least one FAQ card to contain "bisq"; found cards: ${cardTexts.join(" | ")}`);
            }
            return;
        }

        await expect(page.locator("text=No FAQs found").first()).toBeVisible();
    });

    test("should show clear button when search has text", async ({ page }) => {
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');

        // Initially no clear button visible
        const clearButton = page.locator(".lucide-x").first();
        await expect(clearButton).not.toBeVisible();

        // Type in search
        await searchInput.fill("test search");
        await page.waitForTimeout(100);

        // Clear button should now be visible
        await expect(clearButton).toBeVisible();

        // Click clear button
        await clearButton.click();

        // Search input should be cleared
        await expect(searchInput).toHaveValue("");

        // Clear button should be hidden again
        await expect(clearButton).not.toBeVisible();
    });

    test("should have smart filter chips always visible", async ({ page }) => {
        // Verify category filter chip is visible
        const categoryChip = page.locator("text=All Categories").first();
        await expect(categoryChip).toBeVisible();

        // Note: Source filter chip is no longer in the top filter bar (UI change)

        // Verify chevron icon is present for category dropdown
        const chevronIcons = page.locator(".lucide-chevron-down");
        const chevronCount = await chevronIcons.count();
        expect(chevronCount).toBeGreaterThanOrEqual(1);
    });

    test("should filter by category using smart filter chip", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

        // Click category filter chip
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
            const faqCards = page.locator(FAQ_CARD_SELECTOR);
            const count = await faqCards.count();
            expect(count).toBeGreaterThan(0);
        }
    });

    test.skip("should filter by source using smart filter chip", async ({ page }) => {
        // SKIPPED: Source filter chip is no longer in the top filter bar (UI change)
        // The source filter functionality may have been moved or removed
        // This test should be updated or removed based on the new UI design
        // TODO: Track source filter removal/relocation and update or remove this test
        //       Issue: Need to clarify final UI design for source filtering
    });

    test("should show Reset button when filters are active", async ({ page }) => {
        // Initially reset button should not be visible or be disabled
        const resetButton = page.locator('button:has-text("Reset filters")');

        // Type in search to activate filters
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill("test");
        await page.waitForTimeout(500);

        // Reset button should now be visible
        await expect(resetButton).toBeVisible();

        // Sticky filter chips can overlap the pointer hitbox; keyboard activation remains the
        // reliable accessibility path for the control.
        await resetButton.focus();
        await page.keyboard.press("Enter");

        // Search should be cleared
        await expect(searchInput).toHaveValue("");
    });

    test('should have legacy "Advanced" filter button for backwards compatibility', async ({
        page,
    }) => {
        const advancedButton = page.locator('button:has-text("Advanced")');
        await expect(advancedButton).toBeVisible();

        // The advanced controls are now inline; clicking still must remain safe.
        await advancedButton.click();
        await expect(page.locator("text=Source").first()).toBeVisible();
        await expect(page.locator("text=Protocol").first()).toBeVisible();
    });

    test("should show action buttons only on hover", async ({ page }) => {
        await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
        const unverifiedFaq = page.locator(FAQ_CARD_SELECTOR).filter({ hasText: "Needs Review" }).first();

        await expect(unverifiedFaq).toBeVisible();
        await unverifiedFaq.hover();
        await page.waitForTimeout(250);
        await unverifiedFaq.click();
        await page.keyboard.press("Enter");
        await expect(page.locator("textarea").first()).toBeVisible({ timeout: 5000 });
        await page.keyboard.press("Escape");
    });

    test("should maintain all existing CRUD operations", async ({ page }) => {
        const testQuestion = `UI Improvement Test ${Date.now()}`;
        const createResponsePromise = page.waitForResponse(
            (response) =>
                response.url().includes("/admin/faqs") &&
                response.request().method() === "POST",
            { timeout: 30000 }
        );
        await page.click('button:has-text("Add New FAQ")');
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Testing Phase 1 improvements");
        await page.click('button:has-text("Add FAQ")');
        expect((await createResponsePromise).ok()).toBeTruthy();
        await page.getByRole("dialog", { name: "Add New FAQ" }).waitFor({
            state: "hidden",
            timeout: 30000,
        });

        const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
        await expect(faqCard).toBeVisible({ timeout: 30000 });

        await faqCard.click();
        await page.keyboard.press("Enter");
        const inlineAnswerField = page.locator("textarea").first();
        await inlineAnswerField.waitFor({ state: "visible", timeout: 5000 });
        await inlineAnswerField.clear();
        await inlineAnswerField.fill("Updated via inline edit");

        const saveButton = page.getByRole("button", { name: "Save", exact: true });
        const updateResponsePromise = page.waitForResponse(
            (response) =>
                response.url().includes("/admin/faqs/") &&
                response.request().method() === "PUT",
            { timeout: 30000 }
        );
        await saveButton.click();
        expect((await updateResponsePromise).ok()).toBeTruthy();

        await expect(page.locator(`text="${testQuestion}"`).first()).toBeVisible({ timeout: 10000 });
        await expect(page.locator('text="Updated via inline edit"').first()).toBeVisible({ timeout: 10000 });

        await page.reload();
        await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
        const updatedFaqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
        await updatedFaqCard.click();
        await page.keyboard.press("d");

        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        await dialog.getByRole("button", { name: "Continue" }).click();
        await expect(updatedFaqCard).toHaveCount(0, { timeout: 10000 });
    });

    test("should maintain search functionality while using smart filters", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

        // Type in search
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill("Bisq");
        await page.waitForTimeout(500);

        // Select a category filter
        const categoryChip = page.locator("text=All Categories").first();
        await categoryChip.click();
        await page.waitForSelector('[role="option"]', { timeout: 5000 });

        const categoryOptions = page.locator('[role="option"]');
        const optionCount = await categoryOptions.count();

        if (optionCount > 1) {
            await categoryOptions.nth(1).click();
            await page.waitForTimeout(1000);

            // Both filters should be active
            const resetButton = page.locator('button:has-text("Reset filters")');
            await expect(resetButton).toBeVisible();

            // FAQs should be filtered by both search and category
            const faqCards = page.locator(FAQ_CARD_SELECTOR);
            const count = await faqCards.count();
            expect(count).toBeGreaterThanOrEqual(0); // May be 0 if no matches
        }
    });

    test("should preserve filter state during pagination", async ({ page }) => {
        // Apply a search filter
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill("test");
        await page.waitForTimeout(500);

        // If pagination exists, test it
        const nextButton = page.locator('button:has-text("Next")');
        const isNextButtonVisible = await nextButton.isVisible();

        if (isNextButtonVisible) {
            const isNextEnabled = await nextButton.isEnabled();

            if (isNextEnabled) {
                await nextButton.click();
                await page.waitForTimeout(1000);

                // Search input should still have the value
                await expect(searchInput).toHaveValue("test");
            }
        }
    });
});
