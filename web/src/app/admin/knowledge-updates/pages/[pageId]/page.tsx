"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { GuideMarkdown, SupportGuideContent, SupportGuideProjection } from "@/components/knowledge/SupportGuideContent";
import { makeAuthenticatedRequest } from "@/lib/auth";

interface InternalGuide {
  page_id: string;
  title: string;
  protocol: string;
  status: string;
  body: string;
  projection: SupportGuideProjection | null;
  public: boolean;
  can_publish: boolean;
  publication_history: { action: string; revision: string; reviewer: string; created_at: string }[];
}

export default function InternalSupportGuidePage() {
  const { pageId } = useParams<{ pageId: string }>();
  const [guide, setGuide] = useState<InternalGuide | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reviewed, setReviewed] = useState(false);
  const endpoint = `/admin/knowledge-updates/pages/${encodeURIComponent(pageId)}`;
  const load = useCallback(async () => {
    setReviewed(false);
    const response = await makeAuthenticatedRequest(endpoint, { cache: "no-store" });
    if (!response.ok) throw new Error("Internal support guide unavailable.");
    setGuide(await response.json());
  }, [endpoint]);
  useEffect(() => {
    setGuide(null);
    void load().catch((error: unknown) => setError(error instanceof Error ? error.message : "Unable to load guide."));
  }, [load]);
  const publish = async (action: "publish" | "revoke") => {
    if (!guide || (action === "publish" && (!reviewed || !guide.projection))) return;
    setBusy(true);
    setError("");
    try {
      const response = await makeAuthenticatedRequest(`${endpoint}/${action}`, {
        method: "POST",
        body: JSON.stringify(action === "publish" ? { revision: guide.projection?.revision } : {}),
      });
      if (!response.ok) throw new Error("Publication did not complete. Reload and review the current preview before trying again.");
      await load();
    } catch (error: unknown) {
      setReviewed(false);
      setError(error instanceof Error ? error.message : "Publication status unavailable.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mx-auto max-w-4xl space-y-7 p-5 md:p-8">
      <Link className="text-sm underline" href="/admin/knowledge-updates">Back to knowledge updates</Link>
      <header><h1 className="text-2xl font-semibold">Internal support guide</h1><p className="mt-2 text-muted-foreground">{guide?.title}</p></header>
      {error && <p role="alert" className="text-destructive">{error}</p>}
      {!guide ? <p role="status">Loading guide…</p> : <>
        <p role="status">Public view: {guide.public ? "Published" : "Private or changed since publication"}. Internal status: {guide.status}.</p>
        <details className="rounded-lg border p-4">
          <summary className="cursor-pointer font-medium">Inspect complete internal guidance</summary>
          <div className="mt-4"><GuideMarkdown>{guide.body}</GuideMarkdown></div>
        </details>
        <section className="space-y-5 rounded-lg border p-5">
          <h2 className="text-xl font-semibold">Public preview</h2>
          <p className="text-sm text-muted-foreground">Only the answer and applicability below can be published. Review for private case details and unsupported claims. Internal review notes and page bibliographies are excluded.</p>
          {guide.projection ? <SupportGuideContent guide={guide.projection} preview /> : <p>A canonical answer and applicability section are required.</p>}
          <label className="flex items-start gap-3 text-sm"><input type="checkbox" checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} disabled={busy || !guide.can_publish} className="mt-1" />I reviewed this exact public preview for accuracy, product scope, and private information.</label>
          <div className="flex flex-wrap gap-3">
            <Button disabled={busy || !reviewed || !guide.can_publish} onClick={() => void publish("publish")}>Publish reviewed view</Button>
            <Button variant="outline" disabled={busy || guide.publication_history[0]?.action !== "publish"} onClick={() => void publish("revoke")}>Make private</Button>
            {guide.public && <Link href={`/knowledge/${encodeURIComponent(pageId)}`} className="self-center text-sm underline">Open public view</Link>}
          </div>
        </section>
        <details className="rounded-lg border p-4"><summary className="cursor-pointer font-medium">Publication history ({guide.publication_history.length})</summary><ul className="mt-3 space-y-2 text-sm">{guide.publication_history.map((event, index) => <li key={`${event.created_at}-${index}`}>{event.action} · {event.created_at} · {event.reviewer}</li>)}</ul></details>
      </>}
    </div>
  );
}
