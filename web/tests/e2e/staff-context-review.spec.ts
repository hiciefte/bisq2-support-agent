import { expect, test } from "@playwright/test";

const baseUrl = process.env.WEB_BASE_URL || "http://localhost:3000";

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    test(`staff context review stays internal at ${viewport.width}px`, async ({ page }, testInfo) => {
        await page.setViewportSize(viewport);
        const writes: string[] = [];
        const item = {
            id: 42,
            message_id: "staff-context-fixture",
            channel: "matrix",
            user_id: "public-support-user",
            question: "Where can I open a mediation request?",
            ai_draft_answer: "AI context · Select the affected Open Trade and use Ctrl+O to request mediation.\n\n[Dispute resolution](https://bisq.wiki/Dispute_Resolution_in_Bisq_1)",
            confidence_score: 0.9,
            routing_action: "needs_human",
            routing_reason: "Staff-only context review",
            priority: "normal",
            status: "pending",
            sources: [],
            created_at: new Date().toISOString(),
            channel_metadata: {
                response_kind: "public_context",
                delivery_audience: "staff_room",
                context_status: "delivered",
                context_reason: "Documented support navigation may help staff resolve the question.",
                source_url: "https://matrix.to/#/!support:example.org/$question",
                staff_thread_url: "https://matrix.to/#/!staff:example.org/$root",
                evidence_version: "fixture-evidence-v1",
                generation_version: "fixture-context-v1",
            },
        };
        await page.route("**/*", async (route) => {
            const url = new URL(route.request().url());
            if (url.origin !== new URL(baseUrl).origin) return route.abort();
            if (!url.pathname.startsWith("/api/")) return route.continue();
            let body: unknown = {};
            if (route.request().method() !== "GET") writes.push(url.pathname);
            if (url.pathname.endsWith("/auth/status")) body = { authenticated: true };
            else if (url.pathname.endsWith("/escalations/counts")) body = { pending: 1, in_review: 0, responded: 0, closed: 0, total: 1 };
            else if (url.pathname === "/api/admin/escalations") body = { escalations: [item], total: 1, limit: 20, offset: 0 };
            else if (url.pathname.endsWith("/42/respond")) body = { status: "responded", delivery_status: "not_required" };
            else if (url.pathname.endsWith("/action-counts")) body = { pending_escalations: 1, open_escalations: 1, actionable_signals: 0, covered_signals: 0, total_signals: 0, unverified_faqs: 0, training_queue: 0 };
            await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
        });
        await page.goto(`${baseUrl}/admin/escalations`);
        await page.getByText(item.question, { exact: true }).click();
        const dialog = page.getByRole("dialog");
        await expect(dialog.getByRole("heading", { name: "Staff Context Review" })).toBeVisible();
        await expect(dialog.getByText(/cannot publish a reply to the public room/)).toBeVisible();
        await expect(dialog.getByRole("link", { name: "Open staff thread" })).toHaveAttribute("href", item.channel_metadata.staff_thread_url);
        await expect(dialog.getByRole("button", { name: "Send Response" })).toHaveCount(0);
        await expect(dialog.getByRole("button", { name: /Create FAQ/ })).toHaveCount(0);
        await expect(dialog.getByRole("button", { name: "Record approval" })).toBeVisible();
        await expect(dialog.getByText(item.question, { exact: true })).toBeVisible();
        await expect(dialog.getByText(/AI context · Select the affected Open Trade/)).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.screenshot({ path: testInfo.outputPath(`staff-context-${viewport.width}.png`), fullPage: true, animations: "disabled" });
        await dialog.getByRole("button", { name: "Record approval" }).click();
        await expect(dialog).toHaveCount(0);
        expect(writes).toEqual(["/api/admin/escalations/42/respond"]);
    });
}

for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    test(`Staff association audit stays separate from observations at ${viewport.width}px`, async ({ page }, testInfo) => {
        await page.setViewportSize(viewport);
        const fingerprint = "b".repeat(64);
        const scenarios = [
            {
                name: "confirmed",
                reason: "staff_active",
                basis: "native_relation",
                heading: "Confirmed Staff association",
                discussionReason: null,
                triggerInSnapshot: true,
                coverage: "bounded_snapshot",
                messages: [{ role: "staff", speaker: "participant-1", content: "Synthetic Staff clarification" }],
                explanation: "The triggering Staff turn is included in the bounded observed conversation.",
            },
            {
                name: "unresolved",
                reason: "staff_context_membership_unresolved",
                basis: "incident_membership_unresolved",
                heading: "Unresolved Staff association",
                discussionReason: null,
                triggerInSnapshot: false,
                coverage: "bounded_snapshot",
                messages: [{ role: "user", speaker: "requester", content: "Synthetic requester update" }],
                explanation: "The bounded observation does not include the triggering Staff turn; the saved discussion alone cannot explain this hold.",
            },
            {
                name: "unavailable",
                reason: "staff_active",
                basis: "incident_member",
                heading: "Confirmed Staff association",
                discussionReason: "source_discussion_capacity_reached",
                triggerInSnapshot: false,
                coverage: "discussion_unavailable",
                messages: [],
                explanation: "The observed conversation could not be saved. Its absence does not establish that no Staff turn occurred.",
            },
        ];
        for (const scenario of scenarios) {
            await test.step(scenario.name, async () => {
                const item = {
                    id: 42,
                    message_id: "synthetic-audit-fixture",
                    channel: "matrix",
                    user_id: "synthetic-requester",
                    question: "Why does my wallet stop synchronizing?",
                    ai_draft_answer: "",
                    confidence_score: 0,
                    routing_action: "needs_human",
                    routing_reason: "Staff-only context review",
                    priority: "normal",
                    status: "pending",
                    sources: [],
                    created_at: new Date().toISOString(),
                    channel_metadata: {
                        response_kind: "public_context",
                        context_status: "deferred",
                        context_reason: scenario.discussionReason ?? scenario.reason,
                        staff_activity_snapshot: scenario.messages,
                        staff_activity_decision: {
                            version: 1,
                            phase: "pre_generation",
                            reason: scenario.reason,
                            basis: scenario.basis,
                            trigger_event_sha256: fingerprint,
                            trigger_in_snapshot: scenario.triggerInSnapshot,
                            discussion_reason: scenario.discussionReason,
                            final_route_reason: scenario.discussionReason ?? scenario.reason,
                            coverage: scenario.coverage,
                        },
                    },
                };
                await page.unrouteAll();
                await page.route("**/*", async (route) => {
                    const url = new URL(route.request().url());
                    if (url.origin !== new URL(baseUrl).origin) return route.abort();
                    if (!url.pathname.startsWith("/api/")) return route.continue();
                    expect(route.request().method()).toBe("GET");
                    let body: unknown = {};
                    if (url.pathname.endsWith("/auth/status")) body = { authenticated: true };
                    else if (url.pathname.endsWith("/escalations/counts")) body = { pending: 1, in_review: 0, responded: 0, closed: 0, total: 1 };
                    else if (url.pathname === "/api/admin/escalations") body = { escalations: [item], total: 1, limit: 20, offset: 0 };
                    else if (url.pathname.endsWith("/action-counts")) body = { pending_escalations: 1, open_escalations: 1, actionable_signals: 0, covered_signals: 0, total_signals: 0, unverified_faqs: 0, training_queue: 0 };
                    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
                });
                await page.goto(`${baseUrl}/admin/escalations`);
                await page.getByText(item.question, { exact: true }).click();
                const dialog = page.getByRole("dialog");
                const audit = dialog.getByRole("region", { name: "Recorded Staff association" });
                await expect(audit.getByRole("heading", { name: scenario.heading })).toBeVisible();
                await expect(audit.getByText(scenario.explanation)).toBeVisible();
                await expect(dialog).not.toContainText(fingerprint);
                await expect(dialog.getByText(item.question, { exact: true })).toBeVisible();
                if (scenario.messages.length) {
                    await dialog.getByText("Conversation observed when the reply was held").click();
                    await expect(dialog.getByText(scenario.messages[0].content)).toBeVisible();
                    await expect(audit).not.toContainText(scenario.messages[0].content);
                } else {
                    await expect(dialog.getByText("Conversation observed when the reply was held")).toHaveCount(0);
                }
                expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
                await page.screenshot({ path: testInfo.outputPath(`staff-audit-${scenario.name}-${viewport.width}.png`), fullPage: true, animations: "disabled" });
            });
        }
    });
}
