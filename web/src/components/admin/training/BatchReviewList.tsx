"use client"

import { useState } from 'react';
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { stripGeneratedAnswerFooter } from "@/lib/answer-format";
import { Check, Loader2, ChevronDown, ChevronUp } from "lucide-react";
import type { BatchCandidate } from "./types";

interface BatchReviewListProps {
  candidates: BatchCandidate[];
  isLoading: boolean;
  onBatchApprove: (ids: number[]) => Promise<void>;
  onExpandItem: (candidate: BatchCandidate) => void;
}

export function BatchReviewList({
  candidates,
  isLoading,
  onBatchApprove,
  onExpandItem,
}: BatchReviewListProps) {
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [isApproving, setIsApproving] = useState(false);

  const toggleSelection = (id: number) => {
    const newSelected = new Set(selectedIds);
    if (newSelected.has(id)) {
      newSelected.delete(id);
    } else {
      newSelected.add(id);
    }
    setSelectedIds(newSelected);
  };

  const toggleSelectAll = () => {
    if (selectedIds.size === candidates.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(candidates.map(c => c.id)));
    }
  };

  const handleBatchApprove = async () => {
    if (selectedIds.size === 0) return;
    setIsApproving(true);
    try {
      await onBatchApprove(Array.from(selectedIds));
      setSelectedIds(new Set());
    } finally {
      setIsApproving(false);
    }
  };

  const toggleExpand = (id: number) => {
    setExpandedId(expandedId === id ? null : id);
  };

  if (isLoading) {
    return (
      <Card>
        <CardContent className="p-12 text-center">
          <Loader2 className="h-8 w-8 animate-spin mx-auto text-muted-foreground" />
          <p className="text-sm text-muted-foreground mt-2">Loading candidates...</p>
        </CardContent>
      </Card>
    );
  }

  if (candidates.length === 0) {
    return (
      <Card>
        <CardContent className="p-12 text-center">
          <p className="text-muted-foreground">No candidates in batch queue</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Batch actions header */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Checkbox
                id="select-all"
                checked={selectedIds.size === candidates.length}
                onCheckedChange={toggleSelectAll}
              />
              <label htmlFor="select-all" className="text-sm font-medium cursor-pointer">
                {selectedIds.size === candidates.length
                  ? 'Deselect all'
                  : `Select all (${candidates.length})`}
              </label>
              {selectedIds.size > 0 && (
                <Badge variant="secondary">
                  {selectedIds.size} selected
                </Badge>
              )}
            </div>
            <Button
              onClick={handleBatchApprove}
              disabled={selectedIds.size === 0 || isApproving}
              className="bg-green-600 hover:bg-green-700"
            >
              {isApproving ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Approving...
                </>
              ) : (
                <>
                  <Check className="h-4 w-4 mr-2" />
                  Approve Selected ({selectedIds.size})
                </>
              )}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Batch item list */}
      <div className="space-y-2">
        {candidates.map((candidate) => {
          const scorePct = candidate.final_score === null
            ? null
            : Math.round(candidate.final_score <= 1 ? candidate.final_score * 100 : candidate.final_score);
          const cleanedGeneratedAnswer = stripGeneratedAnswerFooter(candidate.generated_answer || "");

          return (
            <Card
              key={candidate.id}
              className={cn(
                "transition-colors hover:bg-accent/20",
                selectedIds.has(candidate.id) && "ring-2 ring-primary ring-offset-2"
              )}
            >
              <CardContent className="p-4">
                <div className="flex items-start gap-3">
                  <Checkbox
                    checked={selectedIds.has(candidate.id)}
                    onCheckedChange={() => toggleSelection(candidate.id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                  <button
                    type="button"
                    className="flex-1 min-w-0 text-left"
                    onClick={() => toggleExpand(candidate.id)}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs text-muted-foreground">
                        #{candidate.id}
                      </span>
                      {scorePct !== null && (
                        <Badge
                          variant="outline"
                          className={cn(
                            "text-xs",
                            scorePct >= 80
                              ? "bg-green-50 text-green-700 border-green-200 dark:bg-green-900/20 dark:text-green-400 dark:border-green-800"
                              : scorePct >= 60
                                ? "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-900/20 dark:text-yellow-400 dark:border-yellow-800"
                                : "bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-400 dark:border-red-800"
                          )}
                        >
                          {scorePct}%
                        </Badge>
                      )}
                      {candidate.category && (
                        <Badge variant="secondary" className="text-xs">
                          {candidate.category}
                        </Badge>
                      )}
                      <Badge variant="outline" className="text-xs text-muted-foreground">
                        {candidate.source}
                      </Badge>
                    </div>
                    <p className="text-sm line-clamp-2 text-foreground">
                      {candidate.question_text}
                    </p>
                  </button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleExpand(candidate.id);
                    }}
                  >
                    {expandedId === candidate.id ? (
                      <ChevronUp className="h-4 w-4" />
                    ) : (
                      <ChevronDown className="h-4 w-4" />
                    )}
                  </Button>
                </div>

                {expandedId === candidate.id && (
                  <div className="mt-4 pt-4 border-t space-y-3">
                    <div>
                      <p className="text-xs font-medium text-muted-foreground mb-1">Question</p>
                      <p className="text-sm">{candidate.question_text}</p>
                    </div>
                    {cleanedGeneratedAnswer && (
                      <div>
                        <p className="text-xs font-medium text-muted-foreground mb-1">Generated Answer</p>
                        <p className="text-sm text-muted-foreground whitespace-pre-wrap line-clamp-6">
                          {cleanedGeneratedAnswer}
                        </p>
                      </div>
                    )}
                    <div className="flex justify-end">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          onExpandItem(candidate);
                        }}
                      >
                        View Full Details
                      </Button>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          );
        })}
      </div>
    </div>
  );
}
