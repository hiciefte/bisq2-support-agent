"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { LucideIcon } from "lucide-react";

interface QueueTabItem<TTabKey extends string> {
  key: TTabKey;
  label: string;
  count: number;
  icon: LucideIcon;
}

interface QueueTabsProps<TTabKey extends string> {
  tabs: Array<QueueTabItem<TTabKey>>;
  activeTab: TTabKey;
  onTabChange: (tab: TTabKey) => void;
  className?: string;
  gridClassName?: string;
}

export function QueueTabs<TTabKey extends string>({
  tabs,
  activeTab,
  onTabChange,
  className,
  gridClassName = "grid-cols-3",
}: QueueTabsProps<TTabKey>) {
  return (
    <div className={cn("w-full min-w-0 rounded-lg border border-border/70 bg-card/40 p-1.5", className)}>
      <div className="max-w-full overflow-x-auto">
        <div className={cn("flex w-max min-w-full gap-1 sm:grid sm:w-full", gridClassName)}>
          {tabs.map((item) => {
            const isSelected = activeTab === item.key;
            const Icon = item.icon;
            return (
              <Button
                key={item.key}
                variant={isSelected ? "default" : "ghost"}
                size="sm"
                className={cn(
                  "h-auto min-h-11 min-w-52 flex-1 justify-start gap-2 px-3 py-2 text-left sm:min-w-0",
                  !isSelected && "text-muted-foreground hover:text-foreground",
                )}
                aria-pressed={isSelected}
                onClick={() => onTabChange(item.key)}
              >
                <Icon className="h-4 w-4 shrink-0" />
                <span className="truncate">{item.label}</span>
                <Badge variant={isSelected ? "secondary" : "outline"} className="ml-auto tabular-nums">
                  {item.count}
                </Badge>
              </Button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
