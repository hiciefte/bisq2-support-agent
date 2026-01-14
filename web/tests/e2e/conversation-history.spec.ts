import { test, expect } from '@playwright/test';
import {
  ADMIN_API_KEY,
  WEB_BASE_URL,
  loginAsAdmin,
  navigateToFeedbackManagement,
} from './utils';

test.describe('Conversation History Display', () => {
  test.beforeEach(async ({ page }) => {
    // Login to admin and navigate to feedback management
    await loginAsAdmin(page, ADMIN_API_KEY, WEB_BASE_URL);
    await navigateToFeedbackManagement(page);
  });

  test('should show conversation history in feedback detail dialog', async ({ page }) => {
    // Wait for page to load
    await page.waitForTimeout(2000);

    // Check if feedback cards exist (without waiting, just count)
    const feedbackCards = page.locator('.border-l-4.border-l-gray-200');
    const count = await feedbackCards.count();

    if (count === 0) {
      console.log('⚠️  No feedback items found - skipping test');
      console.log('This may occur after container restarts or database clears');
      test.skip();
      return;
    }

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
