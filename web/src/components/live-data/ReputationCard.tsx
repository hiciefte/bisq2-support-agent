import * as React from 'react';
import { cn } from '@/lib/utils';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { LiveDataBadge } from './LiveDataBadge';
import { ReputationBadge } from './ReputationBadge';
import { Trophy, Calendar, Hash, User, Medal } from 'lucide-react';
import type { ReputationCardProps } from '@/types/live-data';

/**
 * Card component for displaying Bisq 2 user reputation data
 *
 * Features:
 * - Profile ID (truncated)
 * - Total reputation score with formatting
 * - Star rating display
 * - Ranking position
 * - Profile age in days
 * - LiveDataBadge for freshness indicator
 * - Dark mode support
 * - Accessible structure
 */
const ReputationCard = React.forwardRef<HTMLDivElement, ReputationCardProps>(
  ({ reputation, className }, ref) => {
    const {
      profileId,
      nickName,
      totalScore,
      starRating,
      ranking,
      profileAgeDays,
      meta,
    } = reputation;

    // Format total score with commas
    const formattedTotalScore = totalScore.toLocaleString();

    return (
      <Card
        ref={ref}
        className={cn(
          'w-full border-emerald-200/50 dark:border-emerald-800/50',
          className
        )}
      >
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-medium text-foreground">
              User Reputation
            </CardTitle>
            <LiveDataBadge type={meta.type} timestamp={meta.timestamp} />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {/* Nickname (if available) */}
          {nickName && (
            <div className="flex items-center gap-2 text-sm">
              <User className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <span className="text-muted-foreground">Nickname:</span>
              <span className="font-semibold text-foreground">{nickName}</span>
            </div>
          )}

          {/* Profile ID */}
          <div className="flex items-center gap-2 text-sm">
            <Hash className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="text-muted-foreground">Profile:</span>
            <code className="rounded bg-muted px-1.5 py-0.5 text-xs font-mono">
              {profileId}
            </code>
          </div>

          {/* Total Score */}
          <div className="flex items-center gap-2 text-sm">
            <Trophy className="h-4 w-4 text-amber-500" aria-hidden="true" />
            <span className="text-muted-foreground">Total Score:</span>
            <span className="font-semibold text-foreground">
              {formattedTotalScore}
            </span>
          </div>

          {/* Star Rating */}
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground ml-6">Rating:</span>
            <ReputationBadge score={starRating} />
          </div>

          {/* Ranking */}
          <div className="flex items-center gap-2 text-sm">
            <Medal className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            <span className="text-muted-foreground">Ranking:</span>
            <span className="font-semibold text-foreground">#{ranking}</span>
          </div>

          {/* Profile Age */}
          {profileAgeDays !== undefined && (
            <div className="flex items-center gap-2 text-sm">
              <Calendar className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
              <span className="text-muted-foreground">Profile Age:</span>
              <span className="font-medium text-foreground">
                {profileAgeDays} days
              </span>
            </div>
          )}
        </CardContent>
      </Card>
    );
  }
);

ReputationCard.displayName = 'ReputationCard';

export { ReputationCard };
