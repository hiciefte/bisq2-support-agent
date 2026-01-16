'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import { getReputationLevel, getStarRating } from '@/lib/live-data-utils';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover';
import { MessageCircle } from 'lucide-react';
import { useChatActionsOptional } from '@/components/chat/context';
import type { ReputationBadgeProps } from '@/types/live-data';

/**
 * Props for the ReputationBadgeWithTooltip component
 */
interface ReputationBadgeWithTooltipProps extends ReputationBadgeProps {
  /** Maker's profile ID (for copy functionality) */
  makerProfileId?: string;
  /** Maker's nickname */
  makerNickName?: string;
}

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

/**
 * ReputationBadgeCompact with popover showing maker info
 * - Explains that Rep is the offer maker's reputation
 * - Shows maker nickname if available
 * - Provides button to ask for full reputation details
 * Uses Popover instead of Tooltip to allow button interaction
 */
const ReputationBadgeWithTooltip = React.forwardRef<
  HTMLSpanElement,
  ReputationBadgeWithTooltipProps
>(({ score, makerProfileId, makerNickName, className }, ref) => {
  const [open, setOpen] = React.useState(false);
  const chatActions = useChatActionsOptional();
  const { colorClass, label } = React.useMemo(
    () => getReputationLevel(score),
    [score]
  );

  const formattedScore = score.toFixed(1);

  const handleAskReputation = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (chatActions && makerProfileId) {
      const name = makerNickName ? `${makerNickName} ` : '';
      const question = `What is the reputation of ${name}(${makerProfileId})?`;
      chatActions.sendQuestion(question);
      setOpen(false); // Close popover after sending question
    }
  };

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <span
          ref={ref}
          role="img"
          aria-label={`Offer maker reputation: ${formattedScore} (${label})`}
          className={cn(
            'inline-flex items-center gap-0.5 text-xs font-medium cursor-pointer',
            colorClass.split(' ').filter(c => c.startsWith('text-')).join(' '),
            className
          )}
        >
          <span aria-hidden="true">★</span>
          <span className="font-mono">{formattedScore}</span>
        </span>
      </PopoverTrigger>
      <PopoverContent
        side="top"
        className="max-w-[280px] p-3"
      >
        <div className="space-y-2">
          <p className="font-medium text-sm">Offer Maker Reputation</p>
          <p className="text-xs text-muted-foreground">
            This is the reputation score of the trader who created this offer.
            Higher scores indicate more experienced and trusted traders.
          </p>
          <div className="pt-1 border-t border-border/50">
            <p className="text-xs">
              <span className="text-muted-foreground">Rating:</span>{' '}
              <span className="font-semibold">{formattedScore}/5.0 ({label})</span>
            </p>
            {makerNickName && (
              <p className="text-xs">
                <span className="text-muted-foreground">Nickname:</span>{' '}
                <span className="font-semibold">{makerNickName}</span>
              </p>
            )}
            {chatActions && makerProfileId && (
              <button
                onClick={handleAskReputation}
                className="mt-2 w-full flex items-center justify-center gap-1.5 px-2 py-1.5 text-xs font-medium rounded-md bg-primary/10 hover:bg-primary/20 text-primary transition-colors"
              >
                <MessageCircle className="h-3 w-3" />
                Ask for full reputation details
              </button>
            )}
          </div>
        </div>
      </PopoverContent>
    </Popover>
  );
});

ReputationBadgeWithTooltip.displayName = 'ReputationBadgeWithTooltip';

export { ReputationBadge, ReputationBadgeCompact, ReputationBadgeWithTooltip };
