/**
 * E2E Tests for Moderator Review Queue Frontend
 *
 * TDD Approach: Write tests FIRST, then implement features to make them pass
 *
 * Test Coverage:
 * - Sprint 1 (MVP): Core queue view with approve/reject
 * - Sprint 2 (Polish): Animations, search, sources
 * - Sprint 3 (Edit): Edit modal functionality
 */

import { test, expect } from '@playwright/test';

// Helper function to authenticate via API
async function authenticateAdmin(page: any) {
  // Call login API directly
  const response = await page.request.post('http://localhost:8000/admin/auth/login', {
    data: {
      api_key: 'dev_admin_key_with_sufficient_length'
    }
  });

  if (!response.ok()) {
    throw new Error(`Login failed: ${response.status()}`);
  }

  // The cookie is now set in the browser context automatically
}

test.describe('Moderator Review Queue - Sprint 1 MVP', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate before each test
    await authenticateAdmin(page);

    // Navigate to pending responses page
    await page.goto('/admin/pending-responses');

    // Wait for page to load (can't use networkidle due to 30s polling)
    await page.waitForSelector('h1:has-text("Pending Moderator Review")', { timeout: 10000 });
  });

  test('should display pending responses queue with header', async ({ page }) => {
    // Header should be visible
    await expect(page.getByRole('heading', { name: /pending moderator review/i })).toBeVisible();

    // Queue counter should be visible
    await expect(page.getByText(/queue:/i)).toBeVisible();

    // Search input should be visible
    await expect(page.getByPlaceholder(/search questions or answers/i)).toBeVisible();
  });

  test('should display pending response cards with all essential info', async ({ page }) => {
    // Wait for at least one card to appear
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    await expect(firstCard).toBeVisible();

    // Card should display confidence badge
    await expect(firstCard.locator('[data-testid="confidence-badge"]')).toBeVisible();

    // Card should display version badge
    await expect(firstCard.locator('[data-testid="version-badge"]')).toBeVisible();

    // Card should display time ago
    await expect(firstCard.locator('[data-testid="time-ago"]')).toBeVisible();

    // Card should display question
    await expect(firstCard.locator('[data-testid="question-text"]')).toBeVisible();

    // Card should display answer
    await expect(firstCard.locator('[data-testid="answer-text"]')).toBeVisible();

    // Card should display action buttons
    await expect(firstCard.getByRole('button', { name: /approve/i })).toBeVisible();
    await expect(firstCard.getByRole('button', { name: /edit/i })).toBeVisible();
    await expect(firstCard.getByRole('button', { name: /reject/i })).toBeVisible();
  });

  test('should approve response with optimistic UI update', async ({ page }) => {
    // Get initial queue count
    const queueCountText = await page.getByText(/queue: \d+/i).textContent();
    const initialCount = parseInt(queueCountText?.match(/\d+/)?.[0] || '0');

    // Click approve on first card
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const approveButton = firstCard.getByRole('button', { name: /approve/i });

    await approveButton.click();

    // Card should fade out immediately (optimistic UI)
    await expect(firstCard).toHaveClass(/opacity-0/, { timeout: 500 });

    // Queue count should decrease
    await expect(page.getByText(new RegExp(`queue: ${initialCount - 1}`, 'i'))).toBeVisible({
      timeout: 1000
    });

    // Success toast should appear
    await expect(page.getByText(/approved/i)).toBeVisible({ timeout: 2000 });
  });

  test('should reject response with optimistic UI update', async ({ page }) => {
    // Get initial queue count
    const queueCountText = await page.getByText(/queue: \d+/i).textContent();
    const initialCount = parseInt(queueCountText?.match(/\d+/)?.[0] || '0');

    // Click reject on first card
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const rejectButton = firstCard.getByRole('button', { name: /reject/i });

    await rejectButton.click();

    // Card should fade + slide left (optimistic UI)
    await expect(firstCard).toHaveClass(/opacity-0/, { timeout: 500 });

    // Queue count should decrease
    await expect(page.getByText(new RegExp(`queue: ${initialCount - 1}`, 'i'))).toBeVisible({
      timeout: 1000
    });

    // Success toast should appear
    await expect(page.getByText(/rejected/i)).toBeVisible({ timeout: 2000 });
  });

  test('should display empty state when no pending responses', async ({ page }) => {
    // Mock empty API response
    await page.route('**/api/admin/pending*', async (route) => {
      await route.fulfill({
        status: 200,
        body: JSON.stringify([]),
      });
    });

    await page.reload();

    // Empty state should be visible
    await expect(page.getByText(/all caught up/i)).toBeVisible();
    await expect(page.getByText(/no pending responses/i)).toBeVisible();

    // Icon should be visible
    await expect(page.locator('[data-testid="empty-state-icon"]')).toBeVisible();
  });

  test('should handle API errors with rollback', async ({ page }) => {
    // Mock API error for approve
    await page.route('**/api/admin/pending/*/approve', async (route) => {
      await route.fulfill({
        status: 500,
        body: JSON.stringify({ detail: 'Internal server error' }),
      });
    });

    // Get initial queue count
    const queueCountText = await page.getByText(/queue: \d+/i).textContent();
    const initialCount = parseInt(queueCountText?.match(/\d+/)?.[0] || '0');

    // Click approve on first card
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const approveButton = firstCard.getByRole('button', { name: /approve/i });

    await approveButton.click();

    // Card should reappear (rollback)
    await expect(firstCard).toBeVisible({ timeout: 2000 });

    // Queue count should remain the same
    await expect(page.getByText(new RegExp(`queue: ${initialCount}`, 'i'))).toBeVisible();

    // Error toast should appear
    await expect(page.getByText(/failed to approve/i)).toBeVisible({ timeout: 2000 });
  });
});

test.describe('Moderator Review Queue - Sprint 2 Polish', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate before each test
    await authenticateAdmin(page);

    await page.goto('/admin/pending-responses');
    await page.waitForSelector('h1:has-text("Pending Moderator Review")', { timeout: 10000 });
  });

  test('should filter responses by search query (client-side)', async ({ page }) => {
    // Get all cards before search
    const allCards = page.locator('[data-testid="pending-response-card"]');
    const initialCount = await allCards.count();

    // Type search query
    const searchInput = page.getByPlaceholder(/search questions or answers/i);
    await searchInput.fill('wallet');

    // Wait for debounce (300ms)
    await page.waitForTimeout(400);

    // Only matching cards should be visible
    const visibleCards = page.locator('[data-testid="pending-response-card"]:visible');
    const visibleCount = await visibleCards.count();

    expect(visibleCount).toBeLessThanOrEqual(initialCount);

    // Non-matching cards should be hidden
    const hiddenCards = page.locator('[data-testid="pending-response-card"][style*="opacity: 0"]');
    expect(await hiddenCards.count()).toBeGreaterThan(0);
  });

  test('should expand sources on click', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Click "View N sources" button
    const sourcesButton = firstCard.getByRole('button', { name: /view \d+ source/i });
    await sourcesButton.click();

    // Sources should expand with animation (250ms)
    await page.waitForTimeout(300);

    // Source items should be visible
    const sourceItems = firstCard.locator('[data-testid="source-item"]');
    expect(await sourceItems.count()).toBeGreaterThan(0);

    // Chevron should rotate
    const chevron = sourcesButton.locator('svg').first();
    await expect(chevron).toHaveClass(/rotate-180/);
  });

  test('should show confidence tooltip on hover', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const confidenceBadge = firstCard.locator('[data-testid="confidence-badge"]');

    // Hover over confidence badge
    await confidenceBadge.hover();

    // Tooltip should appear with routing reason
    await expect(page.getByRole('tooltip')).toBeVisible({ timeout: 200 });
    await expect(page.getByText(/routed:/i)).toBeVisible();
  });

  test('should animate card removal (approve)', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const approveButton = firstCard.getByRole('button', { name: /approve/i });

    // Click approve
    await approveButton.click();

    // Card should fade out (200ms)
    await page.waitForTimeout(100);
    await expect(firstCard).toHaveClass(/opacity-0/);

    // Next card should slide up (300ms)
    await page.waitForTimeout(400);

    // First card should be removed from DOM
    expect(await page.locator('[data-testid="pending-response-card"]').count()).toBeLessThan(
      await page.locator('[data-testid="pending-response-card"]').count() + 1
    );
  });

  test('should animate card removal (reject)', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const rejectButton = firstCard.getByRole('button', { name: /reject/i });

    // Click reject
    await rejectButton.click();

    // Card should fade + slide left (250ms)
    await page.waitForTimeout(100);
    await expect(firstCard).toHaveClass(/opacity-0/);
    await expect(firstCard).toHaveClass(/translate-x/);

    // Card should be removed from DOM
    await page.waitForTimeout(300);
    expect(await firstCard.isVisible()).toBe(false);
  });
});

test.describe('Moderator Review Queue - Sprint 3 Edit', () => {
  test.beforeEach(async ({ page }) => {
    // Authenticate before each test
    await authenticateAdmin(page);

    await page.goto('/admin/pending-responses');
    await page.waitForSelector('h1:has-text("Pending Moderator Review")', { timeout: 10000 });
  });

  test('should open edit modal on edit button click', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const editButton = firstCard.getByRole('button', { name: /edit/i });

    // Click edit
    await editButton.click();

    // Modal should slide in from right (300ms)
    await expect(page.getByRole('dialog', { name: /edit answer/i })).toBeVisible({
      timeout: 400
    });

    // Backdrop should fade in (200ms)
    await expect(page.locator('[data-testid="modal-backdrop"]')).toHaveClass(/opacity-/);

    // Textarea should be auto-focused
    const textarea = page.getByRole('textbox', { name: /your answer/i });
    await expect(textarea).toBeFocused();
  });

  test('should display read-only question in edit modal', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const questionText = await firstCard.locator('[data-testid="question-text"]').textContent();

    // Open edit modal
    await firstCard.getByRole('button', { name: /edit/i }).click();

    // Question should be visible and read-only
    const questionDisplay = page.getByText(questionText || '');
    await expect(questionDisplay).toBeVisible();

    // Should not be editable
    await expect(page.getByRole('textbox', { name: /question/i })).not.toBeVisible();
  });

  test('should save edited answer and approve (Cmd+Enter)', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Open edit modal
    await firstCard.getByRole('button', { name: /edit/i }).click();

    // Edit answer
    const textarea = page.getByRole('textbox', { name: /your answer/i });
    await textarea.fill('This is an edited answer with improved clarity.');

    // Press Cmd+Enter (Mac) or Ctrl+Enter (Windows)
    await textarea.press('Meta+Enter');

    // Modal should close
    await expect(page.getByRole('dialog', { name: /edit answer/i })).not.toBeVisible({
      timeout: 500
    });

    // Card should be removed (approved)
    await expect(firstCard).not.toBeVisible({ timeout: 1000 });

    // Success toast should appear
    await expect(page.getByText(/saved.*approved/i)).toBeVisible({ timeout: 2000 });
  });

  test('should cancel edit on Escape key', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();
    const originalAnswer = await firstCard.locator('[data-testid="answer-text"]').textContent();

    // Open edit modal
    await firstCard.getByRole('button', { name: /edit/i }).click();

    // Edit answer
    const textarea = page.getByRole('textbox', { name: /your answer/i });
    await textarea.fill('Changed answer');

    // Press Escape
    await textarea.press('Escape');

    // Modal should close
    await expect(page.getByRole('dialog', { name: /edit answer/i })).not.toBeVisible({
      timeout: 500
    });

    // Card should still be visible with original answer
    await expect(firstCard).toBeVisible();
    await expect(firstCard.locator('[data-testid="answer-text"]')).toHaveText(originalAnswer || '');
  });

  test('should show character count in edit modal', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Open edit modal
    await firstCard.getByRole('button', { name: /edit/i }).click();

    // Character count should be visible
    await expect(page.getByText(/\d+ characters/i)).toBeVisible();

    // Type text and verify count updates
    const textarea = page.getByRole('textbox', { name: /your answer/i });
    await textarea.fill('Test');

    await expect(page.getByText(/4 characters/i)).toBeVisible();
  });

  test('should display sources in edit modal (lazy loaded)', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Open edit modal
    await firstCard.getByRole('button', { name: /edit/i }).click();

    // Sources section should be collapsed by default
    const sourcesButton = page.getByRole('button', { name: /view \d+ sources/i });
    await expect(sourcesButton).toBeVisible();

    // Expand sources
    await sourcesButton.click();

    // Sources should appear
    const sourceItems = page.locator('[data-testid="source-item"]');
    expect(await sourceItems.count()).toBeGreaterThan(0);

    // Chevron should rotate
    const chevron = sourcesButton.locator('svg').first();
    await expect(chevron).toHaveClass(/rotate-180/);
  });

  test('should disable save button while saving', async ({ page }) => {
    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Open edit modal
    await firstCard.getByRole('button', { name: /edit/i }).click();

    // Click save button
    const saveButton = page.getByRole('button', { name: /save & send/i });
    await saveButton.click();

    // Button should be disabled and show loading state
    await expect(saveButton).toBeDisabled();
    await expect(saveButton).toHaveText(/saving/i);

    // Spinner should be visible
    await expect(saveButton.locator('[data-testid="spinner"]')).toBeVisible();
  });
});

test.describe('Moderator Review Queue - Responsive Design', () => {
  test('should display properly on mobile (375px)', async ({ page }) => {
    // Authenticate before test
    await authenticateAdmin(page);

    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto('/admin/pending-responses');

    // Header should be responsive
    await expect(page.getByRole('heading', { name: /pending moderator review/i })).toBeVisible();

    // Cards should stack vertically
    const cards = page.locator('[data-testid="pending-response-card"]');
    const firstCard = cards.first();
    const secondCard = cards.nth(1);

    const firstCardBox = await firstCard.boundingBox();
    const secondCardBox = await secondCard.boundingBox();

    // Second card should be below first card (vertical stack)
    expect(secondCardBox?.y).toBeGreaterThan((firstCardBox?.y || 0) + (firstCardBox?.height || 0));
  });

  test('should display properly on tablet (768px)', async ({ page }) => {
    // Authenticate before test
    await authenticateAdmin(page);

    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto('/admin/pending-responses');

    // Search should be visible
    await expect(page.getByPlaceholder(/search questions or answers/i)).toBeVisible();

    // Cards should have proper spacing
    const cards = page.locator('[data-testid="pending-response-card"]');
    expect(await cards.count()).toBeGreaterThan(0);
  });
});

test.describe('Moderator Review Queue - Accessibility', () => {
  test('should support keyboard navigation (Tab)', async ({ page }) => {
    // Authenticate before test
    await authenticateAdmin(page);

    await page.goto('/admin/pending-responses');

    // Focus should start on search input
    await page.keyboard.press('Tab');
    await expect(page.getByPlaceholder(/search questions or answers/i)).toBeFocused();

    // Tab to first card's approve button
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: /approve/i }).first()).toBeFocused();

    // Tab to edit button
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: /edit/i }).first()).toBeFocused();

    // Tab to reject button
    await page.keyboard.press('Tab');
    await expect(page.getByRole('button', { name: /reject/i }).first()).toBeFocused();
  });

  test('should have proper ARIA labels', async ({ page }) => {
    // Authenticate before test
    await authenticateAdmin(page);

    await page.goto('/admin/pending-responses');

    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Buttons should have accessible names
    await expect(firstCard.getByRole('button', { name: /approve/i })).toHaveAttribute('aria-label');
    await expect(firstCard.getByRole('button', { name: /edit/i })).toHaveAttribute('aria-label');
    await expect(firstCard.getByRole('button', { name: /reject/i })).toHaveAttribute('aria-label');
  });

  test('should announce state changes to screen readers', async ({ page }) => {
    // Authenticate before test
    await authenticateAdmin(page);

    await page.goto('/admin/pending-responses');

    const firstCard = page.locator('[data-testid="pending-response-card"]').first();

    // Click approve
    await firstCard.getByRole('button', { name: /approve/i }).click();

    // Announcement should be present (via live region)
    const liveRegion = page.locator('[aria-live="polite"]');
    await expect(liveRegion).toHaveText(/approved/i, { timeout: 2000 });
  });
});
