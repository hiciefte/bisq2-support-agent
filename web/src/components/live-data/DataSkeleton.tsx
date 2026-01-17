import * as React from 'react';
import { cn } from '@/lib/utils';

interface SkeletonBaseProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Additional CSS classes */
  className?: string;
}

/**
 * Base skeleton component with pulse animation
 * Respects prefers-reduced-motion
 */
const SkeletonBase = React.forwardRef<HTMLDivElement, SkeletonBaseProps>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'animate-pulse rounded-md bg-primary/10 motion-reduce:animate-none',
        className
      )}
      aria-hidden="true"
      {...props}
    />
  )
);
SkeletonBase.displayName = 'SkeletonBase';

interface PriceSkeletonProps {
  /** Additional CSS classes */
  className?: string;
}

/**
 * Inline loading placeholder for price displays
 *
 * Features:
 * - Matches typical price display width
 * - Inline-flex for text flow
 * - Respects reduced motion preference
 */
const PriceSkeleton = React.forwardRef<HTMLDivElement, PriceSkeletonProps>(
  ({ className }, ref) => (
    <div
      ref={ref}
      role="status"
      aria-label="Loading price"
      className={cn('inline-flex items-center gap-2', className)}
    >
      {/* Price value skeleton */}
      <SkeletonBase className="h-6 w-24" />
      {/* Badge skeleton */}
      <SkeletonBase className="h-5 w-14 rounded-full" />
      <span className="sr-only">Loading price...</span>
    </div>
  )
);
PriceSkeleton.displayName = 'PriceSkeleton';

interface TableSkeletonProps {
  /** Number of rows to display (default: 5) */
  rows?: number;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Multi-row loading placeholder for offer tables
 *
 * Features:
 * - Configurable number of rows
 * - Matches table column structure
 * - Respects reduced motion preference
 * - Accessible loading state
 */
const TableSkeleton = React.forwardRef<HTMLDivElement, TableSkeletonProps>(
  ({ rows = 5, className }, ref) => (
    <div
      ref={ref}
      role="status"
      aria-label="Loading offers"
      className={cn('space-y-3', className)}
    >
      {/* Header skeleton */}
      <div className="flex items-center gap-4 px-2">
        <SkeletonBase className="h-4 w-12" />
        <SkeletonBase className="h-4 w-20" />
        <SkeletonBase className="h-4 w-16" />
        <SkeletonBase className="h-4 w-24" />
        <SkeletonBase className="h-4 w-12" />
      </div>

      {/* Divider */}
      <SkeletonBase className="h-px w-full" />

      {/* Row skeletons */}
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center gap-4 px-2 py-1"
        >
          {/* Type indicator */}
          <SkeletonBase className="h-4 w-12 rounded" />
          {/* Price */}
          <SkeletonBase className="h-4 w-20" />
          {/* Amount */}
          <SkeletonBase className="h-4 w-16" />
          {/* Payment methods */}
          <div className="flex gap-1">
            <SkeletonBase className="h-5 w-16 rounded-full" />
            <SkeletonBase className="h-5 w-12 rounded-full" />
          </div>
          {/* Reputation */}
          <SkeletonBase className="h-4 w-12" />
        </div>
      ))}

      <span className="sr-only">Loading offers...</span>
    </div>
  )
);
TableSkeleton.displayName = 'TableSkeleton';

interface CardSkeletonProps {
  /** Additional CSS classes */
  className?: string;
}

/**
 * Loading placeholder for mobile offer cards
 */
const CardSkeleton = React.forwardRef<HTMLDivElement, CardSkeletonProps>(
  ({ className }, ref) => (
    <div
      ref={ref}
      role="status"
      aria-label="Loading offer"
      className={cn(
        'rounded-lg border border-border bg-card p-3 space-y-2',
        className
      )}
    >
      {/* Header row */}
      <div className="flex items-center justify-between">
        <SkeletonBase className="h-5 w-16 rounded" />
        <SkeletonBase className="h-4 w-20" />
      </div>

      {/* Details */}
      <div className="space-y-1.5">
        <SkeletonBase className="h-4 w-24" />
        <div className="flex gap-1">
          <SkeletonBase className="h-5 w-14 rounded-full" />
          <SkeletonBase className="h-5 w-12 rounded-full" />
        </div>
      </div>

      {/* Footer */}
      <SkeletonBase className="h-4 w-16" />

      <span className="sr-only">Loading offer...</span>
    </div>
  )
);
CardSkeleton.displayName = 'CardSkeleton';

export { SkeletonBase, PriceSkeleton, TableSkeleton, CardSkeleton };
