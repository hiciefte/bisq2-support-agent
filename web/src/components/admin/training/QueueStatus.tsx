"use client"

import { memo } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { AlertCircle, Eye, BarChart3 } from "lucide-react";
import type { QueueCounts, RoutingCategory } from "./types";

interface QueueStatusProps {
  counts: QueueCounts;
  selectedRouting: RoutingCategory;
  onRoutingChange: (routing: RoutingCategory) => void;
}

// Queue configuration reflecting actual semantic meaning:
// - FULL_REVIEW: RAG answered differently from staff → Knowledge gap to fill
// - SPOT_CHECK: RAG was close but not perfect → Minor improvement opportunity
// - AUTO_APPROVE: RAG already knows this → Use for calibration data collection
const routingConfig: Record<RoutingCategory, {
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  bgColor: string;
}> = {
  FULL_REVIEW: {
    label: "Knowledge Gap",
    description: "Create FAQ to fill gap",
    icon: AlertCircle,
    color: "text-muted-foreground",
    bgColor: "bg-muted"
  },
  SPOT_CHECK: {
    label: "Minor Gap",
    description: "Approve or skip",
    icon: Eye,
    color: "text-muted-foreground",
    bgColor: "bg-muted"
  },
  AUTO_APPROVE: {
    label: "Calibration",
    description: "Rate for auto-send",
    icon: BarChart3,
    color: "text-muted-foreground",
    bgColor: "bg-muted"
  }
};

// Memoized QueueStatus component to prevent unnecessary re-renders (Rule 5.2)
export const QueueStatus = memo(function QueueStatus({ counts, selectedRouting, onRoutingChange }: QueueStatusProps) {
  const categories: RoutingCategory[] = ['FULL_REVIEW', 'SPOT_CHECK', 'AUTO_APPROVE'];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
      {categories.map((routing) => {
        const config = routingConfig[routing];
        const count = counts[routing];
        const isSelected = selectedRouting === routing;
        const Icon = config.icon;

        return (
          <Card
            key={routing}
            className={cn(
              "transition-colors hover:bg-accent/30",
              isSelected && "ring-2 ring-primary ring-offset-2"
            )}
          >
            <button
              type="button"
              className="w-full text-left"
              aria-pressed={isSelected}
              onClick={() => onRoutingChange(routing)}
            >
              <CardContent className="p-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={cn("p-2 rounded-lg", config.bgColor)}>
                      <Icon className={cn("h-5 w-5", config.color)} />
                    </div>
                    <div>
                      <p className="font-medium">{config.label}</p>
                      <p className="text-xs text-muted-foreground">
                        {config.description}
                      </p>
                    </div>
                  </div>
                  <span
                    className={cn(
                      "text-lg font-bold tabular-nums",
                      count > 0 ? "text-foreground" : "text-muted-foreground"
                    )}
                  >
                    {count}
                  </span>
                </div>
              </CardContent>
            </button>
          </Card>
        );
      })}
    </div>
  );
});
