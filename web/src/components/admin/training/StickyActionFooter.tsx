"use client"

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { XCircle, SkipForward, PlusCircle, Loader2 } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

// Rejection reasons - same as in TrainingReviewItem
const REJECT_REASONS = [
  { value: "incorrect", label: "Incorrect" },
  { value: "outdated", label: "Outdated" },
  { value: "too_vague", label: "Too vague" },
  { value: "off_topic", label: "Off-topic" },
  { value: "duplicate", label: "Duplicate" },
  { value: "other", label: "Other" },
];

interface StickyActionFooterProps {
  isVisible: boolean;
  candidateId: number;
  score: number | null;
  category: string | null;
  routing: string;
  isLoading: boolean;
  onApprove: () => void;
  onReject: (reason: string) => void;
  onSkip: () => void;
}

export function StickyActionFooter({
  isVisible,
  candidateId,
  score,
  category,
  routing,
  isLoading,
  onApprove,
  onReject,
  onSkip,
}: StickyActionFooterProps) {
  // Local state for showing rejection reasons in sticky footer
  const [showRejectReasons, setShowRejectReasons] = useState(false);

  // Semantic routing labels (Phase: Queue Semantic Redesign)
  const routingLabels: Record<string, string> = {
    FULL_REVIEW: "Knowledge Gap",
    SPOT_CHECK: "Minor Gap",
    AUTO_APPROVE: "Calibration",
  };

  // Handle direct rejection (Speed Through Subtraction principle)
  const handleDirectReject = (reason: string) => {
    onReject(reason);
    setShowRejectReasons(false);
  };

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ y: 100, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          exit={{ y: 100, opacity: 0 }}
          transition={{ type: "spring", stiffness: 300, damping: 30 }}
          className={cn(
            "fixed bottom-0 left-0 right-0 z-50",
            "bg-background/95 backdrop-blur-sm border-t shadow-lg"
          )}
        >
          <div className="container max-w-4xl mx-auto px-4 py-3">
            <div className="flex items-center justify-between gap-4">
              {/* Candidate info */}
              <div className="flex items-center gap-3 min-w-0">
                <span className="text-sm font-medium text-muted-foreground whitespace-nowrap">
                  #{candidateId}
                </span>
                {score !== null && (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-xs",
                      score >= 0.80
                        ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/20 dark:text-green-400 dark:border-green-800"
                        : score >= 0.60
                        ? "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-900/20 dark:text-yellow-400 dark:border-yellow-800"
                        : "bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-400 dark:border-red-800"
                    )}
                  >
                    {Math.round(score * 100)}%
                  </Badge>
                )}
                {category && (
                  <Badge variant="secondary" className="text-xs truncate max-w-[120px]">
                    {category}
                  </Badge>
                )}
                <Badge variant="outline" className="text-xs text-muted-foreground">
                  {routingLabels[routing] || routing}
                </Badge>
              </div>

              {/* Action buttons */}
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={onSkip}
                  disabled={isLoading}
                >
                  <SkipForward className="h-4 w-4 mr-1" />
                  Skip
                </Button>

                {/* Rejection reasons or Reject button */}
                {showRejectReasons ? (
                  <div className="flex items-center gap-1 animate-in fade-in slide-in-from-right-2 duration-200">
                    {REJECT_REASONS.map((reason) => (
                      <Button
                        key={reason.value}
                        variant={reason.value === 'other' ? 'outline' : 'destructive'}
                        size="sm"
                        onClick={() => handleDirectReject(reason.value)}
                        disabled={isLoading}
                        className={cn(
                          "text-xs px-2",
                          reason.value === 'other' && 'text-destructive border-destructive/50 hover:bg-destructive/10'
                        )}
                      >
                        {reason.label}
                      </Button>
                    ))}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowRejectReasons(false)}
                      className="text-xs px-2"
                    >
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Button
                    variant="destructive"
                    size="sm"
                    onClick={() => setShowRejectReasons(true)}
                    disabled={isLoading}
                  >
                    <XCircle className="h-4 w-4 mr-1" />
                    Reject
                  </Button>
                )}

                <Button
                  size="sm"
                  onClick={onApprove}
                  disabled={isLoading}
                  className="bg-green-600 hover:bg-green-700"
                >
                  {isLoading ? (
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                  ) : (
                    <PlusCircle className="h-4 w-4 mr-1" />
                  )}
                  Approve & Create FAQ
                </Button>
              </div>
            </div>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
