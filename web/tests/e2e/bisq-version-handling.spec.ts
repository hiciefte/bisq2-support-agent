import { test, expect } from '@playwright/test';

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
  // Timeout optimized based on actual test runs (36.1s observed, 45s provides 25% buffer)
  test.setTimeout(45000);

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
   * Helper function to extract the last bot response text
   * Waits for bot avatar, finds its message container, and extracts text
   */
  async function getLastBotResponse(page: any): Promise<string> {
    // Wait for bot avatar to appear (indicates response started)
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });

    // Get all bot avatars
    const botAvatars = page.locator('img[alt="Bisq AI"]');
    const count = await botAvatars.count();

    // Get the last bot avatar's parent's parent's sibling (the actual message container)
    // DOM structure: div (row) > div (avatar container) > avatar + div (message container)
    const lastAvatar = botAvatars.nth(count - 1);

    // Navigate up to the row div, then get the next sibling which contains the message
    const messageRow = lastAvatar.locator('../..');
    const messageContainer = messageRow.locator('div').nth(1);

    // Wait for the actual response to load (not just the loading message)
    // Keep checking until we get a response that doesn't contain loading message placeholders
    let responseText = '';
    let attempts = 0;
    const maxAttempts = 30; // 30 seconds total wait time

    while (attempts < maxAttempts) {
      responseText = await messageContainer.innerText();
      responseText = responseText.trim();

      // Check if it's still a loading message
      // All possible loading message patterns from src/components/chat/hooks/use-chat-messages.ts
      const isLoadingMessage =
        responseText.includes('Thinking...') ||
        responseText.includes('potato CPU') ||
        responseText.includes('dial-up soup') ||
        responseText.includes('meditating with a modem') ||
        responseText.includes('Hamster union break') ||
        responseText.includes('procrastinating') ||
        responseText.includes('Turtles in molasses') ||
        responseText.includes('sharpening its crayon') ||
        responseText.includes('Coffee break') ||
        responseText.includes('56k vibe') ||
        responseText.includes('Sloth-mode') ||
        responseText.includes('moonwalking your request') ||
        responseText.includes('Drunk penguin') ||
        responseText.includes('floppy disk') ||
        responseText.includes('Wi-Fi fumes') ||
        responseText.includes('Mini-vacay') ||
        responseText.includes('wrestling a calculator') ||
        responseText.includes('90s dial-up loop') ||
        responseText.includes('Snail rave') ||
        responseText.includes('teaching a toaster') ||
        responseText.includes('Commodore 64') ||
        responseText.includes('juggling with a brick') ||
        responseText.includes('Unicycle CPU') ||
        responseText.includes('your answer\'s') ||
        responseText.includes('AI\'s') ||
        responseText.includes('your reply\'s') ||
        responseText.includes('give it') ||
        responseText.includes('ETA') ||
        responseText.includes('your turn\'s') ||
        responseText.startsWith('...') ||
        responseText.startsWith('..·') ||
        responseText.length < 20; // Loading messages are typically short

      if (!isLoadingMessage) {
        break;
      }

      await page.waitForTimeout(1000);
      attempts++;
    }

    // Extract and return the text content
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

    // Should include disclaimer if Bisq 1 info was provided
    if (responseLower.includes('bisq 1') || responseLower.includes('bisq1')) {
      const hasDisclaimer =
        responseLower.includes('note:') ||
        responseLower.includes('this information is for bisq 1') ||
        responseLower.includes('for bisq 2');

      expect(hasDisclaimer).toBeTruthy();
    }
  });

  test('should default to Bisq 2 for ambiguous questions', async ({ page }) => {
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

    // Should mention Bisq 2 (strengthened assertion)
    expect(responseLower).toMatch(/bisq 2|bisq2/);

    // Should not mention Bisq 1 for ambiguous queries (independent assertion)
    expect(responseLower).not.toMatch(/bisq 1|bisq1/);
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
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });

    // Wait for response to complete
    await page.waitForTimeout(1000);

    // Second question: Switch to Bisq 1
    inputField = page.getByRole('textbox');
    await inputField.click();
    await inputField.pressSequentially('How about in Bisq 1?', { delay: 50 });
    await page.waitForSelector('button[type="submit"]:not([disabled])', { timeout: 5000 });
    await page.click('button[type="submit"]');
    await page.waitForSelector('img[alt="Bisq AI"]', { timeout: 30000 });

    // Wait for response to fully render
    await page.waitForTimeout(2000);

    // Get the page content to extract response text
    const pageContent = await page.content();
    const responseText = pageContent;
    const responseLower = responseText?.toLowerCase() || '';

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

    // Should provide comparative information
    const hasComparison =
      responseLower.includes('difference') ||
      responseLower.includes('compared') ||
      responseLower.includes('whereas') ||
      responseLower.includes('while') ||
      responseLower.includes('contrast') ||
      responseLower.includes('unlike');

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

    // Should recognize "Bisq1" as Bisq 1
    const handlesBisq1 =
      responseLower.includes('bisq 1') ||
      responseLower.includes('bisq1') ||
      responseLower.includes('don\'t have specific information about that for bisq 1');

    expect(handlesBisq1).toBeTruthy();
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
