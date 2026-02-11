import { expect, test } from "@playwright/test";

import { dismissPrivacyNotice, waitForApiReady } from "./utils/helpers";

const TEST_BASE_URL = process.env.BASE_URL || "http://localhost:3000";

test.describe("Smoke", () => {
    test("home loads and API is reachable via /api proxy", async ({ page, request }) => {
        // Ensure backend is up (direct health probe).
        await waitForApiReady(page, 60000);

        // Ensure Next.js proxy to backend works.
        const healthViaProxy = await request.get(`${TEST_BASE_URL}/api/health`);
        expect(healthViaProxy.status()).toBe(200);

        await page.goto(TEST_BASE_URL);
        await dismissPrivacyNotice(page);
        await expect(page.getByRole("textbox")).toBeVisible({ timeout: 60000 });
    });
});
