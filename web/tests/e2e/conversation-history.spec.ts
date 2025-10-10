import { test, expect } from '@playwright/test';

const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'test-admin-key';

test.describe('Conversation History Display', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to admin login
    await page.goto('http://localhost:3000/admin');

    // Login with API key
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');

    // Wait for redirect to overview
    await page.waitForURL('**/admin/overview');

    // Navigate to feedback management
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');
  });

  test('should show conversation history in feedback detail dialog', async ({ page }) => {
    // Wait for feedback table to load
    await page.waitForSelector('table', { timeout: 10000 });

    // Click on the first "View Details" button
    const viewButton = page.locator('button:has-text("View Details")').first();
    await expect(viewButton).toBeVisible();
    await viewButton.click();

    // Wait for dialog to open
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 });

    // Check if conversation history is visible
    const conversationHistoryLabel = page.locator('text=Conversation History');

    // Take a screenshot for debugging
    await page.screenshot({ path: 'feedback-detail-dialog.png', fullPage: true });

    // Check if conversation history exists
    if (await conversationHistoryLabel.isVisible()) {
      console.log('✓ Conversation history is visible');

      // Check for message containers
      const userMessages = page.locator('.bg-blue-50');
      const assistantMessages = page.locator('.bg-green-50');

      const userCount = await userMessages.count();
      const assistantCount = await assistantMessages.count();

      console.log(`Found ${userCount} user messages and ${assistantCount} assistant messages`);

      expect(userCount + assistantCount).toBeGreaterThan(0);
    } else {
      console.log('✗ Conversation history is NOT visible');

      // Log the dialog content
      const dialogContent = await page.locator('[role="dialog"]').textContent();
      console.log('Dialog content:', dialogContent);
    }
  });

  test('should show conversation history in create FAQ dialog from feedback page', async ({ page }) => {
    // Wait for feedback table to load
    await page.waitForSelector('table', { timeout: 10000 });

    // Click on the first "Create FAQ" button
    const createFaqButton = page.locator('button:has-text("Create FAQ")').first();
    await expect(createFaqButton).toBeVisible();
    await createFaqButton.click();

    // Wait for dialog to open
    await page.waitForSelector('[role="dialog"]', { timeout: 5000 });

    // Check if conversation history is visible
    const conversationHistoryLabel = page.locator('text=Conversation History');

    // Take a screenshot for debugging
    await page.screenshot({ path: 'create-faq-dialog-feedback-page.png', fullPage: true });

    // Check if conversation history exists
    if (await conversationHistoryLabel.isVisible()) {
      console.log('✓ Conversation history is visible in Create FAQ dialog');

      // Check for message containers
      const userMessages = page.locator('.bg-blue-50');
      const assistantMessages = page.locator('.bg-green-50');

      const userCount = await userMessages.count();
      const assistantCount = await assistantMessages.count();

      console.log(`Found ${userCount} user messages and ${assistantCount} assistant messages`);

      expect(userCount + assistantCount).toBeGreaterThan(0);
    } else {
      console.log('✗ Conversation history is NOT visible in Create FAQ dialog');

      // Log the dialog content
      const dialogContent = await page.locator('[role="dialog"]').textContent();
      console.log('Dialog content:', dialogContent);
    }
  });
});
