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
 * Uses the Bisq AI avatar as the indicator that the response is ready.
 *
 * @param page - Playwright page instance
 * @param timeout - Maximum time to wait in milliseconds (default: 30000)
 */
export async function waitForAssistantMessage(
  page: Page,
  timeout: number = 30000
): Promise<void> {
  await page.waitForSelector('img[alt="Bisq AI"]', { timeout });
  console.log('Chat response received from assistant');
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
 * Login to admin interface
 *
 * @param page - Playwright page instance
 * @param apiKey - Admin API key for authentication
 * @param baseUrl - Base URL of the web application
 */
export async function loginAsAdmin(
  page: Page,
  apiKey: string,
  baseUrl: string
): Promise<void> {
  await page.goto(`${baseUrl}/admin`);
  await page.waitForSelector('input[type="password"]', { timeout: 10000 });
  await page.fill('input[type="password"]', apiKey);
  await page.click('button:has-text("Login")');
  await page.waitForSelector('text=Admin Dashboard', { timeout: 10000 });
}

/**
 * Navigate to FAQ management page (assumes already logged in as admin)
 *
 * @param page - Playwright page instance
 */
export async function navigateToFaqManagement(page: Page): Promise<void> {
  const faqLink = page.locator('a[href="/admin/manage-faqs"]').first();
  await faqLink.waitFor({ state: 'visible', timeout: 15000 });
  await faqLink.click();
  await page.waitForSelector('text=FAQ', { timeout: 10000 });
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
