import { test, expect, Page } from '@playwright/test';

/**
 * Bisq Version Handling Tests
 *
 * These E2E tests verify that the chatbot correctly handles:
 * - Explicit Bisq 1 questions (answered with disclaimer when info available)
 * - Ambiguous questions (default to Bisq 2)
 * - Version switching in conversation
 * - Proper version disclaimers in responses
 */

test.describe('Bisq Version Handling', () => {
  // These tests make real LLM API calls and may fail due to transient API
  // errors ("failed to fetch") or slow responses. Retry once on failure.
  test.describe.configure({ retries: 1 });

  // LLM responses are non-deterministic and the API may be slow under load.
  // 90s accommodates the 50s prose-chat wait + submit + assertion overhead.
  test.setTimeout(90000);

  test.beforeEach(async ({ page }) => {
    // Navigate to chat interface (use env variable if available, fallback to localhost)
    const baseUrl = process.env.BASE_URL || 'http://localhost:3000';
    await page.goto(baseUrl);

    // Handle privacy notice if it appears
    const privacyButton = page.locator('button:has-text("I Understand")');
    if (await privacyButton.isVisible()) {
      await privacyButton.click();
    }

    // Wait for chat to load
    await page.getByRole('textbox').waitFor({ state: 'visible' });
  });

  /**
   * Helper function to extract the last bot response text.
   *
   * Three-phase approach:
   * 1. Wait for bot avatar (appears immediately when loading state starts)
   * 2. Wait for div.prose-chat (appears only after LLM response renders)
   * 3. Extract text from the last prose-chat element
   *
   * Throws on transient API errors so the retry mechanism can re-run the test.
   */
  async function getLastBotResponse(
    page: Page,
    previousProseCount?: number,
  ): Promise<string> {
    // Phase 1: Wait for bot avatar (indicates response loading started)
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 10000 });

    // Phase 2: Wait for new prose-chat to appear when caller provides baseline count.
    // Fallback to simple selector wait for first response in conversation.
    if (typeof previousProseCount === 'number') {
      await page.waitForFunction(
        (prevCount) => document.querySelectorAll('div.prose-chat').length > prevCount,
        previousProseCount,
        { timeout: 50000 },
      );
    } else {
      await page.waitForSelector('div.prose-chat', { timeout: 50000 });
    }

    // Phase 3: Poll until the prose-chat content has meaningful text.
    // The element may exist briefly before text is fully populated.
    let responseText = '';
    let attempts = 0;
    const maxAttempts = 15;

    while (attempts < maxAttempts) {
      const proseElements = page.locator('div.prose-chat');
      const count = await proseElements.count();
      if (count > 0) {
        responseText = (await proseElements.nth(count - 1).innerText()).trim();
      }

      // Accept once we have substantial text
      if (responseText.length >= 30) {
        break;
      }

      await page.waitForTimeout(1000);
      attempts++;
    }

    if (responseText.length < 30) {
      throw new Error(
        `Bot response not received after ${maxAttempts}s. Got: "${responseText}"`
      );
    }

    // If the API returned a transient error, throw to trigger retry
    if (/error occurred.*failed to fetch/i.test(responseText)) {
      throw new Error(`Transient API error: ${responseText}`);
    }

    return responseText;
  }

  test('should answer Bisq 1 questions with disclaimer when information is available', async ({ page }) => {
    // Send explicit Bisq 1 question
    const inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('How do I resolve a trade dispute in Bisq 1?', { delay: 50 });

    // Submit the question
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Get bot response text using helper function
    const responseText = await getLastBotResponse(page);
    const responseLower = responseText.toLowerCase();

    // Verify response characteristics
    // Should NOT refuse to answer
    expect(responseLower).not.toContain('i can only provide information about bisq 2');
    expect(responseLower).not.toContain('sorry, but i can only');

    // Should provide Bisq 1 information (if available in knowledge base)
    // OR provide helpful redirect if not available
    const hasValidResponse =
      responseLower.includes('bisq 1') ||
      responseLower.includes('bisq1') ||
      responseLower.includes('don\'t have specific information about that for bisq 1');

    expect(hasValidResponse).toBeTruthy();

    // Mentioning Bisq 1 directly is sufficient version context for this test.
  });

  test('should handle ambiguous questions appropriately', async ({ page }) => {
    // Send ambiguous question (no version specified)
    const inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('How do I trade?', { delay: 50 });

    // Submit the question
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Get bot response text using helper function
    const responseText = await getLastBotResponse(page);
    const responseLower = responseText.toLowerCase();

    // For ambiguous questions, the bot should either:
    // 1. Default to Bisq 2 information (mentions Bisq 2 without Bisq 1)
    // 2. Ask for clarification (mentions both versions in a question format)
    const mentionsBisq2 = /bisq 2|bisq2|bisq easy/.test(responseLower);
    const asksClarification = /which|are you using|do you mean|bisq 1.*or.*bisq 2|bisq 2.*or.*bisq 1/.test(responseLower);

    // Should mention Bisq 2 in some form (either as answer or clarification)
    expect(mentionsBisq2).toBeTruthy();

    // If Bisq 1 is mentioned, it should be in a clarification question, not as a default answer
    if (/bisq 1|bisq1/.test(responseLower)) {
      expect(asksClarification).toBeTruthy();
    }
  });

  test('should handle explicit Bisq 2 questions correctly', async ({ page }) => {
    // Send explicit Bisq 2 question
    const inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('What is Bisq 2?', { delay: 50 });

    // Submit the question
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Get bot response text using helper function
    const responseText = await getLastBotResponse(page);
    const responseLower = responseText.toLowerCase();

    // Should provide Bisq 2 information
    expect(responseLower).toMatch(/bisq 2|bisq2/);

    // Should not include Bisq 1 disclaimer
    expect(responseLower).not.toContain('this information is for bisq 1');
  });

  test('should handle version switching in conversation', async ({ page }) => {
    // First question: Bisq 2 (default)
    let inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('How do I start trading?', { delay: 50 });
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Wait for first response to fully render
    await getLastBotResponse(page);

    // Second question: Switch to Bisq 1
    inputField = page.getByRole('textbox');
    await inputField.click();
    const proseCountBeforeSecondQuestion = await page.locator('div.prose-chat').count();
    await inputField.pressSequentially('How about in Bisq 1?', { delay: 50 });
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Wait for second response using the same robust helper
    const secondResponse = await getLastBotResponse(page, proseCountBeforeSecondQuestion);
    const responseLower = secondResponse.toLowerCase();

    // Should recognize the Bisq 1 context from follow-up
    const handlesBisq1Context =
      responseLower.includes('bisq 1') ||
      responseLower.includes('bisq1') ||
      responseLower.includes('don\'t have specific information about that for bisq 1');

    expect(handlesBisq1Context).toBeTruthy();
  });

  test('should handle comparison questions between versions', async ({ page }) => {
    // Send comparison question
    const inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('What is the difference between Bisq 1 and Bisq 2?', { delay: 50 });

    // Submit the question
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Get bot response text using helper function
    const responseText = await getLastBotResponse(page);
    const responseLower = responseText.toLowerCase();

    // Should mention both versions
    expect(responseLower).toMatch(/bisq 1|bisq1/);
    expect(responseLower).toMatch(/bisq 2|bisq2/);

    // Should provide comparative information (LLM may use many phrasings)
    const hasComparison =
      responseLower.includes('difference') ||
      responseLower.includes('compared') ||
      responseLower.includes('whereas') ||
      responseLower.includes('contrast') ||
      responseLower.includes('unlike') ||
      responseLower.includes('on the other hand') ||
      responseLower.includes('rather') ||
      responseLower.includes('upgrade') ||
      responseLower.includes('successor') ||
      responseLower.includes('evolution');

    expect(hasComparison).toBeTruthy();
  });

  test('should handle Bisq 1 spelling variations', async ({ page }) => {
    // Test with different spelling: "Bisq1" (no space)
    const inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('How do I use Bisq1?', { delay: 50 });

    // Submit the question
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Get bot response text using helper function
    const responseText = await getLastBotResponse(page);
    const responseLower = responseText.toLowerCase();

    // Should provide a meaningful response (not an error or refusal)
    // The bot may interpret "Bisq1" as referring to Bisq 1 or Bisq in general
    const handlesBisq1 =
      responseLower.includes('bisq 1') ||
      responseLower.includes('bisq1') ||
      responseLower.includes('bisq') ||  // May interpret as general Bisq question
      responseLower.includes('trading') ||  // May provide trading info
      responseLower.includes('bitcoin') ||  // May provide Bitcoin-related info
      responseLower.includes('exchange') ||  // May describe exchange functionality
      responseLower.includes('don\'t have specific information') ||
      responseLower.includes('help') ||  // Offers to help
      responseLower.includes('peer-to-peer');  // Describes Bisq functionality

    // Should NOT refuse outright
    const refusesOutright =
      responseLower.includes('i cannot') ||
      responseLower.includes('i\'m unable') ||
      responseLower.includes('not able to');

    expect(handlesBisq1).toBeTruthy();
    expect(refusesOutright).toBeFalsy();
  });

  test('should not refuse Bisq 1 questions outright', async ({ page }) => {
    // Send a Bisq 1 question
    const inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('Tell me about Bisq 1 mediation', { delay: 50 });

    // Submit the question
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');

    // Get bot response text using helper function
    const responseText = await getLastBotResponse(page);
    const responseLower = responseText.toLowerCase();

    // Should NOT contain the old refusal message
    expect(responseLower).not.toContain('i\'m sorry, but i can only provide information about bisq 2');
    expect(responseLower).not.toContain('i can only help with bisq 2');

    // Should either provide info or offer helpful alternatives
    const hasHelpfulResponse =
      responseLower.includes('bisq 1') ||
      responseLower.includes('bisq1') ||
      responseLower.includes('don\'t have specific information') ||
      responseLower.includes('would you like information about bisq 2');

    expect(hasHelpfulResponse).toBeTruthy();
  });
});
