"use client";

import { Badge } from "@/components/ui/badge";
import { ReactNode } from "react";

interface QueueCommandBarProps {
  children: ReactNode;
  advancedContent?: ReactNode;
  activeFilterPills?: string[];
}

export function QueueCommandBar({
  children,
  advancedContent,
  activeFilterPills = [],
}: QueueCommandBarProps) {
  return (
    <div className="sticky top-16 z-20 -mx-4 md:-mx-8 px-4 md:px-8 py-3 border-y border-border/70 bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/70">
      {children}
      {advancedContent}
      {activeFilterPills.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {activeFilterPills.map((pill) => (
            <Badge key={pill} variant="outline" className="text-xs bg-card/60">
              {pill}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
