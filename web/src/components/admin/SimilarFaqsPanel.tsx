"use client";

import { useState } from "react";
import { ChevronDown, ExternalLink, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

/**
 * Similar FAQ item returned from the API.
 */
export interface SimilarFAQItem {
  id: number;
  question: string;
  answer: string;
  similarity: number;
  category?: string | null;
  protocol?: string | null;
}

/**
 * Props for the SimilarFaqsPanel component.
 */
interface SimilarFaqsPanelProps {
  /** Array of similar FAQs to display */
  similarFaqs: SimilarFAQItem[];
  /** Whether the component is currently loading */
  isLoading?: boolean;
  /** Callback when "View FAQ" is clicked */
  onViewFaq?: (faqId: number) => void;
  /** Optional className for custom styling */
  className?: string;
}

/**
 * Get the badge variant and label based on similarity score.
 *
 * Tiers:
 * - >95%: destructive (red) - "Likely duplicate"
 * - 85-95%: warning (amber) - "Very similar"
 * - 75-85%: secondary (muted) - "Similar"
 * - 65-75%: outline (subtle) - "Related"
 */
function getSimilarityBadge(similarity: number): {
  variant: "destructive" | "warning" | "secondary" | "outline";
  label: string;
  testId: string;
} {
  if (similarity >= 0.95) {
    return {
      variant: "destructive",
      label: "Likely duplicate",
      testId: "similarity-badge-destructive",
    };
  }
  if (similarity >= 0.85) {
    return {
      variant: "warning",
      label: "Very similar",
      testId: "similarity-badge-warning",
    };
  }
  if (similarity >= 0.75) {
    return {
      variant: "secondary",
      label: "Similar",
      testId: "similarity-badge-secondary",
    };
  }
  return {
    variant: "outline",
    label: "Related",
    testId: "similarity-badge-outline",
  };
}

/**
 * Custom badge styles for warning variant (amber colors).
 */
const badgeWarningStyles =
  "border-transparent bg-amber-500 text-white shadow hover:bg-amber-500/80 dark:bg-amber-600 dark:hover:bg-amber-600/80";

/**
 * SimilarFaqsPanel displays a collapsible alert showing FAQs
 * that are semantically similar to the question being entered.
 *
 * Features:
 * - Collapsible panel with chevron toggle
 * - Tiered similarity badges (destructive, warning, secondary, outline)
 * - Card-based layout for each similar FAQ
 * - Truncated answer preview (200 chars from API)
 * - "View FAQ" link for each item
 * - Loading state with skeleton
 * - Accessibility: role="alert", aria-live="polite", aria-expanded
 */
export function SimilarFaqsPanel({
  similarFaqs,
  isLoading = false,
  onViewFaq,
  className,
}: SimilarFaqsPanelProps) {
  const [isOpen, setIsOpen] = useState(true);

  // Show loading state
  if (isLoading) {
    return (
      <div
        data-testid="similar-faqs-loading"
        className={cn(
          "rounded-lg border border-amber-500/20 bg-amber-50 p-4 dark:bg-amber-900/10",
          className
        )}
      >
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin text-amber-600" />
          <span className="text-sm text-amber-700 dark:text-amber-300">
            Checking for similar FAQs...
          </span>
        </div>
        <div className="mt-3 space-y-2">
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    );
  }

  // Don't render if no similar FAQs
  if (similarFaqs.length === 0) {
    return null;
  }

  return (
    <div
      data-testid="similar-faqs-panel"
      role="alert"
      aria-live="polite"
      className={cn(
        "rounded-lg border border-amber-500/20 bg-amber-50 p-4 dark:bg-amber-900/10",
        className
      )}
    >
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger
          data-testid="similar-faqs-toggle"
          aria-expanded={isOpen}
          className="flex w-full items-center gap-2 text-left"
        >
          <ChevronDown
            className={cn(
              "h-4 w-4 text-amber-600 transition-transform duration-200 dark:text-amber-500",
              isOpen ? "" : "-rotate-90"
            )}
          />
          <span className="text-sm font-medium text-amber-900 dark:text-amber-100">
            <span data-testid="similar-faqs-count">{similarFaqs.length}</span>{" "}
            similar FAQ{similarFaqs.length !== 1 ? "s" : ""} detected
          </span>
        </CollapsibleTrigger>

        <p className="ml-6 text-xs text-amber-700 dark:text-amber-300">
          Review before saving to avoid duplicates
        </p>

        <CollapsibleContent className="mt-3 space-y-3">
          {similarFaqs.map((faq) => {
            const badge = getSimilarityBadge(faq.similarity);

            return (
              <Card
                key={faq.id}
                data-testid="similar-faq-item"
                className="border-amber-200 bg-white dark:border-amber-800 dark:bg-amber-950/50"
              >
                <CardContent className="p-3">
                  <div className="flex items-start justify-between gap-2">
                    <Badge
                      data-testid={badge.testId}
                      variant={badge.variant === "warning" ? "default" : badge.variant}
                      className={cn(
                        badge.variant === "warning" && badgeWarningStyles
                      )}
                    >
                      {badge.label}
                    </Badge>
                    {faq.category && (
                      <span className="text-xs text-muted-foreground">
                        {faq.category}
                      </span>
                    )}
                  </div>

                  <h4 className="mt-2 text-sm font-medium text-foreground">
                    {faq.question}
                  </h4>

                  <p
                    data-testid="similar-faq-answer"
                    className="mt-1 text-xs text-muted-foreground line-clamp-2"
                  >
                    {faq.answer}
                  </p>

                  <div className="mt-2 flex justify-end">
                    <button
                      type="button"
                      data-testid="view-faq-link"
                      onClick={() => onViewFaq?.(faq.id)}
                      className="inline-flex items-center gap-1 text-xs text-amber-600 hover:text-amber-700 hover:underline dark:text-amber-500 dark:hover:text-amber-400"
                    >
                      View FAQ
                      <ExternalLink className="h-3 w-3" />
                    </button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
