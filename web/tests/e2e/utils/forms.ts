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

    // 2. Wait for command input to be visible (replaces arbitrary 300ms timeout)
    const commandInput = page.locator("[cmdk-input]");
    await commandInput.waitFor({ state: "visible" });

    // 3. Type the category name
    await commandInput.fill(category);

    // 4. Wait for filtered list to update (client-side operation, no network needed)
    // Wait for cmdk items to be visible (more robust than fixed delay)
    await page.waitForSelector("[cmdk-item]", { state: "visible", timeout: 1000 });

    // 5. Check if the category exists in the list
    const existingItem = page.locator(`[cmdk-item][data-value="${category.toLowerCase()}"]`);
    const itemExists = (await existingItem.count()) > 0;

    // 6. Either select existing item or create new one
    if (itemExists) {
        // Category exists - click it
        await existingItem.click();
    } else {
        // Category doesn't exist - press Enter to create
        await commandInput.press("Enter");
    }

    // 7. Wait for popover to close (indicates selection complete)
    // We wait for the command input to be hidden instead of checking for button visibility
    // because there are multiple comboboxes on the page (filter chips)
    await commandInput.waitFor({ state: "hidden" });
}
