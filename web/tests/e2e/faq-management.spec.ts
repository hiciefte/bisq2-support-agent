import { test, expect } from '@playwright/test';

/**
 * FAQ Management Tests
 *
 * These tests verify that FAQ CRUD operations work correctly,
 * particularly focusing on the permission issues that cause
 * FAQ deletion to fail after container restarts.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'dev_admin_key';

test.describe('FAQ Management', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to admin page (redirects to /admin/overview)
    await page.goto('http://localhost:3000/admin');

    // Wait for login form to appear
    await page.waitForSelector('input[type="password"]', { timeout: 10000 });

    // Login with admin API key
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');

    // Wait for authenticated UI to appear (sidebar with navigation)
    await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });

    // Navigate to FAQ management
    await page.click('a[href="/admin/manage-faqs"]');
    await page.waitForSelector('text=FAQ', { timeout: 10000 });
  });

  test('should display existing FAQs', async ({ page }) => {
    // Wait for FAQ cards to load
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg', { timeout: 10000 });

    // Verify FAQ cards exist
    const faqCards = await page.locator('.bg-card.border.border-border.rounded-lg').count();
    expect(faqCards).toBeGreaterThan(0);
  });

  test('should create a new FAQ', async ({ page }) => {
    // Click "Add New FAQ" button
    await page.click('button:has-text("Add New FAQ")');

    // Fill in the form with unique question
    const testQuestion = `Test FAQ Question ${Date.now()}`;
    await page.fill('input#question', testQuestion);
    await page.fill('textarea#answer', 'Test FAQ Answer for E2E testing');
    await page.fill('input#category', 'General');

    // Submit form
    await page.click('button:has-text("Add FAQ")');

    // Wait for FAQ list to update
    await page.waitForTimeout(1000);

    // Verify FAQ appears in the list
    const faqCard = page.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await expect(faqCard).toBeVisible();
  });

  test('should edit an existing FAQ', async ({ page }) => {
    // Find and click edit button on first FAQ card
    const firstFaqCard = page.locator('.bg-card.border.border-border.rounded-lg').first();
    const editButton = firstFaqCard.locator('button').first(); // Pencil icon button
    await editButton.click();

    // Modify the answer
    const answerField = page.locator('textarea#answer');
    await answerField.clear();
    await answerField.fill('Updated answer via E2E test');

    // Save changes
    await page.click('button:has-text("Save Changes")');

    // Wait for update
    await page.waitForTimeout(1000);

    // Verify change persisted
    await page.reload();
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg');
    const updatedCard = await page.locator('.bg-card.border.border-border.rounded-lg').first().textContent();
    expect(updatedCard).toContain('Updated answer');
  });

  test('should delete a FAQ (CRITICAL: Tests permission issue)', async ({ page }) => {
    // Create a test FAQ to delete
    await page.click('button:has-text("Add New FAQ")');
    await page.fill('input#question', 'FAQ to be deleted');
    await page.fill('textarea#answer', 'This FAQ will be deleted');
    await page.fill('input#category', 'General');
    await page.click('button:has-text("Add FAQ")');
    await page.waitForTimeout(1000);

    // Find the newly created FAQ card
    const faqCard = page.locator('.bg-card.border.border-border.rounded-lg:has-text("FAQ to be deleted")');

    // Click delete button (second button, Trash2 icon)
    const deleteButton = faqCard.locator('button').nth(1);
    await deleteButton.click();

    // Confirm deletion in dialog
    await page.click('button:has-text("Continue")');

    // Wait for deletion to complete
    await page.waitForTimeout(1000);

    // Verify FAQ is removed from list
    const deletedFaq = page.locator('.bg-card.border.border-border.rounded-lg:has-text("FAQ to be deleted")');
    await expect(deletedFaq).toHaveCount(0);

    // CRITICAL: Verify no permission errors in console
    const logs = await page.evaluate(() => {
      // @ts-ignore
      return window.consoleErrors || [];
    });
    const hasPermissionError = logs.some((log: string) =>
      log.includes('Permission denied') || log.includes('EACCES')
    );
    expect(hasPermissionError).toBe(false);
  });

  test('should filter FAQs by category', async ({ page }) => {
    // Wait for FAQs to load
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg');

    // Open filters panel
    await page.click('button:has-text("Filters")');
    await page.waitForSelector('text=Filter FAQs by text search');

    // Click on first available category badge to filter
    // Badge components have cursor-pointer class and are clickable
    const categoryBadges = page.locator('.cursor-pointer').filter({ hasText: /.+/ });
    const firstBadge = categoryBadges.first();
    await firstBadge.waitFor({ state: 'visible' });
    await firstBadge.click();

    // Wait for filter to apply
    await page.waitForTimeout(1000);

    // Verify FAQs are filtered
    const faqCards = page.locator('.bg-card.border.border-border.rounded-lg');
    const count = await faqCards.count();
    expect(count).toBeGreaterThan(0);
  });

  test('should search FAQs by text', async ({ page }) => {
    // Wait for FAQs to load
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg');

    // Open filters panel
    await page.click('button:has-text("Filters")');

    // Enter search term
    await page.fill('input#search', 'Bisq');

    // Wait for search to apply
    await page.waitForTimeout(1000);

    // Verify all visible FAQs contain search term
    const faqCards = page.locator('.bg-card.border.border-border.rounded-lg');
    const count = await faqCards.count();

    expect(count).toBeGreaterThan(0);

    for (let i = 0; i < Math.min(count, 5); i++) {
      const text = await faqCards.nth(i).textContent();
      expect(text?.toLowerCase()).toMatch(/bisq/i);
    }
  });

  test('should verify FAQ deletion persists after page reload', async ({ page }) => {
    // Create a test FAQ
    await page.click('button:has-text("Add New FAQ")');
    const testQuestion = `Persistence test ${Date.now()}`;
    await page.fill('input#question', testQuestion);
    await page.fill('textarea#answer', 'Testing persistence');
    await page.fill('input#category', 'General');
    await page.click('button:has-text("Add FAQ")');
    await page.waitForTimeout(1000);

    // Delete it
    const faqCard = page.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await faqCard.locator('button').nth(1).click(); // Delete button
    await page.click('button:has-text("Continue")');
    await page.waitForTimeout(1000);

    // Reload page
    await page.reload();
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg');

    // Verify FAQ is still gone (tests that deletion was persisted to disk)
    const deletedFaq = page.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await expect(deletedFaq).toHaveCount(0);
  });

  test('should handle concurrent FAQ operations', async ({ page, context }) => {
    // Open second admin page in same context (shares cookies)
    const page2 = await context.newPage();
    await page2.goto('http://localhost:3000/admin');

    // Since we share the browser context, we should already be authenticated
    // Wait for the authenticated UI to appear (will redirect to /admin/overview)
    await page2.waitForSelector('text=Admin Dashboard', { timeout: 10000 });
    await page2.click('a[href="/admin/manage-faqs"]');
    await page2.waitForSelector('text=FAQ', { timeout: 10000 });

    // Create FAQ on first page
    await page.click('button:has-text("Add New FAQ")');
    const testQuestion = `Concurrent test ${Date.now()}`;
    await page.fill('input#question', testQuestion);
    await page.fill('textarea#answer', 'Testing concurrent access');
    await page.fill('input#category', 'General');
    await page.click('button:has-text("Add FAQ")');
    await page.waitForTimeout(1000);

    // Refresh second page and verify FAQ appears
    await page2.reload();
    await page2.waitForSelector('.bg-card.border.border-border.rounded-lg');
    const faqOnPage2 = page2.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await expect(faqOnPage2).toBeVisible();

    // Cleanup
    await page2.close();
  });
});
