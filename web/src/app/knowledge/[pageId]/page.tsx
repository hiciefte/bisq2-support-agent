"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { SupportGuideContent, SupportGuideProjection } from "@/components/knowledge/SupportGuideContent";
import { buildApiUrl } from "@/lib/config";

export default function PublicSupportGuidePage() {
  const { pageId } = useParams<{ pageId: string }>();
  const [guide, setGuide] = useState<SupportGuideProjection | null>(null);
  const [message, setMessage] = useState("Loading support guide…");
  useEffect(() => {
    const controller = new AbortController();
    setGuide(null);
    setMessage("Loading support guide…");
    void fetch(buildApiUrl(`/public/knowledge/${encodeURIComponent(pageId)}`), {
      cache: "no-store", signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error("This support guide is not currently published.");
      const result: SupportGuideProjection = await response.json();
      if (!controller.signal.aborted) setGuide(result);
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setMessage(error instanceof Error ? error.message : "Support guide unavailable.");
    });
    return () => controller.abort();
  }, [pageId]);
  return (
    <div className="mx-auto max-w-3xl space-y-6 px-5 py-10">
      <p className="text-sm font-medium text-muted-foreground">Reviewed support guide</p>
      {guide ? <SupportGuideContent guide={guide} /> : <p role="status">{message}</p>}
      <p className="border-t pt-4 text-sm text-muted-foreground">
        Reviewed guidance from the maintained support knowledge base. Applicability matters; this is not a diagnosis of your individual case.
      </p>
    </div>
  );
}
