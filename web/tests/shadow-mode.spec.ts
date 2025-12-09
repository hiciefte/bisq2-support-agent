import { test, expect } from '@playwright/test';

test.describe('Shadow Mode Workflow', () => {
  test.beforeEach(async ({ page }) => {
    // Navigate to shadow mode admin
    await page.goto('http://localhost:3000/admin/shadow-mode');

    // Wait for authentication (if needed) and data to load
    await page.waitForTimeout(1000);

    // Check if we need to authenticate
    const loginButton = page.locator('button:has-text("Login")');
    if (await loginButton.isVisible()) {
      // Handle authentication if needed
      // This is placeholder - adjust based on actual auth flow
      console.log('Authentication may be required');
    }

    // Wait for data to load - either cards or empty state
    await page.waitForSelector('[data-testid="version-review-card"], [data-testid="response-review-card"], text="No Responses to Review"', { timeout: 10000 });
  });

  test.describe('Version Review Phase', () => {
    test('should display version toggle buttons with distinct selected state', async ({ page }) => {
      // Check if we have version review cards
      const versionCards = page.locator('[data-testid="version-review-card"]');
      const cardCount = await versionCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No version review cards available');
        return;
      }

      const firstCard = versionCards.first();
      const toggleGroup = firstCard.locator('[role="radiogroup"]');

      // Check buttons are NOT full width (should be around 96px for w-24)
      const button = toggleGroup.locator('button').first();
      const width = await button.evaluate(el => el.clientWidth);
      expect(width).toBeLessThan(150); // Max ~120px for w-24 with padding
      expect(width).toBeGreaterThan(80); // Min reasonable width

      // Check that buttons use flex layout (not grid)
      const containerClass = await toggleGroup.getAttribute('class');
      expect(containerClass).toContain('flex');
      expect(containerClass).not.toContain('grid');

      // Click Bisq 2 button
      await toggleGroup.locator('button:has-text("Bisq 2")').click();

      // Verify selected state is visually distinct
      const selectedButton = toggleGroup.locator('button:has-text("Bisq 2")');
      const selectedClass = await selectedButton.getAttribute('class');

      // Should have bold border (border-2) and ring
      expect(selectedClass).toContain('border-2');
      expect(selectedClass).toContain('ring-2');
      expect(selectedClass).toContain('font-bold');

      // Verify unselected buttons have different style
      const unselectedButton = toggleGroup.locator('button:has-text("Bisq 1")');
      const unselectedClass = await unselectedButton.getAttribute('class');
      expect(unselectedClass).toContain('border'); // Single border
      expect(unselectedClass).not.toContain('border-2'); // Not double border
      expect(unselectedClass).toContain('bg-gray');
    });

    test('should confirm version and generate response', async ({ page }) => {
      // Check if we have version review cards
      const versionCards = page.locator('[data-testid="version-review-card"]');
      const cardCount = await versionCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No version review cards available');
        return;
      }

      const firstCard = versionCards.first();

      // Select version (Bisq 2)
      await firstCard.locator('button:has-text("Bisq 2")').first().click();

      // Click confirm button
      await firstCard.locator('button:has-text("Confirm & Generate")').click();

      // Wait for generating state
      await expect(page.locator('button:has-text("Generating...")')).toBeVisible({ timeout: 5000 });

      // Wait for generation to complete (up to 30 seconds)
      await expect(page.locator('button:has-text("Generating...")')).not.toBeVisible({ timeout: 35000 });

      // Verify Response Review card appears OR card moves to different status
      // (card may have transitioned to response review or been removed from view)
      await page.waitForTimeout(2000);

      // Check that the original version review card is no longer in pending status
      const remainingVersionCards = await page.locator('[data-testid="version-review-card"][data-status="pending_version_review"]').count();
      expect(remainingVersionCards).toBeLessThan(cardCount);
    });

    test('should skip version review and not show response card', async ({ page }) => {
      // Check if we have version review cards
      const versionCards = page.locator('[data-testid="version-review-card"]');
      const initialCardCount = await versionCards.count();

      if (initialCardCount === 0) {
        test.skip(true, 'No version review cards available');
        return;
      }

      const firstCard = versionCards.first();

      // Get initial response review card count
      const initialResponseCount = await page.locator('[data-testid="response-review-card"]').count();

      // Select skip reason
      await firstCard.locator('button:has-text("Skip...")').click();
      await page.locator('[role="option"]:has-text("Not a question")').click();

      // Wait for card removal
      await page.waitForTimeout(1000);

      // Verify card is removed
      const newCardCount = await versionCards.count();
      expect(newCardCount).toBe(initialCardCount - 1);

      // Verify no new Response Review card appeared
      const newResponseCount = await page.locator('[data-testid="response-review-card"]').count();
      expect(newResponseCount).toBe(initialResponseCount);

      // Verify success toast
      await expect(page.locator('text=/Response skipped/')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Response Review Phase', () => {
    test('should edit response inline using "e" keyboard shortcut', async ({ page }) => {
      // Check if we have response review cards
      const responseCards = page.locator('[data-testid="response-review-card"]');
      const cardCount = await responseCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No response review cards available');
        return;
      }

      const firstCard = responseCards.first();

      // Select the card using keyboard navigation (j key)
      await page.keyboard.press('j');

      // Press 'e' key to enter edit mode
      await page.keyboard.press('e');

      // Wait a bit for state update
      await page.waitForTimeout(500);

      // Verify textarea appears
      await expect(firstCard.locator('textarea')).toBeVisible();

      // Verify only Cancel and "Save & Approve" buttons are shown (no "Save Edit")
      await expect(firstCard.locator('button:has-text("Cancel")')).toBeVisible();
      await expect(firstCard.locator('button:has-text("Save & Approve")')).toBeVisible();
      await expect(firstCard.locator('button:has-text("Save Edit")')).not.toBeVisible();
    });

    test('should approve response in edit mode with single action', async ({ page }) => {
      // Check if we have response review cards
      const responseCards = page.locator('[data-testid="response-review-card"]');
      const cardCount = await responseCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No response review cards available');
        return;
      }

      const firstCard = responseCards.first();
      const cardId = await firstCard.getAttribute('data-testid');

      // Enter edit mode
      await firstCard.locator('button:has-text("Edit")').click();
      await page.waitForTimeout(300);

      // Modify response
      const textarea = firstCard.locator('textarea');
      await textarea.fill('Modified response text for testing');

      // Click "Save & Approve" button
      await firstCard.locator('button:has-text("Save & Approve")').click();

      // Verify card is removed from pending queue
      await expect(firstCard).not.toBeVisible({ timeout: 10000 });

      // Verify success toast (either save or approve message)
      await expect(page.locator('text=/approved|saved/i')).toBeVisible({ timeout: 5000 });
    });

    test('should reject response with detailed error message if it fails', async ({ page }) => {
      // Check if we have response review cards
      const responseCards = page.locator('[data-testid="response-review-card"]');
      const cardCount = await responseCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No response review cards available');
        return;
      }

      const firstCard = responseCards.first();

      // Mock API failure
      await page.route('**/admin/shadow-mode/responses/*/reject', route => {
        route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Database connection failed' })
        });
      });

      // Click reject
      await firstCard.locator('button:has-text("Reject")').click();

      // Verify detailed error toast appears
      await expect(page.locator('text=/Failed to reject.*Database connection/i')).toBeVisible({ timeout: 5000 });
    });

    test('should cancel edit mode and restore original response', async ({ page }) => {
      // Check if we have response review cards
      const responseCards = page.locator('[data-testid="response-review-card"]');
      const cardCount = await responseCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No response review cards available');
        return;
      }

      const firstCard = responseCards.first();

      // Get original response text
      const originalTextElement = firstCard.locator('.whitespace-pre-wrap').or(firstCard.locator('p.text-sm').filter({ hasText: /\w+/ }));
      const originalText = await originalTextElement.first().textContent();

      // Enter edit mode
      await firstCard.locator('button:has-text("Edit")').click();
      await page.waitForTimeout(300);

      // Modify response
      const textarea = firstCard.locator('textarea');
      await textarea.fill('Different text that should be discarded');

      // Click Cancel
      await firstCard.locator('button:has-text("Cancel")').click();
      await page.waitForTimeout(300);

      // Verify textarea is hidden
      await expect(textarea).not.toBeVisible();

      // Verify original text is shown (check that some of the original text is present)
      if (originalText) {
        await expect(firstCard.locator(`text=${originalText.slice(0, 30)}`)).toBeVisible();
      }
    });

    test('should approve response without editing', async ({ page }) => {
      // Check if we have response review cards
      const responseCards = page.locator('[data-testid="response-review-card"]');
      const cardCount = await responseCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No response review cards available');
        return;
      }

      const firstCard = responseCards.first();

      // Click approve directly (not in edit mode)
      await firstCard.locator('button:has-text("Approve")').first().click();

      // Verify card is removed
      await expect(firstCard).not.toBeVisible({ timeout: 10000 });

      // Verify success toast
      await expect(page.locator('text=/approved/i')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Failed Response Handling', () => {
    test('should retry failed RAG generation', async ({ page }) => {
      // Check if we have failed cards
      const failedCards = page.locator('[data-testid="failed-card"]');
      const cardCount = await failedCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No failed cards available');
        return;
      }

      const firstFailedCard = failedCards.first();

      // Click retry button
      await firstFailedCard.locator('button:has-text("Retry")').click();

      // Wait for regeneration
      await expect(page.locator('text=/Retrying|Generating/i')).toBeVisible({ timeout: 5000 });

      // Wait for completion or timeout
      await page.waitForTimeout(5000);

      // Verify either success message or card status changed
      // (card may have succeeded or still be generating)
      const newFailedCount = await page.locator('[data-testid="failed-card"]').count();
      expect(newFailedCount).toBeLessThanOrEqual(cardCount);
    });

    test('should skip failed response', async ({ page }) => {
      // Check if we have failed cards
      const failedCards = page.locator('[data-testid="failed-card"]');
      const initialCount = await failedCards.count();

      if (initialCount === 0) {
        test.skip(true, 'No failed cards available');
        return;
      }

      const firstFailedCard = failedCards.first();

      // Click skip button
      await firstFailedCard.locator('button:has-text("Skip")').click();

      // Verify card is removed
      await page.waitForTimeout(1000);
      const newCount = await failedCards.count();
      expect(newCount).toBe(initialCount - 1);
    });
  });

  test.describe('Statistics Dashboard', () => {
    test('should display statistics cards', async ({ page }) => {
      // Verify all stat cards are present
      await expect(page.locator('[data-testid="stat-total"]')).toBeVisible();
      await expect(page.locator('[data-testid="stat-version-review"]')).toBeVisible();
      await expect(page.locator('[data-testid="stat-pending"]')).toBeVisible();

      // Verify they contain numeric values
      const totalText = await page.locator('[data-testid="stat-total"]').textContent();
      expect(totalText).toMatch(/\d+/);
    });

    test('should update stats after actions', async ({ page }) => {
      // Get initial pending count
      const initialPendingText = await page.locator('[data-testid="stat-pending"]').textContent();
      const initialPending = parseInt(initialPendingText || '0', 10);

      // Check if we have response review cards to approve
      const responseCards = page.locator('[data-testid="response-review-card"]');
      const cardCount = await responseCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No response review cards available');
        return;
      }

      // Approve a response
      const firstCard = responseCards.first();
      await firstCard.locator('button:has-text("Approve")').first().click();

      // Wait for action to complete
      await page.waitForTimeout(2000);

      // Verify stats refreshed (pending count should have decreased)
      const newPendingText = await page.locator('[data-testid="stat-pending"]').textContent();
      const newPending = parseInt(newPendingText || '0', 10);

      expect(newPending).toBeLessThan(initialPending);
    });
  });

  test.describe('Keyboard Navigation', () => {
    test('should navigate cards with j/k keys', async ({ page }) => {
      // Check if we have any cards
      const allCards = page.locator('[data-testid="version-review-card"], [data-testid="response-review-card"]');
      const cardCount = await allCards.count();

      if (cardCount < 2) {
        test.skip(true, 'Need at least 2 cards for navigation test');
        return;
      }

      // Press j to navigate down
      await page.keyboard.press('j');
      await page.waitForTimeout(300);

      // Verify a card has focus/selection (ring-2 class)
      const selectedCards = page.locator('.ring-2.ring-primary');
      await expect(selectedCards).toHaveCount(1);

      // Press j again to move to next card
      await page.keyboard.press('j');
      await page.waitForTimeout(300);

      // Press k to move back up
      await page.keyboard.press('k');
      await page.waitForTimeout(300);

      // Should still have exactly one selected card
      await expect(selectedCards).toHaveCount(1);
    });

    test('should open command palette with Cmd+K', async ({ page }) => {
      // Press Cmd+K (or Ctrl+K on non-Mac)
      await page.keyboard.press('Meta+k');

      // Verify command palette opens
      await expect(page.locator('input[placeholder*="command"]')).toBeVisible({ timeout: 2000 });
    });
  });

  test.describe('Filtering', () => {
    test('should filter responses by status', async ({ page }) => {
      // Get total count
      const totalText = await page.locator('[data-testid="stat-total"]').textContent();
      const total = parseInt(totalText || '0', 10);

      if (total === 0) {
        test.skip(true, 'No responses to filter');
        return;
      }

      // Change filter to "Version Review"
      await page.locator('button:has-text("All Items")').click();
      await page.locator('text="Version Review"').last().click();

      // Wait for filter to apply
      await page.waitForTimeout(1000);

      // Verify only version review cards are shown
      const versionCards = await page.locator('[data-testid="version-review-card"]').count();
      const responseCards = await page.locator('[data-testid="response-review-card"]').count();

      // Should have version cards OR empty state
      if (versionCards === 0) {
        await expect(page.locator('text="No Responses to Review"')).toBeVisible();
      } else {
        expect(versionCards).toBeGreaterThan(0);
        expect(responseCards).toBe(0); // Should not show response cards
      }
    });
  });

  test.describe('Visual Regression', () => {
    test('version toggle buttons maintain consistent sizing', async ({ page }) => {
      // Check if we have version review cards
      const versionCards = page.locator('[data-testid="version-review-card"]');
      const cardCount = await versionCards.count();

      if (cardCount === 0) {
        test.skip(true, 'No version review cards available');
        return;
      }

      const firstCard = versionCards.first();
      const buttons = firstCard.locator('[role="radiogroup"] button');

      // Get width of all buttons
      const widths = await Promise.all(
        Array.from({ length: 3 }, (_, i) =>
          buttons.nth(i).evaluate(el => el.clientWidth)
        )
      );

      // All buttons should be same width
      expect(widths[0]).toBe(widths[1]);
      expect(widths[1]).toBe(widths[2]);

      // Width should be consistent with w-24 class (~96px)
      expect(widths[0]).toBeGreaterThan(85);
      expect(widths[0]).toBeLessThan(110);
    });
  });

  test.describe('Error Handling', () => {
    test('should handle API timeout gracefully', async ({ page }) => {
      // Mock slow API response
      await page.route('**/admin/shadow-mode/responses*', async route => {
        await new Promise(resolve => setTimeout(resolve, 60000)); // 60 second delay
        route.fulfill({ status: 504, body: 'Gateway Timeout' });
      });

      // Reload page
      await page.reload();

      // Should show error message or empty state
      await expect(page.locator('text=/Error|Failed|timeout/i')).toBeVisible({ timeout: 15000 });
    });

    test('should handle network failure gracefully', async ({ page }) => {
      // Mock network failure
      await page.route('**/admin/shadow-mode/responses*', route => {
        route.abort('failed');
      });

      // Reload page
      await page.reload();

      // Should show error message
      await expect(page.locator('text=/Error|Failed/i')).toBeVisible({ timeout: 10000 });
    });
  });
});
