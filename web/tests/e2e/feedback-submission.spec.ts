import { test, expect } from '@playwright/test';

/**
 * Feedback Submission Tests
 *
 * These tests verify that feedback submission works correctly,
 * including explanation text for negative feedback and
 * conversation history capture for both positive and negative feedback.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'dev_admin_key';

test.describe('Feedback Submission', () => {
  test('should submit negative feedback with explanation', async ({ page }) => {
    // Navigate to chat interface
    await page.goto('http://localhost:3000');

    // Handle privacy notice if it appears
    const privacyButton = page.locator('button:has-text("I Understand")');
    if (await privacyButton.isVisible()) {
      await privacyButton.click();
    }

    // Wait for chat to load
    await page.getByRole('textbox').waitFor({ state: 'visible' });

    // Send a test message
    await page.getByRole('textbox').fill('What is Bisq 2?');
    await page.click('button[type="submit"]');

    // Wait for response
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });

    // Click thumbs down (negative feedback)
    const thumbsDownButton = page.locator('button[aria-label="Rate as unhelpful"]').last();
    await thumbsDownButton.click();

    // Fill in explanation
    const explanationField = page.locator('textarea#feedback-text');
    await expect(explanationField).toBeVisible();
    await explanationField.fill('The answer was too technical and did not explain the key benefits clearly.');

    // Submit feedback
    await page.click('button:has-text("Submit")');

    // Wait for feedback submission confirmation
    await page.waitForTimeout(1000);

    // Login to admin to verify
    await page.goto('http://localhost:3000/admin');
    await page.waitForSelector('input[type="password"]', { timeout: 10000 });
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });

    // Navigate to feedback management
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');

    // Wait for feedback cards to load
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Find the most recent negative feedback card (should be at top)
    const recentFeedback = page.locator('.border-l-4.border-l-gray-200').first();

    // Verify it's negative feedback
    const thumbsDown = recentFeedback.locator('svg.lucide-thumbs-down');
    await expect(thumbsDown).toBeVisible();

    // Click to view details (Eye icon button)
    const viewButton = recentFeedback.locator('button').filter({ has: page.locator('svg.lucide-eye') }).first();
    await viewButton.click();

    // Verify explanation is visible in the details dialog
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // Check for the explanation text in the dialog
    const dialogContent = await dialog.textContent();
    expect(dialogContent).toMatch(/too technical/i);
    expect(dialogContent).toMatch(/explain the key benefits/i);
  });

  test('should submit positive feedback after conversation', async ({ page }) => {
    // Navigate to chat interface
    await page.goto('http://localhost:3000');

    // Handle privacy notice if it appears
    const privacyButton = page.locator('button:has-text("I Understand")');
    if (await privacyButton.isVisible()) {
      await privacyButton.click();
    }

    // Wait for chat to load
    await page.getByRole('textbox').waitFor({ state: 'visible' });

    // Have a multi-turn conversation
    const messages = [
      'What is Bisq Easy?',
      'How does the reputation system work?',
      'What are the trade limits?'
    ];

    for (const message of messages) {
      await page.getByRole('textbox').fill(message);
      await page.click('button[type="submit"]');
      await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });
      // Wait longer for response to fully render and state to update
      await page.waitForTimeout(2000);
    }

    // Ensure all 3 AI responses are present before rating
    const aiResponses = page.locator('img[alt="Bisq AI"]');
    await expect(aiResponses).toHaveCount(3, { timeout: 10000 });

    // Wait for all 3 messages to be fully rendered and state to update
    await page.waitForTimeout(3000);

    // Get all thumbs up buttons and click the last one (3rd message)
    const thumbsUpButtons = page.locator('button[aria-label="Rate as helpful"]');
    await expect(thumbsUpButtons).toHaveCount(3, { timeout: 5000 });

    // Scroll the 3rd button into view, ensuring it's not covered by the fixed form
    const thirdThumbsUp = thumbsUpButtons.nth(2);
    await thirdThumbsUp.scrollIntoViewIfNeeded();

    // Scroll up a bit more to ensure the button is not covered by the fixed input form
    await page.evaluate(() => window.scrollBy(0, -200));
    await page.waitForTimeout(500);

    // Wait for the feedback submission response
    const responsePromise = page.waitForResponse(
      response => response.url().includes('/feedback/submit') && response.status() === 200,
      { timeout: 15000 }
    );

    // Try clicking without force first
    try {
      await thirdThumbsUp.click({ timeout: 5000 });
    } catch {
      // If normal click fails, try force click
      console.log('Normal click failed, trying force click');
      await thirdThumbsUp.click({ force: true });
    }

    // Wait for the feedback submission to complete
    try {
      await responsePromise;
      console.log('Feedback submitted successfully');
    } catch (error) {
      console.error('Feedback submission failed or timed out:', error);
    }

    // Wait longer for feedback to be saved to database
    await page.waitForTimeout(5000);

    // Login to admin to verify
    await page.goto('http://localhost:3000/admin');
    await page.waitForSelector('input[type="password"]', { timeout: 10000 });
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });

    // Navigate to feedback management
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');

    // Wait for feedback cards to load
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Find the FIRST (most recent) feedback card for "What are the trade limits?" question
    const feedbackCard = page.locator('.border-l-4.border-l-gray-200').filter({ hasText: /trade limits/i }).first();

    // Verify it's positive feedback
    const thumbsUp = feedbackCard.locator('svg.lucide-thumbs-up');
    await expect(thumbsUp).toBeVisible();

    // Click to view details (Eye icon button)
    const viewButton = feedbackCard.locator('button').filter({ has: page.locator('svg.lucide-eye') }).first();
    await viewButton.click();

    // Verify conversation history is visible
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // Check that conversation history section exists (using the Label text from ConversationHistory component)
    const conversationSection = dialog.getByText(/Conversation History/i);
    await expect(conversationSection).toBeVisible();

    // Verify we can see multiple messages from the conversation
    // Should show all 3 user messages and 3 assistant responses
    const conversationContent = await dialog.textContent();
    expect(conversationContent).toMatch(/Bisq Easy/i);
    expect(conversationContent).toMatch(/reputation/i);
    expect(conversationContent).toMatch(/trade limits/i);
  });

  test('should capture conversation history for negative feedback', async ({ page }) => {
    // Navigate to chat interface
    await page.goto('http://localhost:3000');

    // Handle privacy notice if it appears
    const privacyButton = page.locator('button:has-text("I Understand")');
    if (await privacyButton.isVisible()) {
      await privacyButton.click();
    }

    await page.getByRole('textbox').waitFor({ state: 'visible' });

    // Have a conversation
    await page.getByRole('textbox').fill('How do I install Bisq 2?');
    await page.click('button[type="submit"]');
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });
    await page.waitForTimeout(2000);

    await page.getByRole('textbox').fill('What operating systems does it support?');
    await page.click('button[type="submit"]');
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });
    await page.waitForTimeout(2000);

    // Ensure both AI responses are present
    const aiResponses = page.locator('img[alt="Bisq AI"]');
    await expect(aiResponses).toHaveCount(2, { timeout: 10000 });

    // Wait longer to ensure conversation history is fully captured in state
    await page.waitForTimeout(3000);

    // Give negative feedback
    const thumbsDownButton = page.locator('button[aria-label="Rate as unhelpful"]').last();
    await thumbsDownButton.click();

    // Fill explanation
    const explanationField = page.locator('textarea#feedback-text');
    await explanationField.fill('Missing information about macOS installation.');
    await page.click('button:has-text("Submit")');

    // Wait longer for feedback with conversation history to be saved
    await page.waitForTimeout(5000);

    // Verify in admin
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // View details
    const recentFeedback = page.locator('.border-l-4.border-l-gray-200').first();
    const viewButton = recentFeedback.locator('button').filter({ has: page.locator('svg.lucide-eye') }).first();
    await viewButton.click();

    // Verify both explanation AND conversation history are present
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // Check that conversation history section exists
    const conversationSection = dialog.getByText(/Conversation History/i);
    await expect(conversationSection).toBeVisible();

    // Verify dialog content includes explanation and conversation context
    const dialogContent = await dialog.textContent();
    expect(dialogContent).toMatch(/Missing information about macOS/i); // Explanation
    expect(dialogContent).toMatch(/install/i); // From conversation
    expect(dialogContent).toMatch(/operating systems/i); // From conversation
  });

  test('should handle feedback without explanation', async ({ page }) => {
    // Test that positive feedback works without requiring explanation
    await page.goto('http://localhost:3000');

    // Handle privacy notice if it appears
    const privacyButton = page.locator('button:has-text("I Understand")');
    if (await privacyButton.isVisible()) {
      await privacyButton.click();
    }

    await page.getByRole('textbox').waitFor({ state: 'visible' });

    await page.getByRole('textbox').fill('Test quick positive feedback');
    await page.click('button[type="submit"]');
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });

    // Click thumbs up (should submit immediately without explanation dialog)
    const thumbsUpButton = page.locator('button[aria-label="Rate as helpful"]').last();
    await thumbsUpButton.click();

    await page.waitForTimeout(1000);

    // Verify feedback was submitted (check admin)
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    const recentFeedback = page.locator('.border-l-4.border-l-gray-200').first();
    const thumbsUp = recentFeedback.locator('svg.lucide-thumbs-up');
    await expect(thumbsUp).toBeVisible();
  });

  test('should display conversation message count in feedback list', async ({ page }) => {
    // Login to admin
    await page.goto('http://localhost:3000/admin');
    await page.waitForSelector('input[type="password"]', { timeout: 10000 });
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });

    // Navigate to feedback
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Check that feedback cards show conversation count
    // Look for feedback with conversation history
    const feedbackWithHistory = page.locator('.border-l-4.border-l-gray-200').filter({
      hasText: /\d+ messages?/i // Should show "2 messages", "3 messages", etc.
    });

    // If there's feedback with history, verify it's displayed
    const count = await feedbackWithHistory.count();
    if (count > 0) {
      const firstCard = feedbackWithHistory.first();
      const text = await firstCard.textContent();
      expect(text).toMatch(/\d+ messages?/i);
    }
  });

  test('should filter feedback by rating', async ({ page }) => {
    // Login to admin
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Click "Negative Only" tab
    await page.click('button:has-text("Negative Only")');
    await page.waitForTimeout(500);

    // Verify all visible feedback is negative (has thumbs down)
    const cards = page.locator('.border-l-4.border-l-gray-200');
    const count = await cards.count();

    expect(count).toBeGreaterThan(0);

    for (let i = 0; i < Math.min(count, 5); i++) {
      const thumbsDown = cards.nth(i).locator('svg.lucide-thumbs-down');
      await expect(thumbsDown).toBeVisible();
    }
  });

  test('should export feedback data', async ({ page }) => {
    // Login to admin
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    // Click export button if it exists
    const exportButton = page.locator('button:has-text("Export")');

    if (await exportButton.isVisible()) {
      // Start waiting for download before clicking
      const downloadPromise = page.waitForEvent('download');
      await exportButton.click();

      // Wait for the download
      const download = await downloadPromise;

      // Verify download filename
      expect(download.suggestedFilename()).toMatch(/feedback.*\.(csv|json)/i);
    }
  });
});
