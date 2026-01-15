import * as React from 'react';
import { cn } from '@/lib/utils';
import { formatTimestamp, parseTimestamp } from '@/lib/live-data-utils';
import type { LiveDataBadgeProps } from '@/types/live-data';

/**
 * Badge component indicating data freshness status
 *
 * Features:
 * - Live: Emerald green with pulse animation
 * - Cached: Amber without animation
 * - Stale: Gray
 * - Accessible with aria-label
 * - Supports dark mode
 * - Respects prefers-reduced-motion
 */
const LiveDataBadge = React.forwardRef<HTMLSpanElement, LiveDataBadgeProps>(
  ({ type, timestamp, className }, ref) => {
    // Parse and format timestamp if provided
    const formattedTime = React.useMemo(() => {
      if (!timestamp) return null;
      const date = parseTimestamp(timestamp);
      if (!date) return null;
      return formatTimestamp(date);
    }, [timestamp]);

    // Determine styles based on type
    const typeStyles = {
      live: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-400',
      cached: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
      stale: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    };

    // Labels for accessibility
    const typeLabels = {
      live: 'Live data',
      cached: 'Cached data',
      stale: 'Stale data',
    };

    // Generate aria-label
    const ariaLabel = formattedTime
      ? `${typeLabels[type]}, updated ${formattedTime.text}`
      : typeLabels[type];

    return (
      <span
        ref={ref}
        role="status"
        aria-label={ariaLabel}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium',
          typeStyles[type],
          className
        )}
      >
        {/* Pulse indicator for live data */}
        {type === 'live' && (
          <span
            className="relative flex h-2 w-2"
            aria-hidden="true"
          >
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75 motion-reduce:animate-none" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
          </span>
        )}

        {/* Static indicator for cached data */}
        {type === 'cached' && (
          <span
            className="inline-flex h-2 w-2 rounded-full bg-amber-500"
            aria-hidden="true"
          />
        )}

        {/* Static indicator for stale data */}
        {type === 'stale' && (
          <span
            className="inline-flex h-2 w-2 rounded-full bg-gray-400 dark:bg-gray-500"
            aria-hidden="true"
          />
        )}

        {/* Label text */}
        <span className="capitalize">{type}</span>

        {/* Timestamp if available */}
        {formattedTime && (
          <>
            <span aria-hidden="true">·</span>
            <span className={cn('text-[10px]', formattedTime.color)}>
              {formattedTime.text}
            </span>
          </>
        )}
      </span>
    );
  }
);

LiveDataBadge.displayName = 'LiveDataBadge';

export { LiveDataBadge };
