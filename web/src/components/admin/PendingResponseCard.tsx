/**
 * PendingResponseCard Component
 *
 * Displays a single pending response awaiting moderator review.
 *
 * Design Principles Applied:
 * - Speed Through Subtraction: Essential info only, no clutter
 * - Spatial Consistency: Fixed button positions (right side)
 * - Progressive Disclosure: Sources hidden by default, expand on click
 * - Feedback Immediacy: Optimistic UI with fade-out animation
 */

'use client';

import { useState } from 'react';
import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ChevronDown } from 'lucide-react';
import { cn } from '@/lib/utils';
import type { PendingResponse } from '@/types/pending-response';

interface PendingResponseCardProps {
  response: PendingResponse;
  onApprove: () => void;
  onEdit: () => void;
  onReject: () => void;
  isRemoving?: boolean;
}

export function PendingResponseCard({
  response,
  onApprove,
  onEdit,
  onReject,
  isRemoving = false,
}: PendingResponseCardProps) {
  const [sourcesExpanded, setSourcesExpanded] = useState(false);

  // Confidence badge color and level
  const getConfidenceDisplay = (confidence: number) => {
    const percentage = Math.round(confidence * 100);

    if (confidence >= 0.8) {
      return {
        color: 'bg-green-500',
        level: 'High',
        text: `${percentage}% High`,
      };
    }

    if (confidence >= 0.5) {
      return {
        color: 'bg-yellow-500',
        level: 'Medium',
        text: `${percentage}% Medium`,
      };
    }

    return {
      color: 'bg-red-500',
      level: 'Low',
      text: `${percentage}% Low`,
    };
  };

  // Human-readable time ago
  const getTimeAgo = (timestamp: string): string => {
    const now = Date.now();
    const created = new Date(timestamp).getTime();
    const diffSeconds = Math.floor((now - created) / 1000);

    if (diffSeconds < 60) return 'just now';

    const diffMinutes = Math.floor(diffSeconds / 60);
    if (diffMinutes < 60) {
      return diffMinutes === 1 ? '1 min ago' : `${diffMinutes} min ago`;
    }

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) {
      return diffHours === 1 ? '1 hour ago' : `${diffHours} hours ago`;
    }

    const diffDays = Math.floor(diffHours / 24);
    return diffDays === 1 ? '1 day ago' : `${diffDays} days ago`;
  };

  const confidenceDisplay = getConfidenceDisplay(response.confidence);
  const timeAgo = getTimeAgo(response.created_at);
  const hasSources = response.sources && response.sources.length > 0;

  return (
    <Card
      data-testid="pending-response-card"
      className={cn(
        'p-4 transition-all duration-200 hover:shadow-md',
        isRemoving && 'opacity-0'
      )}
    >
      {/* Header: Badges and Time */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Badge
            data-testid="confidence-badge"
            className={cn('text-white', confidenceDisplay.color)}
          >
            {confidenceDisplay.text}
          </Badge>

          <Badge data-testid="version-badge" variant="outline">
            {response.detected_version}
          </Badge>
        </div>

        <span
          data-testid="time-ago"
          className="text-sm text-muted-foreground"
        >
          {timeAgo}
        </span>
      </div>

      {/* Question */}
      <div className="mb-3">
        <h3 className="text-sm font-medium text-muted-foreground mb-1">
          Question
        </h3>
        <p data-testid="question-text" className="text-base">
          {response.question}
        </p>
      </div>

      {/* Answer */}
      <div className="mb-4">
        <h3 className="text-sm font-medium text-muted-foreground mb-1">
          Answer
        </h3>
        <p data-testid="answer-text" className="text-base">
          {response.answer}
        </p>
      </div>

      {/* Sources (Progressive Disclosure) */}
      {hasSources && (
        <div className="mb-4">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSourcesExpanded(!sourcesExpanded)}
            className="p-0 h-auto font-normal text-muted-foreground hover:text-foreground"
          >
            <ChevronDown
              className={cn(
                'h-4 w-4 mr-1 transition-transform duration-200',
                sourcesExpanded && 'rotate-180'
              )}
            />
            View {response.sources.length} source
            {response.sources.length !== 1 ? 's' : ''}
          </Button>

          {sourcesExpanded && (
            <div className="mt-2 space-y-1 animate-in slide-in-from-top-2 duration-250">
              {response.sources.map((source, index) => (
                <div
                  key={index}
                  className="text-sm text-muted-foreground pl-5"
                >
                  <a
                    href={source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-foreground hover:underline"
                  >
                    {source.title}
                  </a>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Action Buttons (Fixed Right Position) */}
      <div className="flex items-center justify-end gap-2">
        <Button
          variant="outline"
          size="sm"
          onClick={onReject}
          disabled={isRemoving}
          aria-label="Reject this response"
        >
          Reject
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={onEdit}
          disabled={isRemoving}
          aria-label="Edit this response before approving"
        >
          Edit
        </Button>

        <Button
          size="sm"
          onClick={onApprove}
          disabled={isRemoving}
          aria-label="Approve and send this response"
        >
          Approve
        </Button>
      </div>
    </Card>
  );
}
