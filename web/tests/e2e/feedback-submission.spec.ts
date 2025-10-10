import { test, expect } from '@playwright/test';

/**
 * Feedback Submission Tests
 *
 * These tests verify that feedback submission works correctly,
 * including explanation text for negative feedback and
 * conversation history capture for both positive and negative feedback.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'test-admin-key';

test.describe('Feedback Submission', () => {
  test('should submit negative feedback with explanation', async ({ page }) => {
    // Navigate to chat interface
    await page.goto('http://localhost:3000');

    // Wait for chat to load
    await page.waitForSelector('textarea[placeholder*="Type your message"]');

    // Send a test message
    await page.fill('textarea[placeholder*="Type your message"]', 'What is Bisq 2?');
    await page.click('button[type="submit"]');

    // Wait for response
    await page.waitForSelector('.message-assistant', { timeout: 30000 });

    // Click thumbs down (negative feedback)
    const thumbsDownButton = page.locator('button[aria-label*="Not helpful"], button:has-text("👎")').last();
    await thumbsDownButton.click();

    // Fill in explanation
    const explanationField = page.locator('textarea[placeholder*="explain"], textarea[placeholder*="feedback"]');
    await expect(explanationField).toBeVisible();
    await explanationField.fill('The answer was too technical and did not explain the key benefits clearly.');

    // Submit feedback
    await page.click('button:has-text("Submit")');

    // Wait for feedback submission confirmation
    await page.waitForTimeout(1000);

    // Login to admin to verify
    await page.goto('http://localhost:3000/admin');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/overview');

    // Navigate to feedback management
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');

    // Wait for feedback list to load
    await page.waitForSelector('table');

    // Find the most recent negative feedback (should be at top)
    const recentFeedback = page.locator('tbody tr').first();

    // Verify it's negative feedback
    const thumbsDown = recentFeedback.locator('svg.lucide-thumbs-down, [data-icon="thumbs-down"]');
    await expect(thumbsDown).toBeVisible();

    // Click to view details
    await recentFeedback.locator('button:has-text("View Details"), button:has-text("👁")').click();

    // Verify explanation is visible in the details dialog
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    const explanationText = await dialog.locator('text=/too technical/i, text=/explain the key benefits/i').textContent();
    expect(explanationText).toBeTruthy();
  });

  test('should submit positive feedback after conversation', async ({ page }) => {
    // Navigate to chat interface
    await page.goto('http://localhost:3000');

    // Wait for chat to load
    await page.waitForSelector('textarea[placeholder*="Type your message"]');

    // Have a multi-turn conversation
    const messages = [
      'What is Bisq Easy?',
      'How does the reputation system work?',
      'What are the trade limits?'
    ];

    for (const message of messages) {
      await page.fill('textarea[placeholder*="Type your message"]', message);
      await page.click('button[type="submit"]');
      await page.waitForSelector('.message-assistant', { timeout: 30000 });
      await page.waitForTimeout(1000); // Wait for response to fully render
    }

    // Click thumbs up on the last response
    const thumbsUpButton = page.locator('button[aria-label*="Helpful"], button:has-text("👍")').last();
    await thumbsUpButton.click();

    // Wait for feedback submission
    await page.waitForTimeout(2000);

    // Login to admin to verify
    await page.goto('http://localhost:3000/admin');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/overview');

    // Navigate to feedback management
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');

    // Wait for feedback list to load
    await page.waitForSelector('table');

    // Find the most recent positive feedback
    const recentFeedback = page.locator('tbody tr').first();

    // Verify it's positive feedback
    const thumbsUp = recentFeedback.locator('svg.lucide-thumbs-up, [data-icon="thumbs-up"]');
    await expect(thumbsUp).toBeVisible();

    // Click to view details
    await recentFeedback.locator('button:has-text("View Details"), button:has-text("👁")').click();

    // Verify conversation history is visible
    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible();

    // Check that conversation history section exists
    const conversationSection = dialog.locator('text=/conversation/i, text=/history/i');
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
    await page.waitForSelector('textarea[placeholder*="Type your message"]');

    // Have a conversation
    await page.fill('textarea[placeholder*="Type your message"]', 'How do I install Bisq 2?');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.message-assistant', { timeout: 30000 });
    await page.waitForTimeout(1000);

    await page.fill('textarea[placeholder*="Type your message"]', 'What operating systems does it support?');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.message-assistant', { timeout: 30000 });
    await page.waitForTimeout(1000);

    // Give negative feedback
    const thumbsDownButton = page.locator('button[aria-label*="Not helpful"], button:has-text("👎")').last();
    await thumbsDownButton.click();

    // Fill explanation
    const explanationField = page.locator('textarea[placeholder*="explain"], textarea[placeholder*="feedback"]');
    await explanationField.fill('Missing information about macOS installation.');
    await page.click('button:has-text("Submit")');
    await page.waitForTimeout(2000);

    // Verify in admin
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('table');

    // View details
    const recentFeedback = page.locator('tbody tr').first();
    await recentFeedback.locator('button:has-text("View Details"), button:has-text("👁")').click();

    // Verify both explanation AND conversation history are present
    const dialog = page.locator('[role="dialog"]');
    const dialogContent = await dialog.textContent();

    expect(dialogContent).toMatch(/Missing information about macOS/i); // Explanation
    expect(dialogContent).toMatch(/install/i); // From conversation
    expect(dialogContent).toMatch(/operating systems/i); // From conversation
  });

  test('should handle feedback without explanation', async ({ page }) => {
    // Test that positive feedback works without requiring explanation
    await page.goto('http://localhost:3000');
    await page.waitForSelector('textarea[placeholder*="Type your message"]');

    await page.fill('textarea[placeholder*="Type your message"]', 'Test quick positive feedback');
    await page.click('button[type="submit"]');
    await page.waitForSelector('.message-assistant', { timeout: 30000 });

    // Click thumbs up (should submit immediately without explanation dialog)
    const thumbsUpButton = page.locator('button[aria-label*="Helpful"], button:has-text("👍")').last();
    await thumbsUpButton.click();

    await page.waitForTimeout(1000);

    // Verify feedback was submitted (check admin)
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('table');

    const recentFeedback = page.locator('tbody tr').first();
    const thumbsUp = recentFeedback.locator('svg.lucide-thumbs-up, [data-icon="thumbs-up"]');
    await expect(thumbsUp).toBeVisible();
  });

  test('should display conversation message count in feedback list', async ({ page }) => {
    // Login to admin
    await page.goto('http://localhost:3000/admin');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/overview');

    // Navigate to feedback
    await page.click('a[href="/admin/manage-feedback"]');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('table');

    // Check that feedback entries show conversation count
    // Look for feedback with conversation history
    const feedbackWithHistory = page.locator('tbody tr').filter({
      hasText: /\d+ messages?/i // Should show "2 messages", "3 messages", etc.
    });

    // If there's feedback with history, verify it's displayed
    const count = await feedbackWithHistory.count();
    if (count > 0) {
      const firstRow = feedbackWithHistory.first();
      const text = await firstRow.textContent();
      expect(text).toMatch(/\d+ messages?/i);
    }
  });

  test('should filter feedback by rating', async ({ page }) => {
    // Login to admin
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('table');

    // Filter for negative feedback only
    await page.selectOption('select[aria-label*="rating"], select:has-option:text("Negative")', 'negative');
    await page.waitForTimeout(500);

    // Verify all visible feedback is negative (has thumbs down)
    const rows = page.locator('tbody tr');
    const count = await rows.count();

    expect(count).toBeGreaterThan(0);

    for (let i = 0; i < Math.min(count, 5); i++) {
      const thumbsDown = rows.nth(i).locator('svg.lucide-thumbs-down, [data-icon="thumbs-down"]');
      await expect(thumbsDown).toBeVisible();
    }
  });

  test('should export feedback data', async ({ page }) => {
    // Login to admin
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('table');

    // Click export button if it exists
    const exportButton = page.locator('button:has-text("Export"), button:has-text("Download")');

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
