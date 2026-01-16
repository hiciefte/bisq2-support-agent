/**
 * Parser for extracting structured live data from message content
 *
 * Detects markers like [LIVE MARKET PRICES] and [LIVE OFFERBOOK]
 * and parses the following lines into structured data for rich rendering.
 */

import type { MarketPrice, OfferSummary, LiveDataMeta } from '@/types/live-data';

/**
 * Parsed live data sections from message content
 */
export interface ParsedLiveData {
  /** Market prices extracted from [LIVE MARKET PRICES] section */
  prices: MarketPrice[];
  /** Offers extracted from [LIVE OFFERBOOK] section */
  offers: OfferSummary[];
  /** Text content with live data sections removed */
  cleanContent: string;
  /** Whether any live data was found */
  hasLiveData: boolean;
}

/**
 * Regex patterns for detecting live data sections
 */
const PRICE_SECTION_REGEX = /\[LIVE MARKET PRICES\]\n([\s\S]*?)(?=\n\n|\n\[|$)/;
const OFFERBOOK_SECTION_REGEX = /\[LIVE OFFERBOOK\]\n([\s\S]*?)(?=\n\n|\n\[|$)/;
const PRICE_LINE_REGEX = /BTC\/(\w+):\s*([0-9,.]+)/;
// Format: "BUY: 0.00057557 BTC @ 95556.79 (55.00 USD) via STRIKE [Rep: 0]"
const OFFER_LINE_REGEX = /^\s*(BUY|SELL):\s*([\d.]+(?:\s*-\s*[\d.]+)?)\s*BTC\s*@\s*([\d,.]+)\s*\(([^)]+)\)\s*via\s+([^\[]+?)(?:\s*\[Rep:\s*(\d+)\])?$/i;

/**
 * Create default metadata for parsed live data
 */
function createMeta(): LiveDataMeta {
  return {
    type: 'live',
    timestamp: new Date().toISOString(),
    source: 'mcp-server',
  };
}

/**
 * Parse a price line like "BTC/USD: 95,279.32"
 */
function parsePriceLine(line: string): MarketPrice | null {
  const match = line.match(PRICE_LINE_REGEX);
  if (!match) return null;

  const currency = match[1];
  const valueStr = match[2].replace(/,/g, '');
  const value = parseFloat(valueStr);

  if (isNaN(value)) return null;

  return {
    currency,
    value,
    meta: createMeta(),
  };
}

/**
 * Parse an offer line like "BUY: 0.00057557 BTC @ 95556.79 (55.00 USD) via STRIKE [Rep: 0]"
 */
function parseOfferLine(line: string): OfferSummary | null {
  const match = line.match(OFFER_LINE_REGEX);
  if (!match) return null;

  const direction = match[1].toLowerCase() as 'buy' | 'sell';
  const btcAmount = match[2].trim(); // e.g., "0.00057557" or "0.0005 - 0.0050"
  const pricePerBtc = match[3].replace(/,/g, ''); // e.g., "95556.79"
  const fiatAmount = match[4].trim(); // e.g., "55.00 USD"
  const paymentMethod = match[5].trim(); // e.g., "STRIKE"
  const reputationScore = match[6] ? parseInt(match[6], 10) : 0;

  // Extract currency from fiat amount (e.g., "55.00 USD" -> "USD")
  const currencyMatch = fiatAmount.match(/([A-Z]{3})$/);
  const currency = currencyMatch ? currencyMatch[1] : 'USD';

  return {
    direction,
    formattedPrice: `${pricePerBtc} ${currency}`,
    formattedQuoteAmount: `${btcAmount} BTC`,
    paymentMethods: [paymentMethod],
    reputationScore,
  };
}

/**
 * Parse message content to extract live data sections
 *
 * @param content - Raw message content from the LLM
 * @returns Parsed live data with prices, offers, and clean content
 */
export function parseLiveDataContent(content: string): ParsedLiveData {
  const prices: MarketPrice[] = [];
  const offers: OfferSummary[] = [];
  let cleanContent = content;

  // Parse [LIVE MARKET PRICES] section
  const priceMatch = content.match(PRICE_SECTION_REGEX);
  if (priceMatch) {
    const priceLines = priceMatch[1].split('\n').filter(line => line.trim());
    for (const line of priceLines) {
      const price = parsePriceLine(line);
      if (price) {
        prices.push(price);
      }
    }
    // Remove the section from clean content
    cleanContent = cleanContent.replace(PRICE_SECTION_REGEX, '').trim();
  }

  // Parse [LIVE OFFERBOOK] section
  const offerMatch = content.match(OFFERBOOK_SECTION_REGEX);
  if (offerMatch) {
    const offerLines = offerMatch[1].split('\n').filter(line => line.trim());
    for (const line of offerLines) {
      const offer = parseOfferLine(line);
      if (offer) {
        offers.push(offer);
      }
    }
    // Remove the section from clean content
    cleanContent = cleanContent.replace(OFFERBOOK_SECTION_REGEX, '').trim();
  }

  // Clean up any remaining markers
  cleanContent = cleanContent
    .replace(/\[LIVE MARKET PRICES\]/g, '')
    .replace(/\[LIVE OFFERBOOK\]/g, '')
    .replace(/\[LIVE BISQ 2 DATA\]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return {
    prices,
    offers,
    cleanContent,
    hasLiveData: prices.length > 0 || offers.length > 0,
  };
}

/**
 * Check if content contains live data markers without full parsing
 * (more efficient for quick checks)
 */
export function hasLiveDataMarkers(content: string): boolean {
  return (
    content.includes('[LIVE MARKET PRICES]') ||
    content.includes('[LIVE OFFERBOOK]') ||
    content.includes('[LIVE BISQ 2 DATA]')
  );
}
