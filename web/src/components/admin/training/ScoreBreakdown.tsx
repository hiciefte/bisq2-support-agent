"use client"

import { useState, memo, useMemo } from "react";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import {
  ChevronDown,
  ChevronUp,
  BarChart3,
  GitCompare,
  CheckCircle2,
  AlertTriangle,
  ListChecks,
  ShieldAlert,
  Zap,
  Eye,
  ClipboardCheck,
  Sparkles,
  CircleCheck,
  CircleAlert,
  CircleX,
  Info,
} from "lucide-react";

interface ScoreBreakdownProps {
  embeddingSimilarity: number | null;
  factualAlignment: number | null;
  contradictionScore: number | null;
  completeness: number | null;
  hallucinationRisk: number | null;
  finalScore: number | null;
  generationConfidence?: number | null;
  defaultCollapsed?: boolean;
}

interface MetricConfig {
  label: string;
  weight: number;
  icon: React.ReactNode;
  actionableDescription: string;
  technicalDescription: string;
  inverted?: boolean;
}

const METRIC_CONFIGS: Record<string, MetricConfig> = {
  generationConfidence: {
    label: "RAG Confidence",
    weight: 0,  // Not part of comparison score calculation
    icon: <Sparkles className="h-3.5 w-3.5" />,
    actionableDescription: "How confident RAG is in its answer",
    technicalDescription: "RAG system's self-assessed confidence in generating this answer (not part of comparison score)",
    inverted: false,
  },
  embeddingSimilarity: {
    label: "Meaning Match",
    weight: 15,
    icon: <GitCompare className="h-3.5 w-3.5" />,
    actionableDescription: "Check if both answers convey the same meaning",
    technicalDescription: "Semantic similarity via vector embeddings (15% weight)",
    inverted: false,
  },
  factualAlignment: {
    label: "Facts Aligned",
    weight: 30,
    icon: <CheckCircle2 className="h-3.5 w-3.5" />,
    actionableDescription: "Verify key facts and data points match between answers",
    technicalDescription: "Factual consistency between staff and RAG answers (30% weight)",
    inverted: false,
  },
  contradictionScore: {
    label: "No Conflicts",
    weight: 25,
    icon: <AlertTriangle className="h-3.5 w-3.5" />,
    actionableDescription: "Look for conflicting statements between the two answers",
    technicalDescription: "Contradiction detection - lower raw score is better (25% weight)",
    inverted: true,
  },
  completeness: {
    label: "Coverage",
    weight: 10,
    icon: <ListChecks className="h-3.5 w-3.5" />,
    actionableDescription: "Ensure all important points from staff answer are covered",
    technicalDescription: "Key point coverage from staff answer to RAG answer (10% weight)",
    inverted: false,
  },
  hallucinationRisk: {
    label: "Grounded",
    weight: 20,
    icon: <ShieldAlert className="h-3.5 w-3.5" />,
    actionableDescription: "Check for claims not supported by source documents",
    technicalDescription: "Hallucination risk assessment - lower raw score is better (20% weight)",
    inverted: true,
  },
};

interface ScoreBarProps {
  metricKey: string;
  value: number | null;
}

// Memoized ScoreBar component to prevent unnecessary re-renders (Rule 5.2)
const ScoreBar = memo(function ScoreBar({ metricKey, value }: ScoreBarProps) {
  const config = METRIC_CONFIGS[metricKey];
  if (!config) return null;

  const { label, weight, icon, actionableDescription, technicalDescription, inverted } = config;

  // If inverted, display (1 - value) for visual clarity
  // e.g., contradiction score of 0.1 is GOOD, so show as 0.9 (90%)
  const displayValue = value !== null
    ? (inverted ? 1 - value : value)
    : null;

  const percentage = displayValue !== null ? displayValue * 100 : 0;

  // Semantic color palette - green/yellow/red for quick visual assessment
  // Follows traffic light principle for instant comprehension
  const getBarColor = (pct: number) => {
    if (pct >= 75) return "bg-green-500 dark:bg-green-600";
    if (pct >= 50) return "bg-yellow-500 dark:bg-yellow-600";
    return "bg-red-500 dark:bg-red-600";
  };

  const getTextColor = (pct: number) => {
    if (pct >= 75) return "text-green-700 dark:text-green-400";
    if (pct >= 50) return "text-yellow-700 dark:text-yellow-400";
    return "text-red-700 dark:text-red-400";
  };

  const getIconColor = (pct: number) => {
    if (pct >= 75) return "text-green-600 dark:text-green-500";
    if (pct >= 50) return "text-yellow-600 dark:text-yellow-500";
    return "text-red-600 dark:text-red-500";
  };

  // Build accessible label for screen readers
  const ariaLabel = value !== null
    ? `${label}: ${percentage.toFixed(0)}%`
    : `${label}: Not available`;

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className="space-y-1.5"
            role="meter"
            aria-valuenow={value !== null ? Math.round(percentage) : undefined}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={ariaLabel}
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 min-w-0">
                <span className={cn(
                  "flex-shrink-0",
                  value !== null ? getIconColor(percentage) : "text-muted-foreground/50"
                )}>
                  {icon}
                </span>
                <span className="text-sm text-muted-foreground truncate">
                  {label}
                </span>
                <Badge
                  variant="outline"
                  className="text-[10px] px-1.5 py-0 h-4 text-muted-foreground/70 border-border/50 font-normal"
                >
                  {weight}%
                </Badge>
              </div>
              <span className={cn(
                "font-medium text-sm tabular-nums flex-shrink-0",
                value !== null ? getTextColor(percentage) : "text-muted-foreground"
              )}>
                {value !== null ? `${percentage.toFixed(0)}%` : "N/A"}
              </span>
            </div>
            {/* Actionable hint - visible below the label */}
            <p className="text-xs text-muted-foreground/70 pl-5 leading-tight">
              {actionableDescription}
            </p>
            <div className="relative h-1.5 bg-muted rounded-full overflow-hidden">
              {value !== null && (
                <>
                  {/* Threshold marker at 75% - subtle */}
                  <div
                    className="absolute top-0 bottom-0 w-px bg-border z-10"
                    style={{ left: '75%' }}
                  />
                  {/* Bar fill */}
                  <div
                    className={cn("h-full rounded-full transition-all", getBarColor(percentage))}
                    style={{ width: `${percentage}%` }}
                  />
                </>
              )}
            </div>
          </div>
        </TooltipTrigger>
        <TooltipContent
          side="left"
          className="bg-popover text-popover-foreground border shadow-md max-w-xs"
        >
          <div className="space-y-2">
            <p className="font-medium">{label}</p>
            <p className="text-sm text-muted-foreground">{technicalDescription}</p>
            {value !== null && (
              <p className="text-xs text-muted-foreground/80 pt-1 border-t border-border">
                Raw value: {(value * 100).toFixed(1)}%
                {inverted && ` (displayed as ${percentage.toFixed(0)}% - lower is better)`}
              </p>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
});

// Routing threshold footer component - hoisted static content (Rule 6.3)
// Updated labels to reflect semantic queue meaning (Phase: Queue Semantic Redesign)
function RoutingThresholdFooter() {
  return (
    <div className="mt-4 pt-3 border-t border-border/50">
      <div className="flex items-center gap-1.5 mb-2">
        <BarChart3 className="h-3.5 w-3.5 text-muted-foreground/70" />
        <span className="text-xs font-medium text-muted-foreground">Routing Thresholds</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 p-2 rounded-md bg-muted/30 border border-border/30">
                <Zap className="h-3.5 w-3.5 text-foreground/60" />
                <div>
                  <div className="font-medium text-foreground/80">90%+</div>
                  <div className="text-muted-foreground/70">Calibration</div>
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-[200px]">
              <p className="text-sm"><strong>Calibration:</strong> RAG already knows this well. Rate the answer quality for auto-send threshold tuning.</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 p-2 rounded-md bg-muted/30 border border-border/30">
                <Eye className="h-3.5 w-3.5 text-foreground/50" />
                <div>
                  <div className="font-medium text-foreground/80">75-89%</div>
                  <div className="text-muted-foreground/70">Minor Gap</div>
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-[200px]">
              <p className="text-sm"><strong>Minor gap:</strong> Small improvement opportunity. Quick review - approve or skip.</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <div className="flex items-center gap-1.5 p-2 rounded-md bg-muted/30 border border-border/30">
                <ClipboardCheck className="h-3.5 w-3.5 text-foreground/40" />
                <div>
                  <div className="font-medium text-foreground/80">&lt;75%</div>
                  <div className="text-muted-foreground/70">Knowledge Gap</div>
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="bottom" className="max-w-[200px]">
              <p className="text-sm"><strong>Knowledge gap:</strong> RAG answered differently. Create FAQ to fill this gap in knowledge.</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
    </div>
  );
}

// Memoized ScoreBreakdown component (Rule 5.2)
export const ScoreBreakdown = memo(function ScoreBreakdown({
  embeddingSimilarity,
  factualAlignment,
  contradictionScore,
  completeness,
  hallucinationRisk,
  finalScore,
  generationConfidence,
  defaultCollapsed = true
}: ScoreBreakdownProps) {
  const [isOpen, setIsOpen] = useState(!defaultCollapsed);

  // Memoized routing indicator calculation (Rule 7.4)
  const routing = useMemo(() => {
    if (finalScore === null) return null;
    const pct = finalScore * 100;
    if (pct >= 90) return { label: "Auto", color: "text-foreground/70" };
    if (pct >= 75) return { label: "Spot", color: "text-muted-foreground" };
    return { label: "Full", color: "text-muted-foreground/70" };
  }, [finalScore]);

  // Memoized traffic light calculation (Rule 7.4)
  const trafficLight = useMemo(() => {
    if (finalScore === null) return null;
    const pct = finalScore * 100;

    // Identify specific issues for actionable hints
    const issues: string[] = [];

    // Check for low factual alignment (< 50%)
    if (factualAlignment !== null && factualAlignment < 0.5) {
      issues.push("fact");
    }

    // Check for high contradiction score (> 50% raw = bad)
    if (contradictionScore !== null && contradictionScore > 0.5) {
      issues.push("conflict");
    }

    // Check for high hallucination risk (> 50% raw = bad)
    if (hallucinationRisk !== null && hallucinationRisk > 0.5) {
      issues.push("grounding");
    }

    // Generate actionable hint based on specific issues
    const getActionableHint = (issueList: string[]): string => {
      if (issueList.includes("conflict")) {
        return "Possible conflicts between answers";
      }
      if (issueList.includes("fact")) {
        return "Verify facts match staff answer";
      }
      if (issueList.includes("grounding")) {
        return "Check for unsupported claims";
      }
      return "Review specific metrics";
    };

    // GREEN: >= 75% - Good match
    if (pct >= 75) {
      return {
        icon: <CircleCheck className="h-4 w-4 text-green-600 dark:text-green-500" />,
        label: "Good Match",
        color: "text-green-600 dark:text-green-500",
        bgColor: "bg-green-50 dark:bg-green-950/30",
        hint: null,
      };
    }

    // YELLOW: 50-74% - Review needed
    if (pct >= 50) {
      return {
        icon: <CircleAlert className="h-4 w-4 text-yellow-600 dark:text-yellow-500" />,
        label: "Review Needed",
        color: "text-yellow-600 dark:text-yellow-500",
        bgColor: "bg-yellow-50 dark:bg-yellow-950/30",
        hint: issues.length > 0 ? getActionableHint(issues) : "Check metrics below",
      };
    }

    // RED: < 50% - Issues found
    return {
      icon: <CircleX className="h-4 w-4 text-red-600 dark:text-red-500" />,
      label: "Check Carefully",
      color: "text-red-600 dark:text-red-500",
      bgColor: "bg-red-50 dark:bg-red-950/30",
      hint: issues.length > 0 ? getActionableHint(issues) : "Multiple issues detected",
    };
  }, [finalScore, factualAlignment, contradictionScore, hallucinationRisk]);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <button className="w-full flex items-center justify-between p-3 hover:bg-muted/50 rounded-lg transition-colors border border-transparent hover:border-border">
          <div className="flex items-center gap-2">
            <BarChart3 className="h-4 w-4 text-muted-foreground" />
            <div className="flex flex-col items-start">
              <span className="font-medium text-sm">Answer Comparison Score</span>
              <span className="text-xs text-muted-foreground">How similar is RAG&apos;s answer to staff&apos;s answer?</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {/* Traffic Light System - Level 1: Quick visual assessment */}
            {trafficLight && (
              <div className={cn(
                "flex items-center gap-2 px-2 py-1 rounded-md",
                trafficLight.bgColor
              )}>
                {trafficLight.icon}
                <span className={cn("text-sm font-medium", trafficLight.color)}>
                  {trafficLight.label}
                </span>
                {trafficLight.hint && (
                  <TooltipProvider>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Info className="h-3.5 w-3.5 text-muted-foreground cursor-help" />
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="max-w-[200px]">
                        <p className="text-sm">{trafficLight.hint}</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                )}
              </div>
            )}
            {finalScore !== null && (
              <div className="flex items-center gap-2">
                <span className="text-lg font-bold text-foreground tabular-nums">
                  {(finalScore * 100).toFixed(0)}%
                </span>
                {routing && (
                  <Badge
                    variant="outline"
                    className={cn(
                      "text-xs px-2 py-0.5",
                      routing.color,
                      "border-border/50"
                    )}
                  >
                    {routing.label}
                  </Badge>
                )}
              </div>
            )}
            {isOpen ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </div>
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 pb-3 pt-2 space-y-4">
          {/* Level 2: Detailed metrics breakdown (shown on expand) */}

          {/* RAG Confidence - shown only when available, at the top */}
          {generationConfidence !== null && generationConfidence !== undefined && (
            <>
              <ScoreBar metricKey="generationConfidence" value={generationConfidence} />
              <div className="border-t border-border/50 my-2" />
            </>
          )}

          {/* Comparison metrics - 5 core metrics */}
          <ScoreBar metricKey="embeddingSimilarity" value={embeddingSimilarity} />
          <ScoreBar metricKey="factualAlignment" value={factualAlignment} />
          <ScoreBar metricKey="contradictionScore" value={contradictionScore} />
          <ScoreBar metricKey="completeness" value={completeness} />
          <ScoreBar metricKey="hallucinationRisk" value={hallucinationRisk} />

          {/* Routing thresholds - only visible in expanded view */}
          <RoutingThresholdFooter />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
});
