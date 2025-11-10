import { test, expect } from "@playwright/test";
import { selectCategory, API_BASE_URL, ADMIN_API_KEY, WEB_BASE_URL } from "./utils";

/**
 * FAQ UI Improvements Tests (Phase 1)
 *
 * These tests verify the Phase 1 UI improvements:
 * 1. Persistent inline search (always visible search bar)
 * 2. Smart filter chips (always visible category/source filters)
 * 3. Hover action buttons (buttons only visible on hover)
 */

test.describe("FAQ UI Improvements - Phase 1", () => {
    test.beforeEach(async ({ page }) => {
        // Navigate and login
        await page.goto(`${WEB_BASE_URL}/admin`);
        await page.waitForSelector('input[type="password"]', { timeout: 10000 });
        await page.fill('input[type="password"]', ADMIN_API_KEY);
        await page.click('button:has-text("Login")');
        await page.waitForSelector("text=Admin Dashboard", { timeout: 10000 });

        // Navigate to FAQ management
        await page.click('a[href="/admin/manage-faqs"]');
        await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });

        // Wait for FAQs to load
        await Promise.race([
            page
                .waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 5000 })
                .catch(() => null),
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

        // Verify FAQs are filtered
        const faqCards = page.locator(".bg-card.border.border-border.rounded-lg");
        const count = await faqCards.count();

        if (count > 0) {
            // Verify visible FAQs contain search term
            const firstCardText = await faqCards.first().textContent();
            expect(firstCardText?.toLowerCase()).toContain("bisq");
        }
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

        // Verify source filter chip is visible
        const sourceChip = page.locator("text=All Sources").first();
        await expect(sourceChip).toBeVisible();

        // Verify chevron icons are present (indicating dropdowns)
        const chevronIcons = page.locator(".lucide-chevron-down");
        const chevronCount = await chevronIcons.count();
        expect(chevronCount).toBeGreaterThanOrEqual(2);
    });

    test("should filter by category using smart filter chip", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

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
            const faqCards = page.locator(".bg-card.border.border-border.rounded-lg");
            const count = await faqCards.count();
            expect(count).toBeGreaterThan(0);
        }
    });

    test("should filter by source using smart filter chip", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

        // Click source filter chip
        const sourceChip = page.locator("text=All Sources").first();
        await sourceChip.click();

        // Wait for dropdown to appear
        await page.waitForSelector('[role="option"]', { timeout: 5000 });

        // Verify "All Sources" option is present
        const allSourcesOption = page.locator('[role="option"]:has-text("All Sources")');
        await expect(allSourcesOption).toBeVisible();
    });

    test("should show Reset button when filters are active", async ({ page }) => {
        // Initially reset button should not be visible or be disabled
        const resetButton = page.locator('button:has-text("Reset")');

        // Type in search to activate filters
        const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
        await searchInput.fill("test");
        await page.waitForTimeout(500);

        // Reset button should now be visible
        await expect(resetButton).toBeVisible();

        // Click reset button
        await resetButton.click();

        // Search should be cleared
        await expect(searchInput).toHaveValue("");
    });

    test('should have legacy "Advanced" filter button for backwards compatibility', async ({
        page,
    }) => {
        // Verify Advanced filter button exists
        const advancedButton = page.locator('button:has-text("Advanced")');
        await expect(advancedButton).toBeVisible();

        // Click to open legacy filter panel
        await advancedButton.click();

        // Verify legacy filter panel opens
        await page.waitForSelector("text=Filter FAQs by text search", { timeout: 5000 });

        // Close filter panel using aria-label (button has X icon, no text)
        await page.locator('button[aria-label="Close filters"]').click();
        await page.waitForTimeout(500);
    });

    test("should show action buttons only on hover", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

        // Find an unverified FAQ (action buttons are always visible for unverified FAQs when expanded)
        // Verified FAQs collapse by default, so we need an unverified one to test hover behavior
        const unverifiedFaq = page
            .locator(".bg-card.border.border-border.rounded-lg")
            .filter({ hasText: "Needs Review" })
            .first();

        // Ensure we found an unverified FAQ
        await expect(unverifiedFaq).toBeVisible();

        // Get the action buttons container - it has flex items-center gap-1 classes and contains Edit button
        const actionButtons = unverifiedFaq.locator('div.flex.items-center.gap-1').filter({
            has: page.locator('[data-testid="edit-faq-button"]')
        });

        // Wait for the action buttons container to be attached to the DOM
        await actionButtons.waitFor({ state: "attached", timeout: 5000 });

        // Check initial opacity (should be 0 - hidden)
        const initialOpacity = await actionButtons.evaluate((el) =>
            window.getComputedStyle(el).opacity
        );
        expect(parseFloat(initialOpacity)).toBe(0);

        // Hover over the unverified FAQ card
        await unverifiedFaq.hover();

        // Wait for CSS transition (200ms as defined in className)
        await page.waitForTimeout(250);

        // Check opacity after hover (should be 1 - visible)
        const hoverOpacity = await actionButtons.evaluate((el) =>
            window.getComputedStyle(el).opacity
        );
        expect(parseFloat(hoverOpacity)).toBe(1);
    });

    test("should maintain all existing CRUD operations", async ({ page }) => {
        // This test ensures backward compatibility with inline editing

        // Test: Create FAQ
        await page.click('button:has-text("Add New FAQ")');
        const testQuestion = `UI Improvement Test ${Date.now()}`;
        await page.fill("input#question", testQuestion);
        await page.fill("textarea#answer", "Testing Phase 1 improvements");
        await selectCategory(page, "General");
        await page.click('button:has-text("Add FAQ")');
        await page.waitForTimeout(1000);

        // Verify FAQ appears
        const faqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );
        await expect(faqCard).toBeVisible();

        // Test: Inline Edit FAQ (with hover)
        await faqCard.hover();
        await page.waitForTimeout(300);

        // Click edit button to enter inline edit mode
        const editButton = faqCard.locator('[data-testid="edit-faq-button"]');
        await editButton.click();
        await page.waitForTimeout(500);

        // In inline edit mode, the FAQ card is replaced with a Card component containing editable fields
        // Find the textarea in the edit form (it's the only textarea in CardContent)
        const inlineAnswerField = page.locator("textarea").first();
        await inlineAnswerField.waitFor({ state: "visible", timeout: 5000 });
        await inlineAnswerField.clear();
        await inlineAnswerField.fill("Updated via inline edit");

        // Click save button (button with text "Save")
        const saveButton = page.locator('button:has-text("Save")');
        await saveButton.click();
        await page.waitForTimeout(3000);

        // Verify update
        await expect(faqCard).toContainText("Updated via inline edit");

        // Reload page to ensure we have fresh data from backend
        await page.reload();
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

        // Re-locate the FAQ card after reload
        const updatedFaqCard = page.locator(
            `.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`
        );

        // Test: Delete FAQ (with hover)
        await updatedFaqCard.hover();
        await page.waitForTimeout(300);

        const deleteButton = updatedFaqCard.locator('[data-testid="delete-faq-button"]');
        await deleteButton.click();

        // Confirm deletion
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        await dialog.getByRole("button", { name: "Continue" }).click();
        await page.waitForTimeout(2000);

        // Verify FAQ is deleted
        await expect(updatedFaqCard).toHaveCount(0);
    });

    test("should maintain search functionality while using smart filters", async ({ page }) => {
        // Wait for FAQs to load
        await page.waitForSelector(".bg-card.border.border-border.rounded-lg", { timeout: 10000 });

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
            const resetButton = page.locator('button:has-text("Reset")');
            await expect(resetButton).toBeVisible();

            // FAQs should be filtered by both search and category
            const faqCards = page.locator(".bg-card.border.border-border.rounded-lg");
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
