"use client";

import { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { SimilarFaqCandidate } from "./SimilarFaqReviewQueue";

/**
 * Props for the MergePreviewModal component.
 */
interface MergePreviewModalProps {
  /** Whether the modal is open */
  isOpen: boolean;
  /** Callback to close the modal */
  onClose: () => void;
  /** The candidate being merged */
  candidate: SimilarFaqCandidate | null;
  /** Callback when merge is confirmed */
  onConfirm: (mode: "replace" | "append") => void;
  /** Whether an action is in progress */
  isLoading?: boolean;
}

/**
 * MergePreviewModal displays a preview of the merged FAQ before confirming.
 *
 * Features:
 * - Toggle between Replace and Append modes
 * - Live preview of merged content
 * - Side-by-side comparison (current vs after merge)
 * - Highlights appended content for clarity
 */
export function MergePreviewModal({
  isOpen,
  onClose,
  candidate,
  onConfirm,
  isLoading = false,
}: MergePreviewModalProps) {
  const [mode, setMode] = useState<"replace" | "append">("append");

  // Generate preview content based on mode
  const previewContent = useMemo(() => {
    if (!candidate) return null;

    if (mode === "replace") {
      return {
        question: candidate.extracted_question,
        answer: candidate.extracted_answer,
      };
    } else {
      return {
        question: candidate.matched_question,
        answer: `${candidate.matched_answer}\n\n---\n\n${candidate.extracted_answer}`,
        appendedSection: candidate.extracted_answer,
      };
    }
  }, [mode, candidate]);

  if (!candidate) return null;

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Merge FAQ</DialogTitle>
          <DialogDescription>
            Preview how the merged FAQ will look before confirming.
          </DialogDescription>
        </DialogHeader>

        {/* Mode Toggle */}
        <div className="flex gap-2 py-2">
          <Button
            type="button"
            variant={mode === "replace" ? "default" : "outline"}
            size="sm"
            onClick={() => setMode("replace")}
          >
            Replace
          </Button>
          <Button
            type="button"
            variant={mode === "append" ? "default" : "outline"}
            size="sm"
            onClick={() => setMode("append")}
          >
            Append
          </Button>
        </div>

        {/* Mode Description */}
        <p className="text-sm text-muted-foreground">
          {mode === "replace"
            ? "The existing FAQ will be completely replaced with the extracted content."
            : "The extracted content will be appended to the existing FAQ answer."}
        </p>

        {/* Preview Grid */}
        <div className="grid grid-cols-1 gap-4 mt-4 md:grid-cols-2">
          {/* Current FAQ */}
          <div className="space-y-3 rounded-lg border border-blue-200 bg-blue-50 p-4 dark:border-blue-800 dark:bg-blue-950/30">
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200"
              >
                Current FAQ
              </Badge>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground">
                {candidate.matched_question}
              </p>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                {candidate.matched_answer}
              </p>
            </div>
          </div>

          {/* After Merge Preview */}
          <div className="space-y-3 rounded-lg border border-green-200 bg-green-50 p-4 dark:border-green-800 dark:bg-green-950/30">
            <div className="flex items-center gap-2">
              <Badge
                variant="outline"
                className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200"
              >
                After Merge
              </Badge>
            </div>
            <div className="space-y-2">
              <p className="text-sm font-medium text-foreground">
                {previewContent?.question}
              </p>
              <div className="text-sm text-muted-foreground">
                {mode === "append" ? (
                  <>
                    <p className="whitespace-pre-wrap">
                      {candidate.matched_answer}
                    </p>
                    <div className="border-t border-dashed border-green-300 dark:border-green-700 my-3 pt-3">
                      <span className="text-xs font-medium text-green-700 dark:text-green-300 block mb-2">
                        + Appended content:
                      </span>
                      <div className="bg-green-100 dark:bg-green-900/50 p-3 rounded-md whitespace-pre-wrap">
                        {candidate.extracted_answer}
                      </div>
                    </div>
                  </>
                ) : (
                  <div
                    className={cn(
                      "p-3 rounded-md whitespace-pre-wrap",
                      "bg-green-100 dark:bg-green-900/50"
                    )}
                  >
                    {previewContent?.answer}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Info Text */}
        <p className="text-xs text-muted-foreground mt-2">
          The extracted FAQ will be marked as merged after confirmation.
        </p>

        <DialogFooter className="mt-4">
          <Button type="button" variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => onConfirm(mode)}
            disabled={isLoading}
          >
            {isLoading ? "Merging..." : "Confirm Merge"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
