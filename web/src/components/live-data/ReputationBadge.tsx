import * as React from 'react';
import { cn } from '@/lib/utils';
import { getReputationLevel, getStarRating } from '@/lib/live-data-utils';
import type { ReputationBadgeProps } from '@/types/live-data';

/**
 * Badge component displaying user reputation score
 *
 * Features:
 * - Star rating display (★★★★☆ pattern)
 * - Semantic color coding by score range:
 *   - 4.5-5.0: Emerald (Excellent)
 *   - 3.5-4.4: Blue (Good)
 *   - 2.5-3.4: Amber (Fair)
 *   - 0.0-2.4: Gray (New)
 * - Dark mode support
 * - Accessible with aria-label
 */
const ReputationBadge = React.forwardRef<HTMLSpanElement, ReputationBadgeProps>(
  ({ score, className }, ref) => {
    // Get reputation level info
    const { label, colorClass } = React.useMemo(
      () => getReputationLevel(score),
      [score]
    );

    // Generate star rating
    const stars = React.useMemo(
      () => getStarRating(score),
      [score]
    );

    // Format score for display
    const formattedScore = score.toFixed(1);

    return (
      <span
        ref={ref}
        role="img"
        aria-label={`Reputation: ${formattedScore} out of 5 stars, rated ${label}`}
        className={cn(
          'inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs font-medium',
          colorClass,
          className
        )}
      >
        {/* Star rating */}
        <span
          className="tracking-tight"
          aria-hidden="true"
        >
          {stars}
        </span>

        {/* Numeric score */}
        <span
          className="font-mono text-[10px] opacity-80"
          aria-hidden="true"
        >
          ({formattedScore})
        </span>
      </span>
    );
  }
);

ReputationBadge.displayName = 'ReputationBadge';

/**
 * Compact version of ReputationBadge for table cells
 */
const ReputationBadgeCompact = React.forwardRef<
  HTMLSpanElement,
  ReputationBadgeProps
>(({ score, className }, ref) => {
  const { colorClass } = React.useMemo(
    () => getReputationLevel(score),
    [score]
  );

  const formattedScore = score.toFixed(1);

  return (
    <span
      ref={ref}
      role="img"
      aria-label={`Reputation score: ${formattedScore}`}
      className={cn(
        'inline-flex items-center gap-0.5 text-xs font-medium',
        colorClass.split(' ').filter(c => c.startsWith('text-')).join(' '),
        className
      )}
    >
      <span aria-hidden="true">★</span>
      <span className="font-mono">{formattedScore}</span>
    </span>
  );
});

ReputationBadgeCompact.displayName = 'ReputationBadgeCompact';

export { ReputationBadge, ReputationBadgeCompact };
