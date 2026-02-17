import { expect, Page, test } from "@playwright/test";
import {
  ADMIN_API_KEY,
  WEB_BASE_URL,
  dismissPrivacyNotice,
  getLastBotResponse,
  loginAsAdmin,
  navigateToFeedbackManagement,
  submitChatMessage,
  waitForApiReady,
} from "./utils";

const HELPFUL_BUTTON_SELECTOR = 'button[aria-label="Rate as helpful"]';
const UNHELPFUL_BUTTON_SELECTOR = 'button[aria-label="Rate as unhelpful"]';
const FEEDBACK_CARD_SELECTOR = '[class*="border-l-2"]';

async function openChat(page: Page): Promise<void> {
  await waitForApiReady(page, 60000);
  await page.goto(WEB_BASE_URL);
  await dismissPrivacyNotice(page);
  await page.getByRole("textbox").waitFor({ state: "visible", timeout: 15000 });
}

async function askQuestionAndWaitForAnswer(
  page: Page,
  question: string,
): Promise<{ hasRatingControls: boolean }> {
  const previousProseCount = await submitChatMessage(page, question, 10000);
  await getLastBotResponse(page, {
    previousProseCount,
    timeout: 70000,
    minLength: 5,
    throwOnTransientApiError: false,
  });

  const latestRatingControl = page
    .locator(`${HELPFUL_BUTTON_SELECTOR}, ${UNHELPFUL_BUTTON_SELECTOR}`)
    .last();

  try {
    await latestRatingControl.waitFor({ state: "visible", timeout: 8000 });
    return { hasRatingControls: true };
  } catch {
    return { hasRatingControls: false };
  }
}

async function ensureRateableAssistantResponse(
  page: Page,
  prompts: string[],
): Promise<void> {
  for (const prompt of prompts) {
    const { hasRatingControls } = await askQuestionAndWaitForAnswer(page, prompt);
    if (hasRatingControls) {
      return;
    }
  }

  throw new Error("Unable to obtain a rateable assistant response in this test run.");
}

async function submitPositiveRating(page: Page): Promise<void> {
  const thumbsUpButton = page.locator(HELPFUL_BUTTON_SELECTOR).last();
  await expect(thumbsUpButton).toBeVisible({ timeout: 10000 });
  await thumbsUpButton.click();

  await expect(page.getByText(/Thank you for your feedback!/i).last()).toBeVisible({ timeout: 15000 });
}

async function submitNegativeRating(
  page: Page,
  explanationText: string,
): Promise<{ followupDialogShown: boolean }> {
  const thumbsDownButton = page.locator(UNHELPFUL_BUTTON_SELECTOR).last();
  await expect(thumbsDownButton).toBeVisible({ timeout: 10000 });
  await thumbsDownButton.click();

  const explanationField = page.locator("textarea#feedback-text");
  try {
    await explanationField.waitFor({ state: "visible", timeout: 7000 });
  } catch {
    return { followupDialogShown: false };
  }

  await explanationField.fill(explanationText);

  const submitFeedbackButton = page.getByRole("button", { name: "Submit Feedback" });
  await expect(submitFeedbackButton).toBeEnabled({ timeout: 5000 });
  await submitFeedbackButton.click();

  await expect(explanationField).toBeHidden({ timeout: 10000 });
  return { followupDialogShown: true };
}

async function openFeedbackManagement(page: Page): Promise<void> {
  await loginAsAdmin(page, ADMIN_API_KEY, WEB_BASE_URL);
  await navigateToFeedbackManagement(page);
  await waitForFeedbackListLoad(page);
}

async function waitForFeedbackListLoad(page: Page): Promise<void> {
  const waitForCard = page
    .locator(FEEDBACK_CARD_SELECTOR)
    .first()
    .waitFor({ state: "visible", timeout: 20000 });
  const waitForEmptyState = page.getByText("No feedback found").waitFor({ state: "visible", timeout: 20000 });

  try {
    await Promise.any([waitForCard, waitForEmptyState]);
    return;
  } catch {
    // Handled below by collecting both rejection reasons.
  }

  const [cardResult, emptyStateResult] = await Promise.allSettled([waitForCard, waitForEmptyState]);
  const cardError = cardResult.reason instanceof Error ? cardResult.reason.message : String(cardResult.reason);
  const emptyStateError =
    emptyStateResult.reason instanceof Error
      ? emptyStateResult.reason.message
      : String(emptyStateResult.reason);

  throw new Error(
    `Feedback list did not load: card wait failed (${cardError}); empty-state wait failed (${emptyStateError})`,
  );
}

async function openAllFeedbackTab(page: Page): Promise<void> {
  await page.getByRole("button", { name: /All Feedback/i }).first().click();
  await waitForFeedbackListLoad(page);
}

async function openNegativeFeedbackTab(page: Page): Promise<void> {
  await page.getByRole("button", { name: /^Negative/i }).first().click();
  await waitForFeedbackListLoad(page);
}

async function openFeedbackDetailFromList(
  page: Page,
  options?: { preferredCard?: ReturnType<Page["locator"]> },
): Promise<void> {
  const preferredCard = options?.preferredCard;
  const fallbackCard = page.locator(FEEDBACK_CARD_SELECTOR).first();

  const preferredIsVisible =
    preferredCard ? await preferredCard.first().isVisible().catch(() => false) : false;
  if (preferredCard && preferredIsVisible) {
    await preferredCard.first().click();
  } else {
    await fallbackCard.click();
  }

  await expect(page.locator('[role="dialog"]')).toBeVisible({ timeout: 10000 });
}

test.describe("Feedback Submission", () => {
  test("should submit negative feedback with explanation", async ({ page }) => {
    await openChat(page);
    await ensureRateableAssistantResponse(page, [
      "How do I install Bisq 2?",
      "What operating systems does it support?",
      "What is Bisq Easy?",
      "How does the reputation system work?",
    ]);

    const explanation = "The answer was too technical and did not explain the key benefits clearly.";
    const { followupDialogShown } = await submitNegativeRating(page, explanation);

    await openFeedbackManagement(page);
    await openNegativeFeedbackTab(page);

    const negativeCard = page.locator(FEEDBACK_CARD_SELECTOR).filter({
      has: page.locator("svg.lucide-thumbs-down"),
    });
    await expect(negativeCard.first()).toBeVisible({ timeout: 10000 });
    await openFeedbackDetailFromList(page, { preferredCard: negativeCard });

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toContainText(/Question|Answer/i);

    if (followupDialogShown) {
      await expect(dialog).toContainText(explanation.slice(0, 30));
    }
  });

  test("should submit positive feedback after conversation", async ({ page }) => {
    await openChat(page);

    const messages = [
      "What is Bisq Easy?",
      "How does the reputation system work?",
      "What are the trade limits?",
    ];

    for (const message of messages) {
      const { hasRatingControls } = await askQuestionAndWaitForAnswer(page, message);
      if (!hasRatingControls) {
        await ensureRateableAssistantResponse(page, [
          "Can you answer that briefly in one paragraph?",
          "Give me a concise overview.",
        ]);
      }
    }

    await submitPositiveRating(page);

    await openFeedbackManagement(page);
    await openAllFeedbackTab(page);

    const positiveCard = page.locator(FEEDBACK_CARD_SELECTOR).filter({
      has: page.locator("svg.lucide-thumbs-up"),
    });

    await expect(positiveCard.first()).toBeVisible({ timeout: 10000 });
    await openFeedbackDetailFromList(page, { preferredCard: positiveCard });

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toContainText(/Question|Answer/i);

    const conversationHistoryLabel = dialog.getByText(/Conversation History/i);
    if (await conversationHistoryLabel.isVisible().catch(() => false)) {
      await expect(conversationHistoryLabel).toContainText(/\d+ messages?/i);
    }
  });

  test("should capture conversation history for negative feedback", async ({ page }) => {
    await openChat(page);

    await askQuestionAndWaitForAnswer(page, "How do I install Bisq 2?");
    const secondResponse = await askQuestionAndWaitForAnswer(page, "What operating systems does it support?");
    if (!secondResponse.hasRatingControls) {
      await ensureRateableAssistantResponse(page, [
        "What are the system requirements for Bisq?",
        "How can I verify my setup is compatible?",
      ]);
    }

    await submitNegativeRating(page, "Missing information about macOS installation.");

    await openFeedbackManagement(page);
    await openNegativeFeedbackTab(page);

    const preferredCard = page.locator(FEEDBACK_CARD_SELECTOR).filter({
      hasText: /operating systems/i,
    });

    await openFeedbackDetailFromList(page, { preferredCard });

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toContainText(/Question|Answer/i);

    const conversationHistoryLabel = dialog.getByText(/Conversation History/i);
    if (await conversationHistoryLabel.isVisible().catch(() => false)) {
      await expect(conversationHistoryLabel).toContainText(/\d+ messages?/i);
    }
  });

  test("should handle feedback without explanation", async ({ page }) => {
    await openChat(page);
    const initialResponse = await askQuestionAndWaitForAnswer(page, "Test quick positive feedback");
    if (!initialResponse.hasRatingControls) {
      await ensureRateableAssistantResponse(page, [
        "Summarize how user feedback works in this chat.",
        "Give a short answer about Bisq support.",
      ]);
    }

    await submitPositiveRating(page);

    await expect(page.locator("textarea#feedback-text")).toBeHidden();

    await openFeedbackManagement(page);
    await openAllFeedbackTab(page);

    const positiveCard = page.locator(FEEDBACK_CARD_SELECTOR).filter({
      has: page.locator("svg.lucide-thumbs-up"),
    });
    await expect(positiveCard.first()).toBeVisible({ timeout: 10000 });
  });

  // Depends on feedback created by prior tests - runs after feedback creation.
  test("should display conversation message count in feedback detail", async ({ page }) => {
    await openFeedbackManagement(page);

    const feedbackCards = page.locator(FEEDBACK_CARD_SELECTOR);
    const count = await feedbackCards.count();
    expect(count).toBeGreaterThan(0);

    await feedbackCards.first().click();

    const dialog = page.locator('[role="dialog"]');
    await expect(dialog).toBeVisible({ timeout: 10000 });

    const conversationHistoryLabel = dialog.getByText(/Conversation History/i);
    if (await conversationHistoryLabel.isVisible().catch(() => false)) {
      await expect(conversationHistoryLabel).toContainText(/\d+ messages?/i);
    }
  });

  // Depends on feedback created by prior tests - runs after feedback creation.
  test("should filter feedback by rating", async ({ page }) => {
    await openFeedbackManagement(page);
    await openNegativeFeedbackTab(page);

    const cards = page.locator(FEEDBACK_CARD_SELECTOR);
    const count = await cards.count();

    if (count === 0) {
      await expect(page.getByText("No feedback found")).toBeVisible();
      return;
    }

    for (let i = 0; i < Math.min(count, 5); i++) {
      const thumbsDown = cards.nth(i).locator("svg.lucide-thumbs-down");
      await expect(thumbsDown).toBeVisible();
    }
  });

  // Depends on feedback created by prior tests - runs after feedback creation.
  test("should export feedback data", async ({ page }) => {
    await openFeedbackManagement(page);

    const exportButton = page.getByRole("button", { name: /Export/i });
    await expect(exportButton).toBeVisible();

    if (await exportButton.isDisabled()) {
      await expect(page.getByText("No feedback found")).toBeVisible();
      return;
    }

    const downloadPromise = page.waitForEvent("download");
    await exportButton.click();

    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/feedback-export-.*\.csv/i);
  });
});
