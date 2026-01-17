'use client';

import * as React from 'react';
import { cn } from '@/lib/utils';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';
import type { DataUnavailableBadgeProps } from '@/types/live-data';

/**
 * AlertTriangle icon component (inline to avoid external dependencies)
 */
const AlertTriangleIcon = React.forwardRef<
  SVGSVGElement,
  React.SVGProps<SVGSVGElement>
>((props, ref) => (
  <svg
    ref={ref}
    xmlns="http://www.w3.org/2000/svg"
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
    {...props}
  >
    <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
    <path d="M12 9v4" />
    <path d="M12 17h.01" />
  </svg>
));
AlertTriangleIcon.displayName = 'AlertTriangleIcon';

/**
 * Badge component for indicating data unavailability
 *
 * Features:
 * - Amber warning styling
 * - AlertTriangle icon
 * - Tooltip with explanation on hover
 * - Dark mode support
 * - Accessible with aria-label
 * - Uses shadcn Tooltip component
 */
const DataUnavailableBadge = React.forwardRef<
  HTMLSpanElement,
  DataUnavailableBadgeProps
>(({ reason, className }, ref) => {
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            ref={ref}
            role="status"
            aria-label={`Data unavailable: ${reason}`}
            className={cn(
              'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium cursor-help',
              'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-400',
              'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
              className
            )}
            tabIndex={0}
          >
            <AlertTriangleIcon />
            <span>Unavailable</span>
          </span>
        </TooltipTrigger>
        <TooltipContent
          side="top"
          className="max-w-xs text-sm"
        >
          <p>{reason}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
});

DataUnavailableBadge.displayName = 'DataUnavailableBadge';

export { DataUnavailableBadge };
