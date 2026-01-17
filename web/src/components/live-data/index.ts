/**
 * Live Data Components for Bisq 2 MCP Integration
 *
 * This module exports all components for displaying live Bisq 2 data
 * in the chat interface, including prices, offers, and reputation scores.
 */

// Core status badge
export { LiveDataBadge } from './LiveDataBadge';

// Price display
export { PriceDisplay } from './PriceDisplay';

// Reputation badges and card
export { ReputationBadge, ReputationBadgeCompact } from './ReputationBadge';
export { ReputationCard } from './ReputationCard';

// Offer components
export { OfferCard } from './OfferCard';
export { OfferTable } from './OfferTable';

// Loading skeletons
export {
  SkeletonBase,
  PriceSkeleton,
  TableSkeleton,
  CardSkeleton,
} from './DataSkeleton';

// Error/warning states
export { DataUnavailableBadge } from './DataUnavailableBadge';

// Re-export types for convenience
export type {
  LiveDataMeta,
  MarketPrice,
  OfferSummary,
  ReputationData,
  LiveDataResponse,
  LiveDataBadgeProps,
  PriceDisplayProps,
  OfferTableProps,
  OfferCardProps,
  ReputationBadgeProps,
  ReputationCardProps,
  DataUnavailableBadgeProps,
  ReputationLevel,
  FormattedTimestamp,
} from '@/types/live-data';

// Re-export utility functions
export {
  formatTimestamp,
  formatCurrency,
  getReputationLevel,
  getStarRating,
  parseTimestamp,
  getDataFreshness,
} from '@/lib/live-data-utils';
