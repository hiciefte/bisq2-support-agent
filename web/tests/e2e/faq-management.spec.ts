import { test, expect } from '@playwright/test';

/**
 * FAQ Management Tests
 *
 * These tests verify that FAQ CRUD operations work correctly,
 * particularly focusing on the permission issues that cause
 * FAQ deletion to fail after container restarts.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'test-admin-key';

test.describe('FAQ Management', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to admin login
    await page.goto('http://localhost:3000/admin');

    // Login with admin API key
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');

    // Wait for redirect to dashboard
    await page.waitForURL('**/admin/dashboard');

    // Navigate to FAQ management
    await page.click('a[href="/admin/manage-faqs"]');
    await page.waitForURL('**/admin/manage-faqs');
  });

  test('should display existing FAQs', async ({ page }) => {
    // Wait for FAQs to load
    await page.waitForSelector('table');

    // Verify table has rows
    const rows = await page.locator('tbody tr').count();
    expect(rows).toBeGreaterThan(0);
  });

  test('should create a new FAQ', async ({ page }) => {
    // Click "Create FAQ" button
    await page.click('button:has-text("Create FAQ")');

    // Fill in the form
    await page.fill('textarea[name="question"]', 'Test FAQ Question for E2E');
    await page.fill('textarea[name="answer"]', 'Test FAQ Answer for E2E testing');
    await page.selectOption('select[name="category"]', 'General');

    // Submit form
    await page.click('button:has-text("Create")');

    // Wait for success message or FAQ list to update
    await page.waitForTimeout(1000);

    // Verify FAQ appears in the list
    const faqText = await page.locator('tbody tr').filter({ hasText: 'Test FAQ Question for E2E' }).textContent();
    expect(faqText).toContain('Test FAQ Question for E2E');
  });

  test('should edit an existing FAQ', async ({ page }) => {
    // Find and click edit button on first FAQ
    const editButton = page.locator('tbody tr').first().locator('button:has-text("Edit")');
    await editButton.click();

    // Modify the answer
    const answerField = page.locator('textarea[name="answer"]');
    await answerField.clear();
    await answerField.fill('Updated answer via E2E test');

    // Save changes
    await page.click('button:has-text("Save")');

    // Wait for update
    await page.waitForTimeout(1000);

    // Verify change persisted
    await page.reload();
    await page.waitForSelector('table');
    const updatedText = await page.locator('tbody tr').first().textContent();
    expect(updatedText).toContain('Updated answer');
  });

  test('should delete a FAQ (CRITICAL: Tests permission issue)', async ({ page }) => {
    // Create a test FAQ to delete
    await page.click('button:has-text("Create FAQ")');
    await page.fill('textarea[name="question"]', 'FAQ to be deleted');
    await page.fill('textarea[name="answer"]', 'This FAQ will be deleted');
    await page.selectOption('select[name="category"]', 'General');
    await page.click('button:has-text("Create")');
    await page.waitForTimeout(1000);

    // Find the newly created FAQ
    const faqRow = page.locator('tbody tr').filter({ hasText: 'FAQ to be deleted' });

    // Click delete button
    const deleteButton = faqRow.locator('button:has-text("Delete")');
    await deleteButton.click();

    // Confirm deletion in dialog
    await page.click('button:has-text("Confirm")');

    // Wait for deletion to complete
    await page.waitForTimeout(1000);

    // Verify FAQ is removed from list
    const deletedFaq = page.locator('tbody tr').filter({ hasText: 'FAQ to be deleted' });
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
    await page.waitForSelector('table');

    // Select a category filter
    await page.selectOption('select[aria-label="Filter by category"]', 'General');

    // Wait for filter to apply
    await page.waitForTimeout(500);

    // Verify only General FAQs are shown
    const rows = page.locator('tbody tr');
    const count = await rows.count();

    for (let i = 0; i < count; i++) {
      const categoryBadge = rows.nth(i).locator('span:has-text("General")');
      await expect(categoryBadge).toBeVisible();
    }
  });

  test('should search FAQs by text', async ({ page }) => {
    // Wait for FAQs to load
    await page.waitForSelector('table');

    // Enter search term
    await page.fill('input[placeholder*="Search"]', 'Bisq');

    // Wait for search to apply
    await page.waitForTimeout(500);

    // Verify all visible FAQs contain search term
    const rows = page.locator('tbody tr');
    const count = await rows.count();

    expect(count).toBeGreaterThan(0);

    for (let i = 0; i < Math.min(count, 5); i++) {
      const text = await rows.nth(i).textContent();
      expect(text?.toLowerCase()).toMatch(/bisq/i);
    }
  });

  test('should verify FAQ deletion persists after page reload', async ({ page }) => {
    // Create a test FAQ
    await page.click('button:has-text("Create FAQ")');
    const testQuestion = `Persistence test ${Date.now()}`;
    await page.fill('textarea[name="question"]', testQuestion);
    await page.fill('textarea[name="answer"]', 'Testing persistence');
    await page.selectOption('select[name="category"]', 'General');
    await page.click('button:has-text("Create")');
    await page.waitForTimeout(1000);

    // Delete it
    const faqRow = page.locator('tbody tr').filter({ hasText: testQuestion });
    await faqRow.locator('button:has-text("Delete")').click();
    await page.click('button:has-text("Confirm")');
    await page.waitForTimeout(1000);

    // Reload page
    await page.reload();
    await page.waitForSelector('table');

    // Verify FAQ is still gone (tests that deletion was persisted to disk)
    const deletedFaq = page.locator('tbody tr').filter({ hasText: testQuestion });
    await expect(deletedFaq).toHaveCount(0);
  });

  test('should handle concurrent FAQ operations', async ({ page, context }) => {
    // Open second admin page
    const page2 = await context.newPage();
    await page2.goto('http://localhost:3000/admin');
    await page2.fill('input[type="password"]', ADMIN_API_KEY);
    await page2.click('button:has-text("Login")');
    await page2.waitForURL('**/admin/dashboard');
    await page2.click('a[href="/admin/manage-faqs"]');
    await page2.waitForURL('**/admin/manage-faqs');

    // Create FAQ on first page
    await page.click('button:has-text("Create FAQ")');
    const testQuestion = `Concurrent test ${Date.now()}`;
    await page.fill('textarea[name="question"]', testQuestion);
    await page.fill('textarea[name="answer"]', 'Testing concurrent access');
    await page.selectOption('select[name="category"]', 'General');
    await page.click('button:has-text("Create")');
    await page.waitForTimeout(1000);

    // Refresh second page and verify FAQ appears
    await page2.reload();
    await page2.waitForSelector('table');
    const faqOnPage2 = page2.locator('tbody tr').filter({ hasText: testQuestion });
    await expect(faqOnPage2).toBeVisible();

    // Cleanup
    await page2.close();
  });
});
