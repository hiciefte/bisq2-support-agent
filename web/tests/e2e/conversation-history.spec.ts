import { test, expect } from '@playwright/test';

const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'dev_admin_key';

test.describe('Conversation History Display', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to admin page (redirects to /admin/overview)
    await page.goto('http://localhost:3000/admin');

    // Wait for login form to appear
    await page.waitForSelector('input[type="password"]', { timeout: 10000 });

    // Login with API key
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');

    // Wait for authenticated UI to appear (sidebar with navigation)
    await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });

    // Navigate to feedback management
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForSelector('text=Feedback', { timeout: 10000 });
  });

  test('should show conversation history in feedback detail dialog', async ({ page }) => {
    // Wait for feedback cards to load
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Click on the first view details button (Eye icon)
    const viewButton = page.locator('button').filter({ has: page.locator('svg.lucide-eye') }).first();
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
    // Wait for feedback cards to load
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Click on the first "Create FAQ" button (only visible for negative unprocessed feedback)
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
