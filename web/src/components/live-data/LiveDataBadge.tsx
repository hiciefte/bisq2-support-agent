import * as React from 'react';
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
 * Badge component indicating data freshness status
 *
 * Features:
 * - Live: Subtle emerald text with small dot indicator
 * - Cached/Stale: Muted foreground colors
 * - Accessible with aria-label and keyboard navigation
 * - Progressive disclosure via tooltip
 *
 * Design Principles Applied:
 * - Speed Through Subtraction: No backgrounds, minimal visual weight
 * - Spatial Consistency: Uses rounded-md to match sibling badges
 * - Keyboard Accessibility: Focusable with visible focus ring
 * - Progressive Disclosure: Tooltip reveals tool details on hover/focus
 */
const LiveDataBadge = React.forwardRef<HTMLSpanElement, LiveDataBadgeProps>(
  ({ type, timestamp, toolsUsed, className }, ref) => {
    // Parse and format timestamp if provided
    const formattedTime = React.useMemo(() => {
      if (!timestamp) return null;
      const date = parseTimestamp(timestamp);
      if (!date) return null;
      return formatTimestamp(date);
    }, [timestamp]);

    // Consolidated type configuration
    // UI/UX Fix: Subtle text-only styling to reduce visual hierarchy fragmentation
    // No background colors - matches sibling badges (SourceLinksTrigger, ConfidenceBadge)
    const typeConfig = {
      live: {
        style: 'text-emerald-700 dark:text-emerald-400',
        label: 'Live data',
        description: 'Real-time data from Bisq 2 network',
        indicatorClass: 'bg-emerald-500 dark:bg-emerald-400',
      },
      cached: {
        style: 'text-muted-foreground',
        label: 'Cached data',
        description: 'Recently fetched data, may be slightly outdated',
        indicatorClass: 'bg-muted-foreground/50',
      },
      stale: {
        style: 'text-muted-foreground/70',
        label: 'Stale data',
        description: 'Data may be outdated, refresh recommended',
        indicatorClass: 'bg-muted-foreground/30',
      },
    };

    const config = typeConfig[type];

    // Generate aria-label
    const ariaLabel = formattedTime
      ? `${config.label}, updated ${formattedTime.text}`
      : config.label;

    // Format tools list for tooltip
    const toolsDescription = React.useMemo(() => {
      if (!toolsUsed || toolsUsed.length === 0) return null;
      return toolsUsed.map(tool => {
        const toolNames: Record<string, string> = {
          get_market_prices: 'Market Prices',
          get_offerbook: 'Offerbook',
          get_reputation: 'Reputation',
          get_markets: 'Markets',
        };
        return toolNames[tool] || tool;
      }).join(', ');
    }, [toolsUsed]);

    const badgeContent = (
      <span
        ref={ref}
        role="status"
        aria-label={ariaLabel}
        tabIndex={0}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium',
          'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring',
          'min-h-[28px]',
          'transition-colors duration-200 hover:opacity-90',
          config.style,
          className
        )}
      >
        {/* Simple static dot indicator - no pulse animation for visual subtlety */}
        <span
          className={cn('inline-flex h-1.5 w-1.5 rounded-full', config.indicatorClass)}
          aria-hidden="true"
        />

        <span className="capitalize">{type}</span>

        {formattedTime && (
          <>
            <span aria-hidden="true">·</span>
            {/* UI/UX Fix: Use consistent muted-foreground instead of amber colors */}
            <span className="text-[10px] text-muted-foreground">
              {formattedTime.text}
            </span>
          </>
        )}
      </span>
    );

    // Wrap with tooltip for progressive disclosure
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            {badgeContent}
          </TooltipTrigger>
          <TooltipContent side="top" className="max-w-[280px]">
            <p className="text-xs">{config.description}</p>
            {toolsDescription && (
              <p className="text-xs text-muted-foreground mt-1">
                Data from: {toolsDescription}
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
