"use client";

import { useState, useEffect, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { AlertCircle, Loader2, RotateCcw } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { makeAuthenticatedRequest } from "@/lib/auth";

interface RebuildStatus {
  needs_rebuild: boolean;
  rebuild_in_progress: boolean;
  pending_changes_count: number;
  last_rebuild_time: number | null;
}

export function VectorStoreStatusBanner() {
  const [status, setStatus] = useState<RebuildStatus | null>(null);
  const [isRebuilding, setIsRebuilding] = useState(false);
  const { toast } = useToast();

  // Memoized fetchStatus to prevent stale closures and ESLint warnings
  const fetchStatus = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await makeAuthenticatedRequest("/admin/vectorstore/status", { signal });
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
        setIsRebuilding(data.rebuild_in_progress);
      }
    } catch (error: unknown) {
      // Ignore cancelled requests
      if (error && typeof error === 'object' && 'name' in error && error.name === 'AbortError') {
        return;
      }
      console.error("Failed to fetch vector store status:", error);
    }
  }, []); // No dependencies - uses only stable APIs

  // Poll status every 5 seconds when component is mounted
  useEffect(() => {
    const abortController = new AbortController();

    // Initial fetch
    fetchStatus(abortController.signal);

    // Set up polling interval
    const interval = setInterval(() => fetchStatus(abortController.signal), 5000);

    return () => {
      clearInterval(interval);
      abortController.abort();
    };
  }, [fetchStatus]);

  async function handleRebuild() {
    setIsRebuilding(true);

    try {
      const response = await makeAuthenticatedRequest("/admin/vectorstore/rebuild", {
        method: "POST",
      });

      if (response.ok) {
        const result = await response.json();

        if (result.success) {
          // Success toast
          toast({
            title: "Support agent updated",
            description: `Applied ${result.changes_applied || 0} changes${result.rebuild_time ? ` in ${result.rebuild_time.toFixed(1)}s` : ''}`,
            duration: 4000,
          });

          // Refresh status to hide banner
          await fetchStatus();
        } else {
          // Error toast
          toast({
            title: "Update failed",
            description: result.error || "Failed to update support agent",
            variant: "destructive",
            duration: 5000,
          });
        }
      } else {
        throw new Error("Rebuild request failed");
      }
    } catch (error) {
      console.error("Failed to trigger rebuild:", error);
      toast({
        title: "Update failed",
        description: "Network error - please try again",
        variant: "destructive",
        duration: 5000,
      });
    } finally {
      setIsRebuilding(false);
    }
  }

  // Don't show banner if no rebuild needed and not currently rebuilding
  if (!status?.needs_rebuild && !isRebuilding) {
    return null;
  }

  return (
    <div
      className="sticky top-0 z-50 bg-amber-50 shadow-sm dark:bg-amber-900/10 dark:shadow-amber-950/20"
      role="status"
      aria-live="polite"
    >
      <div className="container mx-auto flex items-center justify-between px-4 py-3">
        {/* Left: Status message */}
        <div className="flex items-center gap-3">
          <AlertCircle className="h-5 w-5 flex-shrink-0 text-amber-600 dark:text-amber-500" />
          <div className="min-w-0">
            <p className="text-sm font-medium text-amber-900 dark:text-amber-100">
              Support agent needs update
            </p>
            <p className="text-xs text-amber-700 dark:text-amber-300">
              {status?.pending_changes_count || 0} pending change
              {status?.pending_changes_count !== 1 ? "s" : ""}
            </p>
          </div>
        </div>

        {/* Right: Action button */}
        <Button
          onClick={handleRebuild}
          disabled={isRebuilding}
          aria-label={isRebuilding ? "Updating support agent" : "Update support agent now"}
          size="sm"
          className="ml-4 flex-shrink-0 bg-amber-600 text-white hover:bg-amber-700 dark:bg-amber-700 dark:hover:bg-amber-600"
        >
          {isRebuilding ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Updating...
            </>
          ) : (
            <>
              <RotateCcw className="mr-2 h-4 w-4" />
              Update Now
            </>
          )}
        </Button>
      </div>
    </div>
  );
}
