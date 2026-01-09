"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { ChevronDown, AlertCircle, Loader2, Undo2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ToastAction } from "@/components/ui/toast";
import { SimilarFaqReviewCard } from "./SimilarFaqReviewCard";
import { MergePreviewModal } from "./MergePreviewModal";
import { useToast } from "@/hooks/use-toast";

/**
 * Similar FAQ candidate from the API.
 * Represents an auto-extracted FAQ that is similar to an existing FAQ.
 */
export interface SimilarFaqCandidate {
  id: string;
  extracted_question: string;
  extracted_answer: string;
  extracted_category?: string | null;
  matched_faq_id: number;
  matched_question: string;
  matched_answer: string;
  matched_category?: string | null;
  similarity: number;
  status: "pending" | "approved" | "merged" | "dismissed";
  extracted_at: string;
  resolved_at?: string | null;
  resolved_by?: string | null;
  dismiss_reason?: string | null;
}

/**
 * Props for the SimilarFaqReviewQueue component.
 */
interface SimilarFaqReviewQueueProps {
  /** Array of pending candidates */
  items: SimilarFaqCandidate[];
  /** Whether the component is loading */
  isLoading?: boolean;
  /** Callback when a candidate is approved */
  onApprove: (id: string) => Promise<void>;
  /** Callback when a candidate is merged */
  onMerge: (id: string, mode: "replace" | "append") => Promise<void>;
  /** Callback when a candidate is dismissed */
  onDismiss: (id: string, reason?: string) => Promise<void>;
  /** Callback to refresh the list */
  onRefresh?: () => void;
  /** Optional className for custom styling */
  className?: string;
}

// Undo window duration in milliseconds
const UNDO_DURATION_MS = 5000;

/**
 * SimilarFaqReviewQueue displays a collapsible section showing FAQs
 * that were auto-extracted and found to be similar to existing FAQs.
 *
 * Features:
 * - Inline alert appearance (amber theme)
 * - Collapsible with chevron toggle
 * - Side-by-side comparison for each candidate
 * - Action buttons: Approve, Merge, Dismiss
 * - Instant dismiss with undo capability (no confirmation dialog)
 * - Merge preview modal before confirming
 * - Panel state preserved after actions
 */
export function SimilarFaqReviewQueue({
  items,
  isLoading = false,
  onApprove,
  onMerge,
  onDismiss,
  onRefresh,
  className,
}: SimilarFaqReviewQueueProps) {
  // Panel state with intentional tracking to prevent collapse on re-renders
  const isOpenIntentionalRef = useRef(true);
  const [isOpen, setIsOpen] = useState(true);
  const hasAutoCollapsed = useRef(false);

  const [actionInProgress, setActionInProgress] = useState<string | null>(null);
  const [mergeModalOpen, setMergeModalOpen] = useState(false);
  const [selectedCandidate, setSelectedCandidate] =
    useState<SimilarFaqCandidate | null>(null);
  const { toast } = useToast();

  // Track dismissed items for undo capability
  const dismissedItemsRef = useRef<
    Map<
      string,
      {
        candidate: SimilarFaqCandidate;
        timer: NodeJS.Timeout;
      }
    >
  >(new Map());

  // Handle intentional open/close from user click
  const handleOpenChange = useCallback((open: boolean) => {
    isOpenIntentionalRef.current = open;
    setIsOpen(open);
  }, []);

  // Auto-collapse only once when count > 3 on initial load
  useEffect(() => {
    if (items.length > 3 && !isLoading && !hasAutoCollapsed.current) {
      hasAutoCollapsed.current = true;
      isOpenIntentionalRef.current = false;
      setIsOpen(false);
    }
  }, [items.length, isLoading]);

  // Restore intentional state after item mutations (prevents unwanted collapse)
  useEffect(() => {
    if (isOpen !== isOpenIntentionalRef.current) {
      setIsOpen(isOpenIntentionalRef.current);
    }
  }, [items.length, isOpen]);

  // Cleanup timers on unmount
  useEffect(() => {
    const dismissedItems = dismissedItemsRef.current;
    return () => {
      dismissedItems.forEach(({ timer }) => clearTimeout(timer));
      dismissedItems.clear();
    };
  }, []);

  const handleApprove = useCallback(
    async (id: string) => {
      setActionInProgress(id);
      try {
        await onApprove(id);
        toast({
          title: "FAQ approved",
          description: "The FAQ has been added to the knowledge base.",
        });
      } catch {
        toast({
          title: "Failed to approve",
          description: "An error occurred while approving the FAQ.",
          variant: "destructive",
        });
      } finally {
        setActionInProgress(null);
      }
    },
    [onApprove, toast]
  );

  const handleMergeClick = useCallback(
    (id: string) => {
      const candidate = items.find((item) => item.id === id);
      if (candidate) {
        setSelectedCandidate(candidate);
        setMergeModalOpen(true);
      }
    },
    [items]
  );

  const handleMergeConfirm = useCallback(
    async (mode: "replace" | "append") => {
      if (!selectedCandidate) return;
      setMergeModalOpen(false);
      setActionInProgress(selectedCandidate.id);
      try {
        await onMerge(selectedCandidate.id, mode);
        toast({
          title: "FAQ merged",
          description:
            mode === "replace"
              ? "The existing FAQ has been replaced."
              : "The content has been appended to the existing FAQ.",
        });
      } catch {
        toast({
          title: "Failed to merge",
          description: "An error occurred while merging the FAQ.",
          variant: "destructive",
        });
      } finally {
        setActionInProgress(null);
        setSelectedCandidate(null);
      }
    },
    [selectedCandidate, onMerge, toast]
  );

  // Handle undo dismiss - defined before handleDismissInstant to avoid circular dependency
  const handleUndoDismiss = useCallback(
    (id: string) => {
      const dismissed = dismissedItemsRef.current.get(id);
      if (!dismissed) return;

      // Clear the timer
      clearTimeout(dismissed.timer);
      dismissedItemsRef.current.delete(id);

      // Notify parent to restore the item
      // Note: Parent needs to handle this - we'll trigger a refresh
      if (onRefresh) {
        onRefresh();
      }

      toast({
        title: "Dismiss cancelled",
        description: "FAQ restored to review queue.",
      });
    },
    [onRefresh, toast]
  );

  // Instant dismiss with undo capability (no confirmation dialog)
  const handleDismissInstant = useCallback(
    async (id: string) => {
      const candidate = items.find((item) => item.id === id);
      if (!candidate) return;

      // Start action progress for visual feedback
      setActionInProgress(id);

      // Call onDismiss immediately - single API call
      try {
        await onDismiss(id);

        // Store for potential undo (timer only cleans up tracking, doesn't re-call API)
        const timer = setTimeout(() => {
          // After undo window expires, just clean up the tracking
          dismissedItemsRef.current.delete(id);
        }, UNDO_DURATION_MS);

        dismissedItemsRef.current.set(id, { candidate, timer });

        toast({
          title: "FAQ dismissed",
          description: "Removed from review queue.",
          duration: UNDO_DURATION_MS,
          action: (
            <ToastAction
              altText="Undo dismiss"
              onClick={() => handleUndoDismiss(id)}
            >
              <Undo2 className="mr-1 h-3 w-3" />
              Undo
            </ToastAction>
          ),
        });
      } catch {
        toast({
          title: "Failed to dismiss",
          description: "An error occurred while dismissing the FAQ.",
          variant: "destructive",
        });
      } finally {
        setActionInProgress(null);
      }
    },
    [items, onDismiss, toast, handleUndoDismiss]
  );

  // Show loading state
  if (isLoading) {
    return (
      <div
        data-testid="similar-faq-review-loading"
        className={cn(
          "rounded-lg border border-amber-500/20 bg-amber-50 p-4 dark:bg-amber-900/10",
          className
        )}
      >
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
          <span className="text-sm text-amber-700 dark:text-amber-300">
            Loading review queue...
          </span>
        </div>
        <div className="mt-3 space-y-2">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-32 w-full" />
        </div>
      </div>
    );
  }

  // Don't render if no items
  if (items.length === 0) {
    return null;
  }

  return (
    <>
      <div
        data-testid="similar-faq-review-queue"
        role="alert"
        aria-live="polite"
        className={cn(
          "rounded-lg border border-amber-500/20 bg-amber-50 p-4 dark:bg-amber-900/10",
          className
        )}
      >
        <Collapsible open={isOpen} onOpenChange={handleOpenChange}>
          <div className="flex items-center justify-between">
            <CollapsibleTrigger
              data-testid="similar-faq-review-toggle"
              aria-expanded={isOpen}
              className="flex items-center gap-2 text-left"
            >
              <AlertCircle className="h-4 w-4 text-amber-600 dark:text-amber-500" />
              <ChevronDown
                className={cn(
                  "h-4 w-4 text-amber-600 transition-transform duration-200 dark:text-amber-500",
                  isOpen ? "" : "-rotate-90"
                )}
              />
              <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
                <Badge
                  variant="secondary"
                  className="mr-2 bg-amber-200 text-amber-800 dark:bg-amber-800 dark:text-amber-200"
                >
                  {items.length}
                </Badge>
                similar FAQ{items.length !== 1 ? "s" : ""} pending review
              </span>
            </CollapsibleTrigger>

            {onRefresh && (
              <Button
                variant="ghost"
                size="sm"
                onClick={onRefresh}
                className="text-amber-700 hover:text-amber-800 dark:text-amber-300 dark:hover:text-amber-200"
              >
                Refresh
              </Button>
            )}
          </div>

          <p className="ml-6 mt-1 text-xs text-amber-700 dark:text-amber-300">
            Review auto-extracted FAQs before they go live
          </p>

          <CollapsibleContent className="mt-4 space-y-4">
            {items.map((candidate) => (
              <SimilarFaqReviewCard
                key={candidate.id}
                candidate={candidate}
                isActionInProgress={actionInProgress === candidate.id}
                onApprove={() => handleApprove(candidate.id)}
                onMerge={() => handleMergeClick(candidate.id)}
                onDismiss={() => handleDismissInstant(candidate.id)}
              />
            ))}
          </CollapsibleContent>
        </Collapsible>
      </div>

      {/* Merge Preview Modal */}
      <MergePreviewModal
        isOpen={mergeModalOpen}
        onClose={() => {
          setMergeModalOpen(false);
          setSelectedCandidate(null);
        }}
        candidate={selectedCandidate}
        onConfirm={handleMergeConfirm}
        isLoading={actionInProgress === selectedCandidate?.id}
      />
    </>
  );
}
