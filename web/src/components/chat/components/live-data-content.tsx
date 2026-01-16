'use client';

/**
 * Component to render message content with rich live data components
 *
 * Parses tool results from MCP tools and renders:
 * - PriceDisplay for get_market_prices results
 * - OfferTable for get_offerbook results
 * - Plain text for the LLM response
 */

import { memo, useMemo } from 'react';
import { PriceDisplay, OfferTable } from '@/components/live-data';
import { parseLiveDataContent } from '@/lib/live-data-parser';
import type { LiveDataMeta } from '@/types/live-data';

interface ToolResult {
  tool: string;
  result: string;
}

interface LiveDataContentProps {
  /** LLM response text */
  content: string;
  /** Tool results from MCP tools with structured data */
  toolResults: ToolResult[];
  /** Timestamp for the live data badge */
  timestamp?: string;
}

/**
 * Create metadata object for live data components
 */
function createMeta(timestamp?: string): LiveDataMeta {
  return {
    type: 'live',
    timestamp: timestamp || new Date().toISOString(),
    source: 'bisq2-api',
  };
}

/**
 * Renders message content with rich live data components
 * Uses tool results from MCP to display prices and offers
 */
export const LiveDataContent = memo(function LiveDataContent({
  content,
  toolResults,
  timestamp,
}: LiveDataContentProps) {
  // Parse all tool results to extract structured data
  const parsed = useMemo(() => {
    const allPrices: ReturnType<typeof parseLiveDataContent>['prices'] = [];
    const allOffers: ReturnType<typeof parseLiveDataContent>['offers'] = [];

    for (const { tool, result } of toolResults) {
      // Parse the tool result text for structured data
      const toolParsed = parseLiveDataContent(result);

      if (tool === 'get_market_prices' && toolParsed.prices.length > 0) {
        allPrices.push(...toolParsed.prices);
      }

      if (tool === 'get_offerbook' && toolParsed.offers.length > 0) {
        allOffers.push(...toolParsed.offers);
      }
    }

    return {
      prices: allPrices,
      offers: allOffers,
      hasLiveData: allPrices.length > 0 || allOffers.length > 0,
    };
  }, [toolResults]);

  const meta = createMeta(timestamp);

  return (
    <div className="space-y-4">
      {/* Render price display if prices were found in tool results */}
      {parsed.prices.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Live Market Prices
          </div>
          <div className="flex flex-wrap gap-4">
            {parsed.prices.map((price, idx) => (
              <PriceDisplay
                key={`price-${price.currency}-${idx}`}
                price={price.value}
                currency={price.currency}
                meta={meta}
              />
            ))}
          </div>
        </div>
      )}

      {/* Render offer table if offers were found in tool results */}
      {parsed.offers.length > 0 && (
        <OfferTable
          offers={parsed.offers}
          currency={parsed.offers[0]?.formattedPrice.match(/[A-Z]{3}/)?.[0] || 'EUR'}
          meta={meta}
          maxOffers={5}
        />
      )}

      {/* Always render the LLM response text */}
      <div className={parsed.hasLiveData ? 'mt-2 pt-2 border-t border-border/50' : ''}>
        <span>{content}</span>
      </div>
    </div>
  );
});
