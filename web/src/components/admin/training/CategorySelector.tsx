"use client";

import { useState, useEffect, memo, useCallback } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { Loader2, Sparkles } from "lucide-react";

// FAQ Categories
export const FAQ_CATEGORIES = [
  { value: "Trading", label: "Trading" },
  { value: "Wallet", label: "Wallet" },
  { value: "Installation", label: "Installation" },
  { value: "Security", label: "Security" },
  { value: "Reputation", label: "Reputation" },
  { value: "Payment Methods", label: "Payment Methods" },
  { value: "Fees", label: "Fees" },
  { value: "Troubleshooting", label: "Troubleshooting" },
  { value: "Account", label: "Account" },
  { value: "General", label: "General" },
] as const;

export type CategoryType = (typeof FAQ_CATEGORIES)[number]["value"];

// Dot color for visual category identification
export const getCategoryDotColor = (category: string): string => {
  const colors: Record<string, string> = {
    Trading: "bg-emerald-500",
    Wallet: "bg-amber-500",
    Installation: "bg-blue-500",
    Security: "bg-red-500",
    Reputation: "bg-purple-500",
    "Payment Methods": "bg-cyan-500",
    Fees: "bg-orange-500",
    Troubleshooting: "bg-rose-500",
    Account: "bg-indigo-500",
    General: "bg-slate-500",
  };
  return colors[category] || colors.General;
};

// Badge color for display in other contexts
export const getCategoryBadgeColor = (category: string): string => {
  const colors: Record<string, string> = {
    Trading:
      "bg-emerald-500/10 text-emerald-600 border-emerald-500/30 dark:text-emerald-400",
    Wallet:
      "bg-amber-500/10 text-amber-600 border-amber-500/30 dark:text-amber-400",
    Installation:
      "bg-blue-500/10 text-blue-600 border-blue-500/30 dark:text-blue-400",
    Security:
      "bg-red-500/10 text-red-600 border-red-500/30 dark:text-red-400",
    Reputation:
      "bg-purple-500/10 text-purple-600 border-purple-500/30 dark:text-purple-400",
    "Payment Methods":
      "bg-cyan-500/10 text-cyan-600 border-cyan-500/30 dark:text-cyan-400",
    Fees: "bg-orange-500/10 text-orange-600 border-orange-500/30 dark:text-orange-400",
    Troubleshooting:
      "bg-rose-500/10 text-rose-600 border-rose-500/30 dark:text-rose-400",
    Account:
      "bg-indigo-500/10 text-indigo-600 border-indigo-500/30 dark:text-indigo-400",
    General:
      "bg-slate-500/10 text-slate-600 border-slate-500/30 dark:text-slate-400",
  };
  return colors[category] || colors.General;
};

interface CategorySelectorProps {
  currentCategory: string | null;
  suggestedCategory?: string | null;
  onCategoryChange: (category: string) => void;
  onSaveCategory?: (category: string) => Promise<void>;
  isSaving?: boolean;
  className?: string;
  showLabel?: boolean;
}

// Memoized CategorySelector component to prevent unnecessary re-renders (Rule 5.2)
export const CategorySelector = memo(function CategorySelector({
  currentCategory,
  suggestedCategory,
  onCategoryChange,
  onSaveCategory,
  isSaving = false,
  className,
  showLabel = true,
}: CategorySelectorProps) {
  const [selectedCategory, setSelectedCategory] = useState<string>(
    currentCategory || suggestedCategory || "General"
  );

  useEffect(() => {
    if (currentCategory) {
      setSelectedCategory(currentCategory);
    } else if (suggestedCategory) {
      setSelectedCategory(suggestedCategory);
    }
  }, [currentCategory, suggestedCategory]);

  // Memoized handler to prevent unnecessary re-renders (Rule 5.5)
  const handleCategoryChange = useCallback(async (value: string) => {
    setSelectedCategory(value);
    onCategoryChange(value);
    if (onSaveCategory) {
      await onSaveCategory(value);
    }
  }, [onCategoryChange, onSaveCategory]);

  // Show suggestion chip when different from selected and meaningful
  const showSuggested =
    suggestedCategory &&
    suggestedCategory !== selectedCategory &&
    suggestedCategory !== "General";

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {showLabel && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Category
          </span>
          {isSaving && (
            <Loader2 className="h-3 w-3 animate-spin text-muted-foreground" />
          )}
        </div>
      )}

      {/* Controls row - dropdown + AI suggestion */}
      <div className="flex items-center gap-2">
        {/* Dropdown with color dot */}
        <Select
          value={selectedCategory}
          onValueChange={handleCategoryChange}
          disabled={isSaving}
        >
          <SelectTrigger className="w-48 h-8">
            <SelectValue placeholder="Select..." />
          </SelectTrigger>
          <SelectContent>
            {FAQ_CATEGORIES.map((cat) => (
              <SelectItem key={cat.value} value={cat.value}>
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full flex-shrink-0",
                      getCategoryDotColor(cat.value)
                    )}
                  />
                  <span>{cat.label}</span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* AI Suggestion chip - subtle, actionable */}
        {showSuggested && (
          <button
            type="button"
            onClick={() => handleCategoryChange(suggestedCategory)}
            className={cn(
              "inline-flex items-center gap-1.5 px-2 py-1 text-xs rounded-md",
              "bg-muted hover:bg-muted/80 text-muted-foreground",
              "border border-dashed border-border transition-colors"
            )}
            title="Apply AI suggestion"
          >
            <Sparkles className="h-3 w-3" />
            {suggestedCategory}
          </button>
        )}
      </div>
    </div>
  );
});
