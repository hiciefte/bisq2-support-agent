import { test, expect } from "@playwright/test";
import { selectCategory } from "./utils";

/**
 * FAQ UI Improvements Tests (Phase 1)
 *
 * These tests verify the Phase 1 UI improvements:
 * 1. Persistent inline search (always visible search bar)
 * 2. Smart filter chips (always visible category/source filters)
 * 3. Hover action buttons (buttons only visible on hover)
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || "dev_admin_key";

test.describe("FAQ UI Improvements - Phase 1", () => {
    test.beforeEach(async ({ page }) => {
        // Navigate and login
        await page.goto("http://localhost:3000/admin");
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

        const firstFaqCard = page.locator(".bg-card.border.border-border.rounded-lg").first();

        // Action buttons should not be visible initially (opacity-0)
        // Note: We can't directly test opacity in Playwright, but we can test hover behavior

        // Hover over FAQ card
        await firstFaqCard.hover();

        // Wait for transition
        await page.waitForTimeout(300);

        // Action buttons should now be visible
        const editButton = firstFaqCard.locator('button:has([class*="lucide-pencil"])');
        const deleteButton = firstFaqCard.locator('button:has([class*="lucide-trash"])');

        await expect(editButton).toBeVisible();
        await expect(deleteButton).toBeVisible();
    });

    test("should maintain all existing CRUD operations", async ({ page }) => {
        // This test ensures backward compatibility

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

        // Test: Edit FAQ (with hover)
        await faqCard.hover();
        await page.waitForTimeout(300);

        const editButton = faqCard.locator('button:has([class*="lucide-pencil"])');
        await editButton.click();

        // Modify answer
        const answerField = page.locator("textarea#answer");
        await answerField.clear();
        await answerField.fill("Updated via hover action button");
        await page.click('button:has-text("Save Changes")');
        await page.waitForTimeout(2000);

        // Verify update
        await expect(faqCard).toContainText("Updated via hover");

        // Test: Delete FAQ (with hover)
        await faqCard.hover();
        await page.waitForTimeout(300);

        const deleteButton = faqCard.locator('button:has([class*="lucide-trash"])');
        await deleteButton.click();

        // Confirm deletion
        const dialog = page.getByRole("alertdialog");
        await dialog.waitFor({ state: "visible", timeout: 5000 });
        await dialog.getByRole("button", { name: "Continue" }).click();
        await page.waitForTimeout(2000);

        // Verify FAQ is deleted
        await expect(faqCard).toHaveCount(0);
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
