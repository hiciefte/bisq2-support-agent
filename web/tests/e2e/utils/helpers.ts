/**
 * Common test helper functions for E2E tests
 *
 * Provides reusable utilities to reduce code duplication across test files.
 */

import { Page, expect, APIRequestContext } from '@playwright/test';
import { API_BASE_URL } from './env';

/**
 * Dismiss the privacy notice if it appears
 *
 * @param page - Playwright page instance
 */
export async function dismissPrivacyNotice(page: Page): Promise<void> {
  const privacyButton = page.locator('button:has-text("I Understand")');
  if (await privacyButton.isVisible()) {
    await privacyButton.click();
  }
}

/**
 * Wait for the assistant message to appear after sending a chat message
 *
 * Waits for both the Bisq AI avatar AND the input field to become enabled again
 * (indicating the response has finished loading).
 *
 * @param page - Playwright page instance
 * @param timeout - Maximum time to wait in milliseconds (default: 30000)
 */
export async function waitForAssistantMessage(
  page: Page,
  timeout: number = 30000
): Promise<void> {
  // Wait for the avatar to appear
  await page.waitForSelector('img[alt="Bisq AI"]', { timeout });

  // Wait for the input field to become enabled (response finished loading)
  await page.waitForSelector('input:not([disabled]), textarea:not([disabled])', { timeout });

  // Also wait for feedback buttons to appear (indicates complete response)
  await page.waitForSelector('button[aria-label="Rate as helpful"], button[aria-label="Rate as not helpful"]', { timeout });
}

/**
 * Wait for the API to be healthy and ready to accept requests
 *
 * Polls the /health endpoint until it returns 200 status.
 * Uses Playwright's request client for consistency.
 *
 * @param requestContext - Playwright APIRequestContext or Page
 * @param timeout - Maximum time to wait in milliseconds (default: 60000)
 */
export async function waitForApiReady(
  requestContext: APIRequestContext | Page,
  timeout: number = 60000
): Promise<void> {
  const request = 'request' in requestContext ? requestContext.request : requestContext;

  await expect
    .poll(
      async () => {
        try {
          const res = await request.get(`${API_BASE_URL}/health`);
          return res.status();
        } catch {
          return 0;
        }
      },
      { timeout, intervals: [1000, 2000, 3000] }
    )
    .toBe(200);
}

/**
 * Send a chat message and wait for the response
 *
 * @param page - Playwright page instance
 * @param message - Message text to send
 * @param timeout - Maximum time to wait for response (default: 30000)
 */
export async function sendChatMessage(
  page: Page,
  message: string,
  timeout: number = 30000
): Promise<void> {
  const inputField = page.getByRole('textbox');
  await inputField.click();
  await inputField.pressSequentially(message, { delay: 50 });

  // Wait for React state to update and button to become enabled
  await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
  await page.click('button[type="submit"]');

  // Wait for assistant response
  await waitForAssistantMessage(page, timeout);
}

/**
 * Check if sources are visible in the last assistant message
 *
 * @param page - Playwright page instance
 * @returns true if sources are displayed, false otherwise
 */
export async function hasVisibleSources(page: Page): Promise<boolean> {
  try {
    return await page.locator('text=Sources:').isVisible();
  } catch {
    return false;
  }
}

/**
 * Login to admin interface with retry logic for server recovery
 *
 * @param page - Playwright page instance
 * @param apiKey - Admin API key for authentication
 * @param baseUrl - Base URL of the web application
 * @param maxRetries - Maximum number of retry attempts (default: 5)
 */
export async function loginAsAdmin(
  page: Page,
  apiKey: string,
  baseUrl: string,
  maxRetries: number = 5
): Promise<void> {
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      // Use domcontentloaded - faster and doesn't wait for all network requests
      await page.goto(`${baseUrl}/admin`, {
        waitUntil: 'domcontentloaded',
        timeout: 20000
      });

      // Wait for the loading spinner to disappear (SecureAuth component finishes auth check)
      // The spinner has animate-spin class, wait for it to be gone
      let spinnerSeen = false;
      try {
        await page.waitForSelector('svg.animate-spin', { state: 'attached', timeout: 2000 });
        spinnerSeen = true;
      } catch {
        // Spinner may not appear if auth check is fast, that's ok
      }
      if (spinnerSeen) {
        await page.waitForSelector('svg.animate-spin', { state: 'detached', timeout: 30000 });
      }

      // Wait for either the login form or dashboard to appear (handles both logged-out and logged-in states)
      const loginInput = page.locator('input#apiKey');
      const dashboard = page
        .locator('text=Admin Dashboard')
        .or(page.locator('h1:has-text("Overview")'));
      await loginInput.or(dashboard).first().waitFor({ timeout: 20000 });

      if (await dashboard.first().isVisible()) {
        // Already authenticated, we're done
        console.log('loginAsAdmin: Already authenticated');
        return;
      }

      // Fill in the login form using the input ID directly
      await page.fill('input#apiKey', apiKey);
      await page.click('button:has-text("Login")');

      // Wait for successful login - check for dashboard content
      await dashboard.first().waitFor({ timeout: 15000 });
      return; // Success
    } catch (error) {
      lastError = error as Error;
      console.log(`loginAsAdmin attempt ${attempt}/${maxRetries} failed: ${lastError.message}`);
      if (attempt < maxRetries) {
        const delay = attempt * 3000; // Linear backoff
        console.log(`Waiting ${delay}ms before retry...`);
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }
  throw lastError ?? new Error('loginAsAdmin failed with no retries configured');
}

/**
 * Navigate to FAQ management page with retry logic (assumes already logged in as admin)
 *
 * @param page - Playwright page instance
 * @param maxRetries - Maximum number of retry attempts (default: 3)
 */
export async function navigateToFaqManagement(page: Page, maxRetries: number = 3): Promise<void> {
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const faqLink = page.locator('a[href="/admin/manage-faqs"]').first();
      await faqLink.waitFor({ state: 'visible', timeout: 15000 });
      await faqLink.click();
      await page.waitForSelector('text=FAQ', { timeout: 15000 });
      return; // Success
    } catch (error) {
      lastError = error as Error;
      console.log(`navigateToFaqManagement attempt ${attempt}/${maxRetries} failed: ${lastError.message}`);
      if (attempt < maxRetries) {
        const delay = attempt * 2000; // Linear backoff
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }
  throw lastError ?? new Error('navigateToFaqManagement failed with no retries configured');
}

/**
 * Check for permission errors in API logs
 *
 * @param logs - Docker compose logs output
 * @returns true if permission errors found, false otherwise
 */
export function hasPermissionErrors(logs: string): boolean {
  return (
    logs.includes('Permission denied') ||
    logs.includes('EACCES') ||
    logs.includes('[Errno 13]')
  );
}

/**
 * Navigate to feedback management page with retry logic (assumes already logged in as admin)
 *
 * @param page - Playwright page instance
 * @param maxRetries - Maximum number of retry attempts (default: 3)
 */
export async function navigateToFeedbackManagement(page: Page, maxRetries: number = 3): Promise<void> {
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      const feedbackLink = page.locator('a[href="/admin/manage-feedback"]').first();
      await feedbackLink.waitFor({ state: 'visible', timeout: 15000 });
      await feedbackLink.click();
      await page.waitForURL('**/admin/manage-feedback', { timeout: 15000 });
      // Wait for page content: feedback cards, empty state, or page heading
      await Promise.race([
        page.waitForSelector('[class*="border-l-4"]', { timeout: 15000 }),
        page.waitForSelector('text=No feedback found', { timeout: 15000 }),
        page.locator('h1:has-text("Feedback Management")').waitFor({ timeout: 15000 }),
      ]);
      return; // Success
    } catch (error) {
      lastError = error as Error;
      console.log(`navigateToFeedbackManagement attempt ${attempt}/${maxRetries} failed: ${lastError.message}`);
      if (attempt < maxRetries) {
        const delay = attempt * 2000; // Linear backoff
        await new Promise(r => setTimeout(r, delay));
      }
    }
  }
  throw lastError ?? new Error('navigateToFeedbackManagement failed with no retries configured');
}
