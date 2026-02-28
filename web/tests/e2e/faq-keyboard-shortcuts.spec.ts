import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { selectCategory, API_BASE_URL, ADMIN_API_KEY, WEB_BASE_URL, waitForApiReady } from "./utils";

/**
 * FAQ Keyboard Shortcuts Tests
 *
 * Tests for the new keyboard shortcut behavior:
 * - US-006: Enter key to enter edit mode (changed from E)
 * - US-001: Stay on current FAQ after save
 * - US-002: Jump to next unverified FAQ after V
 * - US-003: Protocol keyboard shortcuts (1/E/M/0)
 */

test.describe("FAQ Keyboard Shortcuts", () => {
    // Match timeout from working faq-management.spec.ts
    test.setTimeout(90000);

    // Base selector for FAQ cards (without border-border since it changes when selected)
    const FAQ_CARD_SELECTOR = ".bg-card.border.rounded-lg";
    // Selector for selected FAQ cards (has ring-2 when selected)
    const SELECTED_FAQ_CARD_SELECTOR = ".bg-card.rounded-lg.ring-2";
    const createdFaqQuestions: string[] = [];

    // Setup: Login and navigate to FAQ management before each test
    // Handles both fresh login and already-logged-in scenarios
    test.beforeEach(async ({ page, context, request }) => {
        // Clear cookies to ensure clean authentication state
        await context.clearCookies();

        // Wait for API to be ready (important after container restart tests)
        await waitForApiReady(request);

        // Retry navigation with exponential backoff for flaky server startup
        let lastError: Error | null = null;
        for (let attempt = 1; attempt <= 3; attempt++) {
            try {
                // Navigate to admin page using domcontentloaded (more reliable than networkidle)
                await page.goto(`${WEB_BASE_URL}/admin`, {
                    waitUntil: 'domcontentloaded',
                    timeout: 20000
                });

                // Wait for login form to appear
                await page.waitForSelector('input[type="password"]', { timeout: 15000 });

                // Login with admin API key
                await page.fill('input[type="password"]', ADMIN_API_KEY);
                await page.click('button:has-text("Login")');

                // Wait for authenticated UI to appear (sidebar with navigation)
                await page.waitForSelector("nav a[href='/admin/overview']", { timeout: 15000 });

                // Navigate to FAQ management
                await page.click('a[href="/admin/manage-faqs"]');

                // Wait for FAQ management page to load - look for specific heading
                // Use longer timeout as Next.js may need to compile the page (8-15s first time)
                await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 30000 });

                // Wait for either FAQ cards to appear OR "Add New FAQ" button (if no FAQs exist)
                // Use Promise.any to ensure at least one selector is found (rejects only if all fail)
                await Promise.any([
                    page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 5000 }),
                    page.waitForSelector('button:has-text("Add New FAQ")', { timeout: 5000 }),
                ]);

                // Success - exit retry loop
                lastError = null;
                break;
            } catch (error) {
                lastError = error as Error;
                console.log(`Attempt ${attempt}/3 failed: ${lastError.message}`);
                if (attempt < 3) {
                    // Clear cookies between retries to ensure clean state
                    await context.clearCookies();
                    // Wait before retry with exponential backoff
                    await new Promise(r => setTimeout(r, attempt * 2000));
                }
            }
        }

        if (lastError) {
            throw lastError;
        }
    });

    // Helper to create FAQ via API for faster test setup
    const createFaqViaApi = async (
        request: any,
        question: string,
        answer: string,
        options: { verified?: boolean; protocol?: string } = {}
    ) => {
        const response = await request.post(`${API_BASE_URL}/admin/faqs`, {
            headers: {
                "x-api-key": ADMIN_API_KEY,
                "Content-Type": "application/json",
            },
            data: {
                question,
                answer,
                category: "General",
                source: "Manual",
                verified: options.verified ?? false,
                protocol: options.protocol,
            },
        });

        if (response.ok()) {
            createdFaqQuestions.push(question);
            return await response.json();
        }
        return null;
    };

    const getSelectedFaqQuestion = async (page: Page): Promise<string> => {
        const selectedCard = page.locator(SELECTED_FAQ_CARD_SELECTOR).first();
        await expect(selectedCard).toBeVisible({ timeout: 5000 });
        return (await selectedCard.locator("h3").first().innerText()).trim();
    };

    test.afterEach(async ({ request }) => {
        // Clean up created FAQs
        for (const question of createdFaqQuestions) {
            try {
                const response = await request.get(`${API_BASE_URL}/admin/faqs`, {
                    headers: { "x-api-key": ADMIN_API_KEY },
                });

                if (response.ok()) {
                    const data = await response.json();
                    const faq = data.faqs?.find((f: any) => f.question === question);
                    if (faq) {
                        await request.delete(`${API_BASE_URL}/admin/faqs/${faq.id}`, {
                            headers: { "x-api-key": ADMIN_API_KEY },
                        });
                    }
                }
            } catch (error) {
                console.log(`Cleanup failed for FAQ: ${question}`, error);
            }
        }
        createdFaqQuestions.splice(0);
    });

    test.describe("US-006: Enter key to enter edit mode", () => {
        test("should enter edit mode when pressing Enter on selected FAQ", async ({ page, request }) => {
            // Create a test FAQ
            const testQuestion = `Enter Edit Test ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer for edit mode");

            // Reload page to show the newly created FAQ (same pattern as faq-management.spec.ts)
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Press J to select first FAQ
            await page.keyboard.press("j");

            // Press Enter to enter edit mode
            await page.keyboard.press("Enter");

            // Verify edit mode is active (textarea should be visible)
            const textarea = page.locator("textarea").first();
            await expect(textarea).toBeVisible({ timeout: 5000 });
        });

        test("should NOT enter edit mode when pressing E on selected FAQ (E is now for protocol)", async ({ page, request }) => {
            const testQuestion = `E Key Protocol Test ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer");

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Press J to select first FAQ
            await page.keyboard.press("j");

            // Press E - should NOT enter edit mode anymore
            await page.keyboard.press("e");

            // Give it a moment to potentially open edit mode
            await page.waitForTimeout(500);

            // Verify edit mode is NOT active (no textarea visible in edit context)
            // Note: There might be textareas elsewhere, so we check for the inline edit specific pattern
            const saveButton = page.locator('button:has-text("Save")');
            await expect(saveButton).toHaveCount(0);
        });
    });

    test.describe("US-001: Stay on current FAQ after save", () => {
        test("should stay on current FAQ after saving edit", async ({ page, request }) => {
            // Create two test FAQs
            const faq1Question = `Stay After Save FAQ 1 - ${Date.now()}`;
            const faq2Question = `Stay After Save FAQ 2 - ${Date.now()}`;
            await createFaqViaApi(request, faq1Question, "First FAQ answer");
            await createFaqViaApi(request, faq2Question, "Second FAQ answer");

            // Reload page to show the newly created FAQs
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search to filter to our test FAQs
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill("Stay After Save FAQ");
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Blur the search input by clicking on the page title
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Use keyboard navigation to select the first FAQ
            await page.keyboard.press("j");
            await page.waitForTimeout(200);

            // Enter edit mode using Enter key
            await page.keyboard.press("Enter");

            // Wait for edit mode
            const textarea = page.locator("textarea").first();
            await expect(textarea).toBeVisible({ timeout: 5000 });

            // Make a small edit
            await textarea.fill("First FAQ answer - edited");

            // Save
            const saveButton = page.getByRole("button", { name: "Save", exact: true });
            await saveButton.click();

            // Wait for save to complete
            await expect(saveButton).toBeHidden({ timeout: 15000 });

            // Verify the first FAQ is still highlighted/selected (has ring styling)
            // The selected FAQ should have the ring-2 class indicating selection
            const selectedCard = page.locator(`${SELECTED_FAQ_CARD_SELECTOR}:has-text("${faq1Question}")`);
            await expect(selectedCard).toBeVisible({ timeout: 5000 });
        });
    });

    test.describe("US-002: Jump to next unverified after V", () => {
        test("should jump to next unverified FAQ after verifying with V", async ({ page, request }) => {
            // Create FAQs: unverified, verified, unverified
            const faq1Question = `Verify Jump Test 1 - ${Date.now()}`;
            const faq2Question = `Verify Jump Test 2 - ${Date.now()}`;
            const faq3Question = `Verify Jump Test 3 - ${Date.now()}`;

            await createFaqViaApi(request, faq1Question, "First FAQ - unverified", { verified: false });
            await createFaqViaApi(request, faq2Question, "Second FAQ - verified", { verified: true });
            await createFaqViaApi(request, faq3Question, "Third FAQ - unverified", { verified: false });

            // Reload page to show the newly created FAQs
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Filter to show only our test FAQs by searching
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill("Verify Jump Test");
            await page.waitForTimeout(1000); // Wait for debounce

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Select FAQ 1 explicitly (ordering can vary in search results)
            const faq1Card = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${faq1Question}")`).first();
            await faq1Card.click();
            const selectedBefore = await getSelectedFaqQuestion(page);
            expect(selectedBefore).toBe(faq1Question);

            // Press V to verify
            await page.keyboard.press("v");

            // Handle confirmation dialog if present
            const dialog = page.getByRole("alertdialog");
            const dialogVisible = await dialog.isVisible().catch(() => false);
            if (dialogVisible) {
                const confirmButton = dialog.getByRole("button", { name: "Verify FAQ" });
                await confirmButton.click();
                await dialog.waitFor({ state: "hidden", timeout: 5000 });
            }

            // After verify, selection should jump to the next unverified FAQ (FAQ 3)
            // FAQ 2 is already verified, so it should be skipped.
            await expect
                .poll(async () => getSelectedFaqQuestion(page), { timeout: 5000 })
                .toBe(faq3Question);
        });

        test("should stay on current FAQ if no more unverified FAQs", async ({ page, request }) => {
            // Create only one unverified FAQ
            const faqQuestion = `Last Unverified Test - ${Date.now()}`;
            await createFaqViaApi(request, faqQuestion, "Only unverified FAQ", { verified: false });

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(faqQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Select the FAQ
            await page.keyboard.press("j");

            // Press V to verify
            await page.keyboard.press("v");

            // Handle confirmation dialog
            const dialog = page.getByRole("alertdialog");
            const dialogVisible = await dialog.isVisible().catch(() => false);
            if (dialogVisible) {
                const confirmButton = dialog.getByRole("button", { name: "Verify FAQ" });
                await confirmButton.click();
                await dialog.waitFor({ state: "hidden", timeout: 5000 });
            }

            // Should still be on the same FAQ (now verified)
            await page.waitForTimeout(500);
            const faqSelected = page.locator(`${SELECTED_FAQ_CARD_SELECTOR}:has-text("${faqQuestion}")`);
            await expect(faqSelected).toBeVisible({ timeout: 5000 });
        });
    });

    test.describe("US-003: Protocol keyboard shortcuts", () => {
        test("should set protocol to Multisig v1 when pressing 1", async ({ page, request }) => {
            const testQuestion = `Protocol 1 Test - ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer for protocol");

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Select the FAQ
            await page.keyboard.press("j");

            // Press 1 to set protocol to Multisig v1
            await page.keyboard.press("1");

            // Wait for update and check for toast or badge update
            await page.waitForTimeout(1000);

            // Verify the protocol badge shows Multisig v1
            const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
            const protocolBadge = faqCard.locator('text=Multisig');
            await expect(protocolBadge).toBeVisible({ timeout: 5000 });
        });

        test("should set protocol to Bisq Easy when pressing E", async ({ page, request }) => {
            const testQuestion = `Protocol E Test - ${Date.now()}`;
            // Start with a different protocol to verify change
            await createFaqViaApi(request, testQuestion, "Test answer", { protocol: "multisig_v1" });

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            await page.keyboard.press("j");
            await page.keyboard.press("e");

            await page.waitForTimeout(1000);

            const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
            const protocolBadge = faqCard.locator('text=Bisq Easy');
            await expect(protocolBadge).toBeVisible({ timeout: 5000 });
        });

        test("should set protocol to MuSig when pressing M", async ({ page, request }) => {
            const testQuestion = `Protocol M Test - ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer");

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            await page.keyboard.press("j");
            await page.keyboard.press("m");

            await page.waitForTimeout(1000);

            const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
            const protocolBadge = faqCard.locator('text=MuSig');
            await expect(protocolBadge).toBeVisible({ timeout: 5000 });
        });

        test("should set protocol to All when pressing 0", async ({ page, request }) => {
            const testQuestion = `Protocol 0 Test - ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer", { protocol: "bisq_easy" });

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            await page.keyboard.press("j");
            await page.keyboard.press("0");

            await page.waitForTimeout(1000);

            const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
            // "All" protocol might show differently - check for the badge
            const protocolBadge = faqCard.locator('[data-testid="protocol-badge"]');
            await expect(protocolBadge).toContainText(/All/i, { timeout: 5000 });
        });

        test("should not change protocol when in edit mode", async ({ page, request }) => {
            const testQuestion = `Protocol Edit Mode Test - ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer", { protocol: "bisq_easy" });

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input by clicking on the page title
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Select and enter edit mode
            await page.keyboard.press("j");
            await page.keyboard.press("Enter");

            // Wait for edit mode
            const textarea = page.locator("textarea").first();
            await expect(textarea).toBeVisible({ timeout: 5000 });

            // Click on textarea to focus it first
            await textarea.click();
            await page.waitForTimeout(100);

            // Press 1 - should type "1" in the field, not change protocol
            await page.keyboard.press("1");

            // Verify "1" was typed, not protocol changed
            await expect(textarea).toHaveValue(/1/);

            // Cancel edit
            await page.keyboard.press("Escape");
        });
    });

    test.describe("US-007: Protocol dropdown in Edit mode", () => {
        test("should display Protocol dropdown in Edit FAQ form", async ({ page, request }) => {
            const testQuestion = `Edit Protocol Dropdown Test - ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer", { protocol: "bisq_easy" });

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            // Wait for FAQs to appear and blur the search input
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Select and enter edit mode
            await page.keyboard.press("j");
            await page.keyboard.press("Enter");

            // Wait for edit mode
            const textarea = page.locator("textarea").first();
            await expect(textarea).toBeVisible({ timeout: 5000 });

            // Verify Protocol dropdown is visible in edit form
            const protocolDropdown = page.locator('button[role="combobox"]:has-text("Bisq Easy")');
            await expect(protocolDropdown).toBeVisible({ timeout: 5000 });

            // Cancel edit
            await page.keyboard.press("Escape");
        });

        test("should change protocol via dropdown and persist after save", async ({ page, request }) => {
            const testQuestion = `Change Protocol via Dropdown - ${Date.now()}`;
            await createFaqViaApi(request, testQuestion, "Test answer for protocol change", { protocol: "bisq_easy" });

            // Reload page to show the newly created FAQ
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search for the EXACT question to avoid matching leftover test data
            const searchInput = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInput.fill(testQuestion);
            await page.waitForTimeout(1000);

            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });
            await page.locator('h1:has-text("FAQ Management")').click();
            await page.waitForTimeout(200);

            // Select and enter edit mode
            await page.keyboard.press("j");
            await page.keyboard.press("Enter");

            // Wait for edit mode
            const textarea = page.locator("textarea").first();
            await expect(textarea).toBeVisible({ timeout: 5000 });

            // Click on Protocol dropdown to open it
            const protocolDropdown = page
                .locator('button[role="combobox"]')
                .filter({ hasText: /Bisq Easy/i })
                .first();
            await protocolDropdown.scrollIntoViewIfNeeded();
            await protocolDropdown.click();

            // Select via DOM click on the currently visible Radix option.
            // This avoids viewport instability when Playwright clicks portal options.
            await page.evaluate(() => {
                const options = Array.from(
                    document.querySelectorAll<HTMLElement>('[role="option"]')
                );
                const inViewport = (el: HTMLElement) => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
                };
                const target =
                    options.find((el) => el.textContent?.includes("Bisq 1 (Multisig)") && inViewport(el)) ??
                    options.find((el) => el.textContent?.includes("Bisq 1 (Multisig)"));

                if (!target) {
                    throw new Error("Could not find Bisq 1 (Multisig) option in protocol dropdown");
                }
                target.click();
            });

            await expect(
                page
                    .locator('button[role="combobox"]')
                    .filter({ hasText: /Bisq 1|Multisig/i })
                    .first()
            ).toBeVisible({ timeout: 5000 });

            // Save the changes
            const saveButton = page.getByRole("button", { name: "Save", exact: true });
            await saveButton.click();

            // Wait for save to complete
            await expect(saveButton).toBeHidden({ timeout: 15000 });

            // Verify the protocol badge shows Multisig on the FAQ card
            const faqCard = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
            const protocolBadge = faqCard.locator('text=Multisig');
            await expect(protocolBadge).toBeVisible({ timeout: 5000 });

            // Reload page to verify persistence
            await page.reload();
            await page.waitForSelector('h1:has-text("FAQ Management")', { timeout: 10000 });
            await page.waitForSelector(FAQ_CARD_SELECTOR, { timeout: 10000 });

            // Search again - need to re-query the search input after reload
            const searchInputAfterReload = page.locator('input[placeholder="Search FAQs... (/)"]');
            await searchInputAfterReload.fill("Change Protocol via Dropdown");
            await page.waitForTimeout(1000);

            // Verify protocol is still Multisig after reload
            const faqCardAfterReload = page.locator(`${FAQ_CARD_SELECTOR}:has-text("${testQuestion}")`);
            const protocolBadgeAfterReload = faqCardAfterReload.locator('text=Multisig');
            await expect(protocolBadgeAfterReload).toBeVisible({ timeout: 5000 });
        });
    });
});
