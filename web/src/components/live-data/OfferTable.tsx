import * as React from 'react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { AlertTriangle } from 'lucide-react';
import { LiveDataBadge } from './LiveDataBadge';
import { OfferCard } from './OfferCard';
import { ReputationBadgeCompact } from './ReputationBadge';
import type { OfferTableProps } from '@/types/live-data';

/**
 * Responsive table component for displaying Bisq 2 offers
 *
 * Features:
 * - Desktop view: Full table with columns (Type, Price, Amount, Methods, Rep)
 * - Mobile view: Card stack layout (hidden md:block / md:hidden pattern)
 * - Buy offers: Green indicator
 * - Sell offers: Red indicator
 * - Shows offer count with LiveDataBadge
 * - Limits display to maxOffers (default: 5)
 * - Dark mode support
 * - Accessible table structure
 */
interface ExtendedOfferTableProps extends OfferTableProps {
  error?: Error | null;
  onRetry?: () => void;
}

const OfferTable = React.forwardRef<HTMLDivElement, ExtendedOfferTableProps>(
  ({ offers, currency, maxOffers = 5, meta, className, error, onRetry }, ref) => {
    // Handle error state
    if (error) {
      return (
        <div
          ref={ref}
          role="region"
          aria-label={`${currency} offers error`}
          className={cn('w-full', className)}
        >
          <div className="flex flex-col items-center justify-center p-8 rounded-lg border border-destructive/20 bg-destructive/5">
            <AlertTriangle className="h-8 w-8 text-destructive mb-3" aria-hidden="true" />
            <p className="text-sm text-destructive mb-3">Failed to load {currency} offers</p>
            {onRetry && (
              <Button variant="outline" size="sm" onClick={onRetry}>
                Retry
              </Button>
            )}
          </div>
        </div>
      );
    }

    // Limit displayed offers
    const displayedOffers = offers.slice(0, maxOffers);
    const hasMore = offers.length > maxOffers;

    // Direction badge styling
    const getDirectionStyle = (direction: 'buy' | 'sell') => {
      if (direction === 'buy') {
        return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400';
      }
      return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400';
    };

    return (
      <div
        ref={ref}
        role="region"
        aria-label={`${currency} offers`}
        aria-live="polite"
        className={cn('w-full', className)}
      >
        {/* Header with offer count and data freshness */}
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-medium text-foreground">
              {currency} Offers
            </h3>
            <span className="text-xs text-muted-foreground">
              ({offers.length} available)
            </span>
          </div>
          {meta && (
            <LiveDataBadge
              type={meta.type}
              timestamp={meta.timestamp}
            />
          )}
        </div>

        {/* Desktop Table View */}
        <div className="hidden md:block">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-16">Type</TableHead>
                <TableHead>Price</TableHead>
                <TableHead>Amount</TableHead>
                <TableHead>Methods</TableHead>
                <TableHead className="w-20 text-right">Rep</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayedOffers.length === 0 ? (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="h-24 text-center text-muted-foreground"
                  >
                    No offers available
                  </TableCell>
                </TableRow>
              ) : (
                displayedOffers.map((offer, index) => (
                  <TableRow key={index}>
                    {/* Direction */}
                    <TableCell>
                      <span
                        className={cn(
                          'inline-flex items-center rounded px-1.5 py-0.5 text-xs font-semibold uppercase',
                          getDirectionStyle(offer.direction)
                        )}
                      >
                        {offer.direction}
                      </span>
                    </TableCell>

                    {/* Price */}
                    <TableCell className="font-mono text-sm">
                      {offer.formattedPrice}
                    </TableCell>

                    {/* Amount */}
                    <TableCell className="font-mono text-sm text-muted-foreground">
                      {offer.formattedQuoteAmount}
                    </TableCell>

                    {/* Payment Methods */}
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {offer.paymentMethods.slice(0, 2).map((method, idx) => (
                          <span
                            key={idx}
                            className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-secondary-foreground"
                          >
                            {method}
                          </span>
                        ))}
                        {offer.paymentMethods.length > 2 && (
                          <span className="inline-flex items-center rounded-full bg-secondary px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                            +{offer.paymentMethods.length - 2}
                          </span>
                        )}
                      </div>
                    </TableCell>

                    {/* Reputation */}
                    <TableCell className="text-right">
                      <ReputationBadgeCompact score={offer.reputationScore} />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </div>

        {/* Mobile Card View */}
        <div className="md:hidden space-y-2">
          {displayedOffers.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
              No offers available
            </div>
          ) : (
            displayedOffers.map((offer, index) => (
              <OfferCard key={index} offer={offer} />
            ))
          )}
        </div>

        {/* Show more indicator */}
        {hasMore && (
          <p className="mt-2 text-center text-xs text-muted-foreground">
            +{offers.length - maxOffers} more offers available
          </p>
        )}
      </div>
    );
  }
);

OfferTable.displayName = 'OfferTable';

export { OfferTable };
