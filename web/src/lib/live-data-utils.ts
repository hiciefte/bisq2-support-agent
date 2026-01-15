import type { FormattedTimestamp, ReputationLevel } from '@/types/live-data';

/**
 * Format a timestamp relative to now with color coding based on age
 * @param date - The date to format
 * @returns Object with formatted text and color class
 */
export function formatTimestamp(date: Date): FormattedTimestamp {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);

  // Determine age category and text
  if (diffSeconds < 30) {
    return {
      text: 'Just now',
      color: 'text-emerald-600 dark:text-emerald-400',
    };
  } else if (diffSeconds < 60) {
    return {
      text: `${diffSeconds}s ago`,
      color: 'text-emerald-600 dark:text-emerald-400',
    };
  } else if (diffMinutes < 5) {
    return {
      text: `${diffMinutes} min ago`,
      color: 'text-emerald-600 dark:text-emerald-400',
    };
  } else if (diffMinutes < 30) {
    return {
      text: `${diffMinutes} min ago`,
      color: 'text-amber-600 dark:text-amber-400',
    };
  } else if (diffHours < 1) {
    return {
      text: `${diffMinutes} min ago`,
      color: 'text-amber-600 dark:text-amber-400',
    };
  } else if (diffHours < 24) {
    return {
      text: `${diffHours}h ago`,
      color: 'text-gray-600 dark:text-gray-400',
    };
  } else {
    return {
      text: date.toLocaleDateString(),
      color: 'text-gray-600 dark:text-gray-400',
    };
  }
}

/**
 * Currency symbols for common currencies
 */
const CURRENCY_SYMBOLS: Record<string, string> = {
  USD: '$',
  EUR: '€',
  GBP: '£',
  JPY: '¥',
  CHF: 'CHF',
  CAD: 'C$',
  AUD: 'A$',
  BTC: '₿',
  XMR: 'XMR',
};

/**
 * Format a number as currency with proper symbol and formatting
 * @param value - The numeric value to format
 * @param currency - The currency code (e.g., 'USD', 'EUR', 'BTC')
 * @returns Formatted currency string
 */
export function formatCurrency(value: number, currency: string): string {
  const symbol = CURRENCY_SYMBOLS[currency.toUpperCase()] || currency;

  // Bitcoin and crypto formatting
  if (currency.toUpperCase() === 'BTC') {
    // Format BTC with up to 8 decimal places, removing trailing zeros
    const formatted = value.toFixed(8).replace(/\.?0+$/, '');
    return `${symbol}${formatted}`;
  }

  if (currency.toUpperCase() === 'XMR') {
    // Format XMR with up to 12 decimal places
    const formatted = value.toFixed(12).replace(/\.?0+$/, '');
    return `${formatted} ${symbol}`;
  }

  // Fiat currencies - use locale formatting
  try {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: currency.toUpperCase(),
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    // Fallback for unknown currencies
    return `${symbol}${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
}

/**
 * Get reputation level information based on score
 * @param score - Reputation score (0.0 to 5.0)
 * @returns Object with label and color class
 */
export function getReputationLevel(score: number): ReputationLevel {
  if (score >= 4.5) {
    return {
      label: 'Excellent',
      colorClass: 'text-emerald-600 dark:text-emerald-400 bg-emerald-100 dark:bg-emerald-900/30',
    };
  } else if (score >= 3.5) {
    return {
      label: 'Good',
      colorClass: 'text-blue-600 dark:text-blue-400 bg-blue-100 dark:bg-blue-900/30',
    };
  } else if (score >= 2.5) {
    return {
      label: 'Fair',
      colorClass: 'text-amber-600 dark:text-amber-400 bg-amber-100 dark:bg-amber-900/30',
    };
  } else {
    return {
      label: 'New',
      colorClass: 'text-gray-600 dark:text-gray-400 bg-gray-100 dark:bg-gray-800',
    };
  }
}

/**
 * Generate star rating display from score
 * @param score - Score from 0 to 5
 * @returns String of filled and empty stars (e.g., '★★★★☆')
 */
export function getStarRating(score: number): string {
  const filledStars = Math.round(score);
  const emptyStars = 5 - filledStars;
  return '★'.repeat(filledStars) + '☆'.repeat(emptyStars);
}

/**
 * Parse ISO timestamp string to Date object
 * @param timestamp - ISO format timestamp string
 * @returns Date object or null if invalid
 */
export function parseTimestamp(timestamp: string): Date | null {
  try {
    const date = new Date(timestamp);
    if (isNaN(date.getTime())) {
      return null;
    }
    return date;
  } catch {
    return null;
  }
}

/**
 * Determine data freshness type based on timestamp age
 * @param timestamp - ISO format timestamp string
 * @returns Data freshness type
 */
export function getDataFreshness(timestamp: string): 'live' | 'cached' | 'stale' {
  const date = parseTimestamp(timestamp);
  if (!date) return 'stale';

  const now = new Date();
  const diffMinutes = (now.getTime() - date.getTime()) / (1000 * 60);

  if (diffMinutes < 1) return 'live';
  if (diffMinutes < 30) return 'cached';
  return 'stale';
}
