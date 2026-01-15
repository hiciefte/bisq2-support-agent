/**
 * Type definitions for live Bisq 2 data components
 */

/**
 * Metadata for live data indicating freshness and source
 */
export interface LiveDataMeta {
  /** Type of data freshness: 'live' (real-time), 'cached' (from cache), 'stale' (outdated) */
  type: 'live' | 'cached' | 'stale';
  /** ISO timestamp of when the data was fetched */
  timestamp: string;
  /** Source of the data (e.g., 'bisq2-api', 'mcp-server') */
  source: string;
}

/**
 * Market price information for a currency pair
 */
export interface MarketPrice {
  /** Currency code (e.g., 'USD', 'EUR', 'BTC') */
  currency: string;
  /** Price value in the specified currency */
  value: number;
  /** Data freshness metadata */
  meta: LiveDataMeta;
}

/**
 * Summary of an offer from the Bisq 2 offerbook
 */
export interface OfferSummary {
  /** Offer direction: 'buy' or 'sell' from the maker's perspective */
  direction: 'buy' | 'sell';
  /** Formatted price string (e.g., '$98,500.00') */
  formattedPrice: string;
  /** Formatted quote amount (e.g., '0.05 BTC' or '$500') */
  formattedQuoteAmount: string;
  /** Available payment methods for this offer */
  paymentMethods: string[];
  /** Maker's reputation score (0.0 to 5.0) */
  reputationScore: number;
}

/**
 * Response structure for live data API calls
 */
export interface LiveDataResponse {
  /** Market prices by currency code */
  prices?: Record<string, MarketPrice>;
  /** List of offers from the offerbook */
  offers?: OfferSummary[];
  /** Overall metadata for the response */
  meta: LiveDataMeta;
}

/**
 * Props for the LiveDataBadge component
 */
export interface LiveDataBadgeProps {
  /** Type of data freshness indicator */
  type: 'live' | 'cached' | 'stale';
  /** Optional timestamp to display */
  timestamp?: string;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Props for the PriceDisplay component
 */
export interface PriceDisplayProps {
  /** Price value */
  price: number;
  /** Currency code */
  currency: string;
  /** Data freshness metadata */
  meta: LiveDataMeta;
  /** Optional change percentage */
  changePercent?: number;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Props for the OfferTable component
 */
export interface OfferTableProps {
  /** List of offers to display */
  offers: OfferSummary[];
  /** Currency for display context */
  currency: string;
  /** Maximum number of offers to display (default: 5) */
  maxOffers?: number;
  /** Data freshness metadata */
  meta?: LiveDataMeta;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Props for the OfferCard component (mobile view)
 */
export interface OfferCardProps {
  /** Offer data to display */
  offer: OfferSummary;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Props for the ReputationBadge component
 */
export interface ReputationBadgeProps {
  /** Reputation score (0.0 to 5.0) */
  score: number;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Props for the DataUnavailableBadge component
 */
export interface DataUnavailableBadgeProps {
  /** Reason for data unavailability */
  reason: string;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Reputation level information returned by utility functions
 */
export interface ReputationLevel {
  /** Human-readable label (e.g., 'Excellent', 'Good', 'Fair', 'New') */
  label: string;
  /** Tailwind CSS color class for this level */
  colorClass: string;
}

/**
 * Timestamp formatting result
 */
export interface FormattedTimestamp {
  /** Human-readable timestamp text (e.g., 'Just now', '5 min ago') */
  text: string;
  /** Tailwind CSS color class based on age */
  color: string;
}
