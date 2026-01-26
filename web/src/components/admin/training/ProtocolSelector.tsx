"use client";

import { useState, useEffect, useRef, memo, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { RefreshCw, Loader2, AlertTriangle } from "lucide-react";

export type ProtocolType = "bisq_easy" | "multisig_v1" | "musig" | "all";

const PROTOCOLS = [
  { value: "bisq_easy" as const, label: "Bisq Easy" },
  { value: "multisig_v1" as const, label: "Bisq 1 (Multisig)" },
  { value: "musig" as const, label: "MuSig" },
  { value: "all" as const, label: "All Protocols" },
];

// Color classes for the protocol dot indicator - subtle
const getProtocolDotColor = (value: string): string => {
  const colors: Record<string, string> = {
    bisq_easy: "bg-foreground/60",
    multisig_v1: "bg-foreground/60",
    musig: "bg-foreground/60",
    all: "bg-foreground/60",
  };
  return colors[value] || "bg-muted-foreground";
};

// Color classes for selected button state - subtle, muted
const getSelectedButtonClasses = (): string => {
  return "bg-background text-foreground shadow-sm ring-1 ring-border";
};

// Protocol badge colors for display in other contexts
export const getProtocolBadgeColor = (protocol: string): string => {
  switch (protocol) {
    case "bisq_easy":
      return "bg-green-50 text-green-700 border-green-300 dark:bg-green-900/30 dark:text-green-400 dark:border-green-700";
    case "multisig_v1":
      return "bg-blue-50 text-blue-700 border-blue-300 dark:bg-blue-900/30 dark:text-blue-400 dark:border-blue-700";
    case "musig":
      return "bg-orange-50 text-orange-700 border-orange-300 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-700";
    case "all":
    default:
      return "bg-purple-50 text-purple-700 border-purple-300 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-700";
  }
};

interface ProtocolSelectorProps {
  currentProtocol: ProtocolType | null;
  onProtocolChange: (protocol: ProtocolType) => void;
  onRegenerateAnswer: (protocol: ProtocolType) => Promise<void>;
  isRegenerating: boolean;
  showRegeneratePrompt: boolean;
  /** Auto-regenerate answer when protocol changes (with 500ms debounce) */
  autoRegenerate?: boolean;
}

// Memoized ProtocolSelector component to prevent unnecessary re-renders (Rule 5.2)
export const ProtocolSelector = memo(function ProtocolSelector({
  currentProtocol,
  onProtocolChange,
  onRegenerateAnswer,
  isRegenerating,
  showRegeneratePrompt,
  autoRegenerate = true, // Default to auto-regenerate (Speed Through Subtraction)
}: ProtocolSelectorProps) {
  const [selectedProtocol, setSelectedProtocol] = useState<ProtocolType | null>(
    currentProtocol
  );
  const autoRegenerateTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const isInitialMount = useRef(true);

  useEffect(() => {
    setSelectedProtocol(currentProtocol);
    isInitialMount.current = true; // Reset on candidate change
  }, [currentProtocol]);

  // Auto-regenerate effect with 500ms debounce
  // Speed Through Subtraction: Auto-generate when protocol first selected OR changed
  useEffect(() => {
    if (!autoRegenerate || !selectedProtocol || isRegenerating) {
      return;
    }

    // Trigger auto-regenerate when:
    // 1. Protocol is selected for the first time (currentProtocol was null)
    // 2. Protocol has changed to a different value
    const isFirstSelection = currentProtocol === null && selectedProtocol !== null;
    const hasProtocolChanged = selectedProtocol !== currentProtocol && currentProtocol !== null;

    if (isFirstSelection || hasProtocolChanged) {
      // Skip if this is initial mount with an existing protocol
      if (isInitialMount.current && !isFirstSelection) {
        isInitialMount.current = false;
        return;
      }
      isInitialMount.current = false;

      // Clear any existing timeout
      if (autoRegenerateTimeoutRef.current) {
        clearTimeout(autoRegenerateTimeoutRef.current);
      }

      // Set new timeout for debounced regeneration
      autoRegenerateTimeoutRef.current = setTimeout(() => {
        onRegenerateAnswer(selectedProtocol);
      }, 500);
    }

    // Cleanup on unmount or dependency change
    return () => {
      if (autoRegenerateTimeoutRef.current) {
        clearTimeout(autoRegenerateTimeoutRef.current);
      }
    };
  }, [selectedProtocol, currentProtocol, autoRegenerate, isRegenerating, onRegenerateAnswer]);

  // Memoized handlers to prevent unnecessary re-renders (Rule 5.5)
  const handleProtocolSelect = useCallback((protocol: ProtocolType) => {
    setSelectedProtocol(protocol);
    onProtocolChange(protocol);
  }, [onProtocolChange]);

  const handleRegenerate = useCallback(async () => {
    if (selectedProtocol) {
      // Clear any pending auto-regenerate
      if (autoRegenerateTimeoutRef.current) {
        clearTimeout(autoRegenerateTimeoutRef.current);
      }
      await onRegenerateAnswer(selectedProtocol);
    }
  }, [selectedProtocol, onRegenerateAnswer]);

  // Show prominent regenerate when protocol changed or no answer exists
  const hasProtocolChanged =
    selectedProtocol !== currentProtocol && selectedProtocol !== null;
  const needsGeneration = showRegeneratePrompt || hasProtocolChanged;

  return (
    <div className="flex flex-col gap-2">
      {/* Label row */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Protocol
        </span>
        {showRegeneratePrompt && !currentProtocol && (
          <span className="inline-flex items-center gap-1 text-xs text-amber-600 dark:text-amber-400">
            <AlertTriangle className="h-3 w-3" />
            Select protocol
          </span>
        )}
      </div>

      {/* Controls row - segmented control + regenerate button */}
      <div className="flex items-center gap-2">
        {/* Segmented Control */}
        <div className="inline-flex rounded-lg bg-muted p-1 gap-0.5">
          {PROTOCOLS.map((protocol) => (
            <button
              key={protocol.value}
              onClick={() => handleProtocolSelect(protocol.value)}
              className={cn(
                "px-3 py-1.5 text-xs font-medium rounded-md transition-all",
                "flex items-center gap-1.5",
                selectedProtocol === protocol.value
                  ? getSelectedButtonClasses()
                  : "text-muted-foreground hover:text-foreground hover:bg-muted-foreground/10"
              )}
              type="button"
            >
              <span
                className={cn(
                  "h-2 w-2 rounded-full transition-opacity",
                  getProtocolDotColor(protocol.value),
                  selectedProtocol === protocol.value
                    ? "opacity-100"
                    : "opacity-40"
                )}
              />
              {protocol.label}
            </button>
          ))}
        </div>

        {/* Regenerate Button - compact, inline, green highlight when needs generation */}
        <Button
          onClick={handleRegenerate}
          disabled={isRegenerating || !selectedProtocol}
          variant={needsGeneration ? "default" : "ghost"}
          size="sm"
          className={cn(
            "h-8 px-3 transition-all",
            needsGeneration &&
              !isRegenerating &&
              "bg-green-600 hover:bg-green-700 text-white dark:bg-green-600 dark:hover:bg-green-700"
          )}
        >
          {isRegenerating ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RefreshCw className="h-3.5 w-3.5" />
          )}
          <span className="ml-1.5 text-xs">
            {showRegeneratePrompt ? "Generate Answer" : "Regenerate"}
          </span>
        </Button>
      </div>
    </div>
  );
});
