"use client";

import { Button } from "@/components/ui/button";

export default function SecurityAlertsError({ reset }: { reset: () => void }) {
  return (
    <div className="p-4 md:p-8 pt-16 lg:pt-8">
      <div className="mx-auto max-w-3xl rounded-2xl border border-red-500/30 bg-red-500/5 p-6 text-sm text-red-200">
        <div className="text-lg font-semibold">Security alerts failed to load</div>
        <p className="mt-2 text-red-200/90">
          The trust-monitor admin route could not be rendered. Retry once, then inspect the API route if this persists.
        </p>
        <Button className="mt-4" variant="outline" onClick={reset}>Retry</Button>
      </div>
    </div>
  );
}
