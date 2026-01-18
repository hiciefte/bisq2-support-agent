/**
 * Parser for extracting structured live data from message content
 *
 * Detects markers like [LIVE MARKET PRICES] and [LIVE OFFERBOOK]
 * and parses the following lines into structured data for rich rendering.
 */

import type { MarketPrice, OfferSummary, ReputationData, LiveDataMeta } from '@/types/live-data';

/**
 * Parsed live data sections from message content
 */
export interface ParsedLiveData {
  /** Market prices extracted from [LIVE MARKET PRICES] section */
  prices: MarketPrice[];
  /** Offers extracted from [LIVE OFFERBOOK] section */
  offers: OfferSummary[];
  /** Total number of offers available (from [Total offers: X] line) */
  totalOffers: number | null;
  /** Reputation data extracted from [REPUTATION DATA] section */
  reputation: ReputationData | null;
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
const REPUTATION_SECTION_REGEX = /\[REPUTATION DATA\]\n([\s\S]*?)(?=\n\n|\n\[|$)/;
const PRICE_LINE_REGEX = /BTC\/(\w+):\s*([0-9,.]+)/;
// Format: "BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 USD) via STRIKE [Rep: 1.0] Maker:nickname(profileId)"
// The price percentage (e.g., "+1.00%", "-2.50%", "0.00%") is optional for backwards compatibility
// The maker info is optional: " Maker:nickname(profileId)" where nickname or profileId may be empty
const OFFER_LINE_REGEX = /^\s*(BUY|SELL):\s*([\d.]+(?:\s*-\s*[\d.]+)?)\s*BTC\s*@\s*([\d,.]+)\s*(?:\(([+-]?[\d.]+%)\)\s*)?\(([^)]+)\)\s*via\s+([^\[]+?)(?:\s*\[Rep:\s*([\d.]+)\])?(?:\s*Maker:([^(]*)\(([^)]+)\))?$/i;
// Reputation data lines
const REPUTATION_PROFILE_REGEX = /Profile ID:\s*(.+)/;
const REPUTATION_NICKNAME_REGEX = /Nickname:\s*(.+)/;
const REPUTATION_SCORE_REGEX = /Total Score:\s*([\d,]+)/;
const REPUTATION_STAR_REGEX = /Star Rating:\s*([\d.]+)\/5\.0/;
const REPUTATION_RANKING_REGEX = /Ranking:\s*#?(\S+)/;
const REPUTATION_AGE_REGEX = /Profile Age:\s*(\d+)\s*days/;
// Total offers count line: [TOTAL EUR OFFERS: 57]
const TOTAL_OFFERS_REGEX = /\[TOTAL\s+\w+\s+OFFERS:\s*(\d+)\]/i;
// Filtered offers line: [Showing 48 BUY offers out of 60 total]
const FILTERED_OFFERS_REGEX = /\[Showing\s+(\d+)\s+\w+\s+offers\s+out\s+of\s+(\d+)\s+total\]/;

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
 * Parse an offer line like "BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 USD) via STRIKE [Rep: 0] Maker:nickname(profileId)"
 */
function parseOfferLine(line: string): OfferSummary | null {
  const match = line.match(OFFER_LINE_REGEX);
  if (!match) return null;

  const direction = match[1].toLowerCase() as 'buy' | 'sell';
  const btcAmount = match[2].trim(); // e.g., "0.00057557" or "0.0005 - 0.0050"
  const pricePerBtc = match[3].replace(/,/g, ''); // e.g., "95556.79"
  const pricePercentage = match[4] || undefined; // e.g., "+1.00%", "-2.50%", "0.00%"
  const fiatAmount = match[5].trim(); // e.g., "55.00 USD"
  const paymentMethod = match[6].trim(); // e.g., "STRIKE"
  const reputationScore = match[7] ? parseFloat(match[7]) : 0;
  const makerNickName = match[8]?.trim() || undefined; // e.g., "nickname"
  const makerProfileId = match[9]?.trim() || undefined; // e.g., "profileId" (truncated)

  // Extract currency from fiat amount (e.g., "55.00 USD" -> "USD")
  const currencyMatch = fiatAmount.match(/([A-Z]{3})$/);
  const currency = currencyMatch ? currencyMatch[1] : 'USD';

  return {
    direction,
    currency,
    formattedPrice: `${pricePerBtc} ${currency}`,
    formattedQuoteAmount: `${btcAmount} BTC`,
    paymentMethods: [paymentMethod],
    reputationScore,
    pricePercentage,
    makerProfileId,
    makerNickName,
  };
}

/**
 * Parse reputation section content
 */
function parseReputationSection(content: string): ReputationData | null {
  const profileMatch = content.match(REPUTATION_PROFILE_REGEX);
  const nicknameMatch = content.match(REPUTATION_NICKNAME_REGEX);
  const scoreMatch = content.match(REPUTATION_SCORE_REGEX);
  const starMatch = content.match(REPUTATION_STAR_REGEX);
  const rankingMatch = content.match(REPUTATION_RANKING_REGEX);
  const ageMatch = content.match(REPUTATION_AGE_REGEX);

  // Need at least profile ID and score to consider it valid
  if (!profileMatch || !scoreMatch) return null;

  const totalScore = parseInt(scoreMatch[1].replace(/,/g, ''), 10);
  if (isNaN(totalScore)) return null;

  return {
    profileId: profileMatch[1].trim(),
    nickName: nicknameMatch ? nicknameMatch[1].trim() : undefined,
    totalScore,
    starRating: starMatch ? parseFloat(starMatch[1]) : 0,
    ranking: rankingMatch ? rankingMatch[1] : 'N/A',
    profileAgeDays: ageMatch ? parseInt(ageMatch[1], 10) : undefined,
    meta: createMeta(),
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
  let totalOffers: number | null = null;
  let reputation: ReputationData | null = null;
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

  // Parse total offers count from content
  // Check for filtered format first: [Showing X ... offers out of Y total]
  const filteredOffersMatch = content.match(FILTERED_OFFERS_REGEX);
  if (filteredOffersMatch) {
    // Use the total (Y) not the filtered count (X) for the widget header
    totalOffers = parseInt(filteredOffersMatch[2], 10);
    // Remove the filtered offers line from clean content
    cleanContent = cleanContent.replace(FILTERED_OFFERS_REGEX, '').trim();
  } else {
    // Backend format: [TOTAL EUR OFFERS: X]
    const totalOffersMatch = content.match(TOTAL_OFFERS_REGEX);
    if (totalOffersMatch) {
      totalOffers = parseInt(totalOffersMatch[1], 10);
      // Remove the total offers line from clean content
      cleanContent = cleanContent.replace(TOTAL_OFFERS_REGEX, '').trim();
    }
  }

  // Parse [REPUTATION DATA] section
  const reputationMatch = content.match(REPUTATION_SECTION_REGEX);
  if (reputationMatch) {
    reputation = parseReputationSection(reputationMatch[1]);
    // Remove the section from clean content
    cleanContent = cleanContent.replace(REPUTATION_SECTION_REGEX, '').trim();
  }

  // Clean up any remaining markers and timestamps
  cleanContent = cleanContent
    .replace(/\[LIVE MARKET PRICES\]/g, '')
    .replace(/\[LIVE OFFERBOOK\]/g, '')
    .replace(/\[LIVE BISQ 2 DATA\]/g, '')
    .replace(/\[REPUTATION DATA\]/g, '')
    .replace(/\[Updated:.*?\]/g, '')
    .replace(/\n{3,}/g, '\n\n')
    .trim();

  return {
    prices,
    offers,
    totalOffers,
    reputation,
    cleanContent,
    hasLiveData: prices.length > 0 || offers.length > 0 || reputation !== null,
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
    content.includes('[LIVE BISQ 2 DATA]') ||
    content.includes('[REPUTATION DATA]')
  );
}
