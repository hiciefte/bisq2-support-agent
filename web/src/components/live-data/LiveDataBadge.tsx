'use client';

import * as React from 'react';
import { Activity, Database, Clock } from 'lucide-react';
import { cn } from '@/lib/utils';
import { formatTimestamp, parseTimestamp } from '@/lib/live-data-utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { LiveDataBadgeProps } from '@/types/live-data';

/**
 * Tool metadata for enhanced tooltip display
 * Maps MCP tool names to human-readable labels and descriptions
 */
const TOOL_METADATA: Record<string, { label: string; description: string }> = {
  get_market_prices: {
    label: 'Market Prices',
    description: 'Current BTC exchange rates',
  },
  get_offerbook: {
    label: 'Offerbook',
    description: 'Active buy/sell offers',
  },
  get_reputation: {
    label: 'Reputation',
    description: 'Trader reputation scores',
  },
  get_markets: {
    label: 'Markets',
    description: 'Available trading pairs',
  },
};

/**
 * Badge component indicating data freshness status
 *
 * Features:
 * - Live: Emerald styling with activity icon
 * - Cached/Stale: Muted foreground colors with appropriate icons
 * - Fully keyboard accessible with proper focus management
 * - Progressive disclosure via tooltip showing MCP tool details
 *
 * Design Principles Applied:
 * - Speed Through Subtraction: Minimal visual weight, no heavy backgrounds
 * - Spatial Consistency: Matches SourceLinksTrigger and ConfidenceBadge exactly
 * - Keyboard Accessibility: Button element with visible focus ring (WCAG 2.1 AA)
 * - Progressive Disclosure: Tooltip reveals tool details on hover/focus
 * - Feedback Immediacy: Subtle hover state provides interaction feedback
 */
const LiveDataBadge = React.forwardRef<HTMLButtonElement, LiveDataBadgeProps>(
  ({ type, timestamp, toolsUsed, className }, ref) => {
    // Parse and format timestamp if provided
    const formattedTime = React.useMemo(() => {
      if (!timestamp) return null;
      const date = parseTimestamp(timestamp);
      if (!date) return null;
      return formatTimestamp(date);
    }, [timestamp]);

    // Type configuration with consistent styling matching sibling badges
    // Uses subtle background on hover (like ConfidenceBadge) for interaction feedback
    const typeConfig = {
      live: {
        textStyle: 'text-emerald-700 dark:text-emerald-400',
        hoverStyle: 'hover:bg-emerald-500/10',
        label: 'Live data',
        description: 'Real-time data from Bisq 2 network',
        indicatorClass: 'bg-emerald-500 dark:bg-emerald-400',
        Icon: Activity,
      },
      cached: {
        textStyle: 'text-muted-foreground',
        hoverStyle: 'hover:bg-muted/50',
        label: 'Cached data',
        description: 'Recently fetched data, may be slightly outdated',
        indicatorClass: 'bg-muted-foreground/50',
        Icon: Database,
      },
      stale: {
        textStyle: 'text-muted-foreground/70',
        hoverStyle: 'hover:bg-muted/30',
        label: 'Stale data',
        description: 'Data may be outdated, refresh recommended',
        indicatorClass: 'bg-muted-foreground/30',
        Icon: Clock,
      },
    };

    const config = typeConfig[type];
    const Icon = config.Icon;

    // Generate comprehensive aria-label
    const ariaLabel = React.useMemo(() => {
      const parts = [config.label];
      if (formattedTime) {
        parts.push(`updated ${formattedTime.text}`);
      }
      if (toolsUsed && toolsUsed.length > 0) {
        // Deduplicate tools for cleaner aria-label
        const uniqueTools = [...new Set(toolsUsed)];
        const toolLabels = uniqueTools
          .map(tool => TOOL_METADATA[tool]?.label || tool)
          .join(', ');
        parts.push(`using ${toolLabels}`);
      }
      return parts.join(', ');
    }, [config.label, formattedTime, toolsUsed]);

    // Format tools for tooltip with detailed descriptions
    // Deduplicate tools to avoid React key warnings
    const toolsInfo = React.useMemo(() => {
      if (!toolsUsed || toolsUsed.length === 0) return null;
      const uniqueTools = [...new Set(toolsUsed)];
      return uniqueTools.map(tool => ({
        name: tool,
        ...(TOOL_METADATA[tool] || { label: tool, description: 'MCP tool' }),
      }));
    }, [toolsUsed]);

    // Button element for proper keyboard accessibility (matches SourceLinksTrigger)
    const badgeContent = (
      <button
        ref={ref}
        type="button"
        aria-label={ariaLabel}
        className={cn(
          // Base styles matching SourceLinksTrigger and ConfidenceBadge exactly
          'inline-flex items-center gap-1.5 px-2 py-1 rounded-md',
          'text-xs font-medium',
          'min-h-[28px]',
          // Transition and hover (matching ConfidenceBadge pattern)
          'transition-colors duration-200',
          config.hoverStyle,
          // Focus ring matching ConfidenceBadge (focus-visible for keyboard-only)
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
          // Text color
          config.textStyle,
          className
        )}
      >
        {/* Icon indicator matching ConfidenceBadge pattern (Icon instead of dot) */}
        <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />

        <span className="capitalize">{type}</span>

        {formattedTime && (
          <>
            <span aria-hidden="true" className="text-muted-foreground/50">
              ·
            </span>
            <span className="text-[10px] text-muted-foreground font-normal">
              {formattedTime.text}
            </span>
          </>
        )}
      </button>
    );

    // Wrap with tooltip for progressive disclosure of tool details
    return (
      <TooltipProvider delayDuration={300}>
        <Tooltip>
          <TooltipTrigger asChild>{badgeContent}</TooltipTrigger>
          <TooltipContent
            side="top"
            align="start"
            className="max-w-[300px] p-3 bg-popover text-popover-foreground border border-border shadow-md"
            sideOffset={8}
          >
            {/* Primary description */}
            <p className="text-xs font-medium">{config.description}</p>

            {/* Tool details with enhanced layout */}
            {toolsInfo && toolsInfo.length > 0 && (
              <div className="mt-2 pt-2 border-t border-border/50">
                <p className="text-[10px] uppercase tracking-wide text-muted-foreground mb-1.5">
                  Data Sources
                </p>
                <ul className="space-y-1" role="list">
                  {toolsInfo.map(tool => (
                    <li
                      key={tool.name}
                      className="flex items-start gap-2 text-xs"
                    >
                      <span
                        className={cn(
                          'inline-block h-1.5 w-1.5 rounded-full mt-1.5 flex-shrink-0',
                          config.indicatorClass
                        )}
                        aria-hidden="true"
                      />
                      <span>
                        <span className="font-medium">{tool.label}</span>
                        <span className="text-muted-foreground">
                          {' '}
                          — {tool.description}
                        </span>
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Timestamp detail if available */}
            {formattedTime && (
              <p className="text-[10px] text-muted-foreground mt-2 pt-2 border-t border-border/50">
                Last updated: {formattedTime.text}
              </p>
            )}
          </TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }
);

LiveDataBadge.displayName = 'LiveDataBadge';

export { LiveDataBadge };
