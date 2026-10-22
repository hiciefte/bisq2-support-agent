import { expect, test } from "@playwright/test";

const baseUrl = process.env.WEB_BASE_URL || "http://localhost:3000";

for (const width of [1440, 390]) {
    test(`review links locate exact cases without a review mutation at ${width}px`, async ({ page }, testInfo) => {
        await page.setViewportSize({ width, height: 900 });
        const writes: string[] = [];
        const searches: string[] = [];
        await page.route("**/*", async (route) => {
            const request = route.request();
            const url = new URL(request.url());
            if (url.origin !== new URL(baseUrl).origin) return route.abort();
            if (!url.pathname.startsWith("/api/")) return route.continue();
            if (request.method() !== "GET") writes.push(url.pathname);
            let body: unknown = {};
            if (url.pathname.endsWith("/auth/status")) body = { authenticated: true };
            else if (url.pathname.endsWith("/escalations/counts")) body = { pending: 2, in_review: 0, responded: 0, closed: 0, total: 2 };
            else if (url.pathname === "/api/admin/escalations") {
                const search = url.searchParams.get("search") || "";
                searches.push(search);
                const id = search === "#43" ? 43 : 42;
                body = { escalations: [{
                    id, message_id: `fixture-${id}`, channel: "matrix", user_id: "synthetic-user",
                    question: `Synthetic review question ${id}`, ai_draft_answer: "", confidence_score: 0,
                    routing_action: "needs_human", routing_reason: "conversation_membership_unresolved",
                    priority: "normal", status: "pending", sources: [], created_at: new Date().toISOString(),
                    channel_metadata: { response_kind: "public_context", delivery_audience: "staff_room",
                        context_status: "deferred", context_reason: "conversation_membership_unresolved",
                        candidate_conversation_ids: id === 42 ? [43] : [],
                        staff_activity_snapshot: [
                            { role: "user", speaker: "requester", content: "Synthetic updater issue." },
                            { role: "staff", speaker: "participant-1", content: "Which version are you using?" },
                        ] },
                }], total: 1, limit: 20, offset: 0 };
            } else if (url.pathname.endsWith("/action-counts")) body = { pending_escalations: 2, open_escalations: 2 };
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
        });
        await page.goto(`${baseUrl}/admin/escalations?search=%2342`);
        await expect(page.getByPlaceholder("Search text or #case ID...")).toHaveValue("#42");
        await expect(page.getByText("Case #42", { exact: true })).toBeVisible();
        await page.getByText("Synthetic review question 42", { exact: true }).click();
        const link = page.getByRole("link", { name: "Review case #43" });
        await expect(link).toHaveAttribute("href", "/admin/escalations?search=%2343");
        await page.getByText("Conversation observed when the reply was held", { exact: true }).click();
        await expect(page.getByText("Staff (participant-1)", { exact: true })).toBeVisible();
        await expect(page.getByText(/not proof of what the AI saw/)).toBeVisible();
        await page.screenshot({ path: testInfo.outputPath(`related-case-${width}.png`), fullPage: true, animations: "disabled" });
        await link.click();
        await expect(page.getByPlaceholder("Search text or #case ID...")).toHaveValue("#43");
        await expect(page.getByText("Case #43", { exact: true })).toBeVisible();
        await expect(page.getByRole("dialog")).toHaveCount(0);
        expect(searches).toContain("#42");
        expect(searches).toContain("#43");
        expect(writes).toEqual([]);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`case-queue-${width}.png`), fullPage: true, animations: "disabled" });
    });
}
