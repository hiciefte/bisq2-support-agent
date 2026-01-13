"use client";

import { memo } from "react";
import { Check, GitMerge, X, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import type { SimilarFaqCandidate } from "./SimilarFaqReviewQueue";

/**
 * Props for the SimilarFaqReviewCard component.
 */
interface SimilarFaqReviewCardProps {
  /** The candidate to display */
  candidate: SimilarFaqCandidate;
  /** Whether an action is currently in progress */
  isActionInProgress?: boolean;
  /** Callback when approve is clicked */
  onApprove: () => void;
  /** Callback when merge is clicked */
  onMerge: () => void;
  /** Callback when dismiss is clicked */
  onDismiss: () => void;
}

/**
 * Get the badge variant and label based on similarity score.
 */
function getSimilarityBadge(similarity: number): {
  variant: "destructive" | "warning" | "secondary" | "outline";
  label: string;
} {
  if (similarity >= 0.95) {
    return { variant: "destructive", label: "Likely duplicate" };
  }
  if (similarity >= 0.85) {
    return { variant: "warning", label: "Very similar" };
  }
  if (similarity >= 0.75) {
    return { variant: "secondary", label: "Similar" };
  }
  return { variant: "outline", label: "Related" };
}

/**
 * Custom badge styles for warning variant.
 */
const badgeWarningStyles =
  "border-transparent bg-amber-500 text-white shadow hover:bg-amber-500/80 dark:bg-amber-600 dark:hover:bg-amber-600/80";

/**
 * SimilarFaqReviewCard displays a single candidate with side-by-side comparison
 * between the extracted FAQ and the matched existing FAQ.
 *
 * Features:
 * - Two-column layout (desktop) / stacked (mobile)
 * - Similarity badge with tier indication
 * - Action buttons: Approve, Merge, Dismiss
 * - Loading state during action
 */
export const SimilarFaqReviewCard = memo(function SimilarFaqReviewCard({
  candidate,
  isActionInProgress = false,
  onApprove,
  onMerge,
  onDismiss,
}: SimilarFaqReviewCardProps) {
  const badge = getSimilarityBadge(candidate.similarity);
  const similarityPercent = Math.round(candidate.similarity * 100);

  return (
    <Card
      data-testid="similar-faq-review-card"
      className={cn(
        "border-amber-200 bg-white dark:border-amber-800 dark:bg-amber-950/50",
        isActionInProgress && "opacity-60"
      )}
    >
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <Badge
            data-testid="similarity-badge"
            variant={badge.variant === "warning" ? "default" : badge.variant}
            className={cn(badge.variant === "warning" && badgeWarningStyles)}
          >
            {badge.label}
          </Badge>
          <span
            className="text-xs text-muted-foreground"
            title={`${similarityPercent}% similarity`}
          >
            {similarityPercent}% match
          </span>
        </div>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Side-by-side comparison */}
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {/* Extracted FAQ (New) */}
          <div className="space-y-2 rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-950/30">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200">
                Extracted (New)
              </Badge>
              {candidate.extracted_category && (
                <span className="text-xs text-muted-foreground">
                  {candidate.extracted_category}
                </span>
              )}
            </div>
            <h4 className="text-sm font-medium text-foreground">
              {candidate.extracted_question}
            </h4>
            <p className="text-xs text-muted-foreground line-clamp-3">
              {candidate.extracted_answer}
            </p>
          </div>

          {/* Matched FAQ (Existing) */}
          <div className="space-y-2 rounded-lg border border-blue-200 bg-blue-50 p-3 dark:border-blue-800 dark:bg-blue-950/30">
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                Existing (Match)
              </Badge>
              {candidate.matched_category && (
                <span className="text-xs text-muted-foreground">
                  {candidate.matched_category}
                </span>
              )}
            </div>
            <h4 className="text-sm font-medium text-foreground">
              {candidate.matched_question}
            </h4>
            <p className="text-xs text-muted-foreground line-clamp-3">
              {candidate.matched_answer}
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-end gap-2 border-t pt-3">
          {isActionInProgress ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Processing...
            </div>
          ) : (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={onDismiss}
                className="text-muted-foreground hover:text-destructive"
              >
                <X className="mr-1 h-4 w-4" />
                Dismiss
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={onMerge}
                className="text-muted-foreground hover:text-primary"
              >
                <GitMerge className="mr-1 h-4 w-4" />
                Merge
              </Button>
              <Button
                variant="default"
                size="sm"
                onClick={onApprove}
                className="bg-green-600 hover:bg-green-700"
              >
                <Check className="mr-1 h-4 w-4" />
                Approve as New
              </Button>
            </>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
