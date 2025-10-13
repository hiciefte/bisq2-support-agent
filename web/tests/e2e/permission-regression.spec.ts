import { test, expect } from '@playwright/test';
import { exec } from 'child_process';
import { promisify } from 'util';

const execAsync = promisify(exec);

/**
 * Permission Regression Tests
 *
 * These tests specifically check for the file permission issues
 * that keep reappearing after container restarts.
 *
 * CRITICAL: These tests verify that FAQ deletion and other file
 * operations continue to work after container restarts.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';
const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'dev_admin_key';

test.describe('Permission Regression Tests', () => {
  test.skip(process.env.CI === 'true', 'Container restart tests only run locally');

  test('FAQ deletion should work after container restart', async ({ page }) => {
    // Step 1: Create a test FAQ
    await page.goto('http://localhost:3000/admin');
    await page.waitForSelector('input[type="password"]', { timeout: 10000 });
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });
    await page.click('a[href="/admin/manage-faqs"]');
    await page.waitForSelector('text=FAQ', { timeout: 10000 });

    await page.click('button:has-text("Add New FAQ")');
    const testQuestion = `Permission test ${Date.now()}`;
    await page.fill('input#question', testQuestion);
    await page.fill('textarea#answer', 'Testing permissions after restart');
    await page.fill('input#category', 'General');
    await page.click('button:has-text("Add FAQ")');
    await page.waitForTimeout(1000);

    // Step 2: Restart API container
    console.log('Restarting API container...');
    try {
      await execAsync('docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml restart api');
      // Wait for API to be healthy (longer timeout for RAG initialization)
      await page.waitForTimeout(20000);
    } catch (error) {
      console.error('Failed to restart container:', error);
      throw error;
    }

    // Step 3: Refresh page and try to delete the FAQ
    await page.reload();
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg', { timeout: 30000 });

    const faqCard = page.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await expect(faqCard).toBeVisible();

    const deleteButton = faqCard.locator('button').nth(1); // Second button is Trash2 icon
    await deleteButton.click();
    await page.click('button:has-text("Continue")');
    await page.waitForTimeout(1000);

    // Step 4: Verify deletion succeeded
    const deletedFaq = page.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await expect(deletedFaq).toHaveCount(0);

    // Step 5: Verify deletion persisted (reload page)
    await page.reload();
    await page.waitForSelector('.bg-card.border.border-border.rounded-lg', { timeout: 10000 });
    await expect(deletedFaq).toHaveCount(0);

    // Step 6: Check API logs for permission errors
    const { stdout: logs } = await execAsync(
      'docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml logs api --tail=50'
    );

    const hasPermissionError = logs.includes('Permission denied') || logs.includes('EACCES');
    if (hasPermissionError) {
      console.error('Permission errors found in logs:', logs);
    }
    expect(hasPermissionError).toBe(false);
  });

  test('Feedback submission should work after container restart', async ({ page }) => {
    // Step 1: Restart API container
    console.log('Restarting API container...');
    await execAsync('docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml restart api');
    await page.waitForTimeout(20000);

    // Step 2: Submit feedback
    await page.goto('http://localhost:3000');

    // Handle privacy notice if it appears
    const privacyButton = page.locator('button:has-text("I Understand")');
    if (await privacyButton.isVisible()) {
      await privacyButton.click();
    }

    await page.getByRole('textbox').waitFor({ state: 'visible' });

    await page.getByRole('textbox').fill('Permission test message');
    await page.click('button[type="submit"]');
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });

    const thumbsUpButton = page.locator('button[aria-label="Rate as helpful"]').last();
    await thumbsUpButton.click();
    await page.waitForTimeout(2000);

    // Step 3: Verify feedback was saved
    await page.goto('http://localhost:3000/admin/manage-feedback');
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForURL('**/admin/manage-feedback');
    await page.waitForSelector('.border-l-4.border-l-gray-200', { timeout: 10000 });

    const recentFeedback = page.locator('.border-l-4.border-l-gray-200').first();
    const thumbsUp = recentFeedback.locator('svg.lucide-thumbs-up');
    await expect(thumbsUp).toBeVisible();

    // Step 4: Check for permission errors
    const { stdout: logs } = await execAsync(
      'docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml logs api --tail=50'
    );

    expect(logs).not.toContain('Permission denied');
    expect(logs).not.toContain('[Errno 13]');
  });

  test('File ownership should be correct after container start', async ({ page }) => {
    // Check file permissions via API container
    const { stdout } = await execAsync(
      'docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml exec -T api ls -la /data/'
    );

    console.log('File permissions:', stdout);

    // Verify critical files are owned by bisq-support (UID 1001)
    const lines = stdout.split('\n');
    const faqFile = lines.find(line => line.includes('extracted_faq.jsonl'));
    const feedbackDb = lines.find(line => line.includes('feedback.db'));

    if (faqFile) {
      // Should show bisq-support or 1001 as owner
      expect(faqFile).toMatch(/bisq-support|1001/);
    }

    if (feedbackDb) {
      expect(feedbackDb).toMatch(/bisq-support|1001/);
    }
  });

  test('Multiple container restarts should not break permissions', async ({ page }) => {
    // Set longer timeout for this test (3 restarts + operations)
    test.setTimeout(120000); // 2 minutes

    // Restart container 3 times
    for (let i = 1; i <= 3; i++) {
      console.log(`Container restart ${i}/3...`);
      await execAsync('docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml restart api');
      await page.waitForTimeout(20000);
    }

    // Try to create and delete FAQ
    await page.goto('http://localhost:3000/admin/manage-faqs');
    await page.waitForSelector('input[type="password"]', { timeout: 15000 });
    await page.fill('input[type="password"]', ADMIN_API_KEY);
    await page.click('button:has-text("Login")');
    await page.waitForSelector('text=Admin Dashboard', { timeout: 15000 });
    await page.waitForSelector('text=FAQ', { timeout: 30000 });

    // Create FAQ
    await page.click('button:has-text("Add New FAQ")');
    const testQuestion = `Multi-restart test ${Date.now()}`;
    await page.fill('input#question', testQuestion);
    await page.fill('textarea#answer', 'Testing after multiple restarts');
    await page.fill('input#category', 'General');
    await page.click('button:has-text("Add FAQ")');
    await page.waitForTimeout(1000);

    // Delete FAQ
    const faqCard = page.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    const deleteButton = faqCard.locator('button').nth(1); // Second button is Trash2 icon
    await deleteButton.click();
    await page.click('button:has-text("Continue")');
    await page.waitForTimeout(1000);

    // Verify deletion
    await expect(faqCard).toHaveCount(0);

    // Check logs
    const { stdout: logs } = await execAsync(
      'docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml logs api --tail=100'
    );

    expect(logs).not.toContain('Permission denied');
  });

  test('Entrypoint script should fix permissions on startup', async ({ page }) => {
    // Check if entrypoint script exists and runs
    const { stdout: dockerfileLogs } = await execAsync(
      'docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml logs api --tail=200'
    );

    // Look for entrypoint execution logs
    // This will fail initially until entrypoint script is added
    // After fix, should see log messages like "Fixing file permissions..."
    const hasEntrypointLogs = dockerfileLogs.includes('Fixing') ||
                              dockerfileLogs.includes('permissions') ||
                              dockerfileLogs.includes('chown');

    if (!hasEntrypointLogs) {
      console.warn(
        'WARNING: No entrypoint permission-fixing logs found. ' +
        'Entrypoint script may not be implemented yet.'
      );
    }

    // Verify files have correct ownership
    const { stdout: permissions } = await execAsync(
      'docker compose -f ../docker/docker-compose.yml -f ../docker/docker-compose.local.yml exec -T api stat -c "%U:%G %a" /data/extracted_faq.jsonl'
    );

    console.log('FAQ file ownership:', permissions);
    expect(permissions.trim()).toMatch(/bisq-support:bisq-support|1001:1001/);
  });
});

test.describe('Cross-session Permission Tests', () => {
  test('FAQ deletion by one admin should be visible to another', async ({ browser }) => {
    // Create two browser contexts (two admin sessions)
    const context1 = await browser.newContext();
    const context2 = await browser.newContext();

    const page1 = await context1.newPage();
    const page2 = await context2.newPage();

    // Login both admins
    for (const page of [page1, page2]) {
      await page.goto('http://localhost:3000/admin');
      await page.waitForSelector('input[type="password"]', { timeout: 10000 });
      await page.fill('input[type="password"]', ADMIN_API_KEY);
      await page.click('button:has-text("Login")');
      await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });
      await page.click('a[href="/admin/manage-faqs"]');
      await page.waitForSelector('text=FAQ', { timeout: 10000 });
    }

    // Admin 1: Create FAQ
    await page1.click('button:has-text("Add New FAQ")');
    const testQuestion = `Cross-session test ${Date.now()}`;
    await page1.fill('input#question', testQuestion);
    await page1.fill('textarea#answer', 'Cross-session test');
    await page1.fill('input#category', 'General');
    await page1.click('button:has-text("Add FAQ")');
    await page1.waitForTimeout(1000);

    // Admin 2: Refresh and verify FAQ appears
    await page2.reload();
    await page2.waitForSelector('.bg-card.border.border-border.rounded-lg', { timeout: 10000 });
    const faqOnPage2 = page2.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    await expect(faqOnPage2).toBeVisible();

    // Admin 1: Delete FAQ
    const faqOnPage1 = page1.locator(`.bg-card.border.border-border.rounded-lg:has-text("${testQuestion}")`);
    const deleteButton = faqOnPage1.locator('button').nth(1); // Second button is Trash2 icon
    await deleteButton.click();
    await page1.click('button:has-text("Continue")');
    await page1.waitForTimeout(1000);

    // Admin 2: Refresh and verify FAQ is gone
    await page2.reload();
    await page2.waitForSelector('.bg-card.border.border-border.rounded-lg', { timeout: 10000 });
    await expect(faqOnPage2).toHaveCount(0);

    // Cleanup
    await context1.close();
    await context2.close();
  });
});
