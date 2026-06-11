"use client";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { Loader2, RefreshCw } from "lucide-react";
import { ReactNode } from "react";

interface QueuePageHeaderProps {
  title: string;
  description: string;
  lastUpdatedLabel?: string | null;
  isRefreshing?: boolean;
  onRefresh?: () => void;
  rightSlot?: ReactNode;
}

export function QueuePageHeader({
  title,
  description,
  lastUpdatedLabel,
  isRefreshing = false,
  onRefresh,
  rightSlot,
}: QueuePageHeaderProps) {
  return (
    <div className="space-y-4">
      <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold tracking-tight">{title}</h1>
          <p className="text-sm text-muted-foreground mt-1">{description}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2 sm:justify-end">
          {lastUpdatedLabel && (
            <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground">
              {isRefreshing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              <span className="tabular-nums">{lastUpdatedLabel}</span>
            </div>
          )}
          {onRefresh && (
            <Button
              onClick={onRefresh}
              variant="ghost"
              size="sm"
              className={cn("text-muted-foreground", isRefreshing && "opacity-80")}
              disabled={isRefreshing}
              aria-label="Refresh queue"
            >
              {isRefreshing ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <RefreshCw className="h-4 w-4" />
              )}
            </Button>
          )}
          {rightSlot}
        </div>
      </div>
    </div>
  );
}
