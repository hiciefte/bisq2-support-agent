/**
 * Form interaction utilities for E2E tests.
 *
 * This module provides reusable helpers for interacting with complex form components
 * like comboboxes, dropdowns, and other custom UI elements.
 */

import { type Page } from "@playwright/test";

/**
 * Select a category from the combobox in FAQ management dialogs.
 *
 * This helper handles the Radix UI Combobox pattern (Popover + Command component)
 * which combines searchable input with selectable items.
 *
 * @param page - Playwright page object
 * @param category - Category name to select or create
 *
 * @example
 * ```typescript
 * await selectCategory(page, "General");
 * await selectCategory(page, "New Category"); // Creates if doesn't exist
 * ```
 */
export async function selectCategory(page: Page, category: string) {
    // 1. Open the combobox popover
    await page.click('button[role="combobox"]:has-text("Select category")');
    await page.waitForTimeout(300);

    // 2. Get reference to the command input (uses cmdk library)
    const commandInput = page.locator("[cmdk-input]");

    // 3. Type the category name
    await commandInput.fill(category);
    await page.waitForTimeout(200);

    // 4. Check if the category exists in the list
    const existingItem = page.locator(`[cmdk-item][data-value="${category.toLowerCase()}"]`);
    const itemExists = (await existingItem.count()) > 0;

    // 5. Either select existing item or create new one
    if (itemExists) {
        // Category exists - click it
        await existingItem.click();
    } else {
        // Category doesn't exist - press Enter to create
        await commandInput.press("Enter");
    }

    // 6. Wait for selection to complete
    await page.waitForTimeout(200);
}
