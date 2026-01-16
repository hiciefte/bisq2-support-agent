import * as React from 'react';
import { cn } from '@/lib/utils';
import { ReputationBadgeCompact } from './ReputationBadge';
import type { OfferCardProps } from '@/types/live-data';

/**
 * Compact card layout for mobile offer display
 *
 * Features:
 * - Direction indicator (Buy/Sell) with color coding
 * - Price and amount display
 * - Payment method badges
 * - Reputation score
 * - Dark mode support
 * - Accessible structure
 */
const OfferCard = React.forwardRef<HTMLDivElement, OfferCardProps>(
  ({ offer, className }, ref) => {
    const {
      direction,
      formattedPrice,
      formattedQuoteAmount,
      paymentMethods,
      reputationScore,
      pricePercentage,
    } = offer;

    // Direction styling and label (from USER's perspective)
    // Direction is already USER-CENTRIC from backend: 'buy' = user buys BTC, 'sell' = user sells BTC
    const getDirectionInfo = (userDirection: 'buy' | 'sell') => {
      if (userDirection === 'buy') {
        // User buys BTC (green - getting BTC)
        return {
          label: 'Buy from',
          bg: 'bg-emerald-100 dark:bg-emerald-900/30',
          text: 'text-emerald-700 dark:text-emerald-400',
          border: 'border-emerald-200 dark:border-emerald-800',
        };
      }
      // User sells BTC (red - giving away BTC)
      return {
        label: 'Sell to',
        bg: 'bg-red-100 dark:bg-red-900/30',
        text: 'text-red-700 dark:text-red-400',
        border: 'border-red-200 dark:border-red-800',
      };
    };

    // Get color class for price percentage (green for discount, red for premium)
    const getPricePercentageStyle = (percentage: string | undefined) => {
      if (!percentage) return 'text-muted-foreground';
      const value = parseFloat(percentage.replace('%', ''));
      if (isNaN(value) || value === 0) return 'text-muted-foreground';
      if (value > 0) return 'text-red-600 dark:text-red-400'; // Premium (buyer pays more)
      return 'text-emerald-600 dark:text-emerald-400'; // Discount (buyer pays less)
    };

    const dirInfo = getDirectionInfo(direction);

    return (
      <article
        ref={ref}
        role="article"
        aria-label={`${dirInfo.label} offer at ${formattedPrice}`}
        className={cn(
          'rounded-lg border bg-card p-3 shadow-sm transition-colors hover:bg-accent/5',
          'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2',
          dirInfo.border,
          className
        )}
      >
        {/* Header: Direction (from user's perspective) and Price */}
        <div className="flex items-center justify-between mb-2">
          <span
            className={cn(
              'inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold',
              dirInfo.bg,
              dirInfo.text
            )}
          >
            {dirInfo.label}
          </span>
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-medium text-foreground">
              {formattedPrice}
            </span>
            {pricePercentage && (
              <span
                className={cn(
                  'font-mono text-xs',
                  getPricePercentageStyle(pricePercentage)
                )}
              >
                ({pricePercentage})
              </span>
            )}
          </div>
        </div>

        {/* Amount */}
        <div className="mb-2">
          <span className="text-xs text-muted-foreground">Amount: </span>
          <span className="font-mono text-sm text-foreground">
            {formattedQuoteAmount}
          </span>
        </div>

        {/* Payment Methods */}
        <div className="flex flex-wrap gap-1 mb-2">
          {paymentMethods.slice(0, 3).map((method, index) => (
            <span
              key={index}
              className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground"
            >
              {method}
            </span>
          ))}
          {paymentMethods.length > 3 && (
            <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
              +{paymentMethods.length - 3}
            </span>
          )}
        </div>

        {/* Reputation */}
        <div className="flex items-center justify-end">
          <ReputationBadgeCompact score={reputationScore} />
        </div>
      </article>
    );
  }
);

OfferCard.displayName = 'OfferCard';

export { OfferCard };
