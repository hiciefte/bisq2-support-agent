'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { formatCurrency } from '@/lib/live-data-utils';
import { LiveDataBadge } from './LiveDataBadge';
import type { PriceDisplayProps } from '@/types/live-data';

/**
 * Component for displaying live market prices
 *
 * Features:
 * - Formatted currency display with proper symbols
 * - Monospace font for price values
 * - Optional change percentage indicator
 * - LiveDataBadge integration for freshness
 * - Dark mode support
 * - Accessible with aria-live for updates
 */
const PriceDisplay = React.forwardRef<HTMLDivElement, PriceDisplayProps>(
  ({ price, currency, meta, changePercent, className }, ref) => {
    // Format the price
    const formattedPrice = React.useMemo(
      () => formatCurrency(price, currency),
      [price, currency]
    );

    // Determine change direction and styling
    const changeInfo = React.useMemo(() => {
      if (changePercent === undefined || changePercent === 0) {
        return null;
      }

      const isPositive = changePercent > 0;
      return {
        isPositive,
        text: `${isPositive ? '+' : ''}${changePercent.toFixed(2)}%`,
        colorClass: isPositive
          ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-red-600 dark:text-red-400',
        arrow: isPositive ? '↑' : '↓',
      };
    }, [changePercent]);

    return (
      <div
        ref={ref}
        role="region"
        aria-label={`${currency} price: ${formattedPrice}`}
        aria-live="polite"
        className={cn(
          'inline-flex items-center gap-2 flex-wrap',
          className
        )}
      >
        {/* Price value with monospace font */}
        <span
          className="font-mono text-lg font-semibold text-foreground tabular-nums"
          aria-hidden="true"
        >
          {formattedPrice}
        </span>

        {/* Change percentage indicator */}
        {changeInfo && (
          <span
            className={cn(
              'inline-flex items-center gap-0.5 text-sm font-medium',
              changeInfo.colorClass
            )}
            aria-label={`Price change: ${changeInfo.text}`}
          >
            <span aria-hidden="true">{changeInfo.arrow}</span>
            <span>{changeInfo.text}</span>
          </span>
        )}

        {/* Live data badge */}
        <LiveDataBadge
          type={meta.type}
          timestamp={meta.timestamp}
        />
      </div>
    );
  }
);

PriceDisplay.displayName = 'PriceDisplay';

export { PriceDisplay };
