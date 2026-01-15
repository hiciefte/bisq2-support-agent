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
    } = offer;

    // Direction styling
    const directionStyles = {
      buy: {
        bg: 'bg-emerald-100 dark:bg-emerald-900/30',
        text: 'text-emerald-700 dark:text-emerald-400',
        border: 'border-emerald-200 dark:border-emerald-800',
      },
      sell: {
        bg: 'bg-red-100 dark:bg-red-900/30',
        text: 'text-red-700 dark:text-red-400',
        border: 'border-red-200 dark:border-red-800',
      },
    };

    const styles = directionStyles[direction];

    return (
      <article
        ref={ref}
        role="article"
        aria-label={`${direction === 'buy' ? 'Buy' : 'Sell'} offer at ${formattedPrice}`}
        className={cn(
          'rounded-lg border bg-card p-3 shadow-sm transition-colors hover:bg-accent/5',
          'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2',
          styles.border,
          className
        )}
      >
        {/* Header: Direction and Price */}
        <div className="flex items-center justify-between mb-2">
          <span
            className={cn(
              'inline-flex items-center rounded px-2 py-0.5 text-xs font-semibold uppercase',
              styles.bg,
              styles.text
            )}
          >
            {direction}
          </span>
          <span className="font-mono text-sm font-medium text-foreground">
            {formattedPrice}
          </span>
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
