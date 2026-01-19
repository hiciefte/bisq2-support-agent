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
import { PriceDisplay, OfferTable, ReputationCard } from '@/components/live-data';
import { parseLiveDataContent } from '@/lib/live-data-parser';
import { getDataFreshness } from '@/lib/live-data-utils';
import { MarkdownContent } from './markdown-content';
import type { LiveDataMeta, ReputationData } from '@/types/live-data';
import type { McpToolUsage } from '../types/chat.types';

/** ToolResult with required result field (filtered from McpToolUsage) */
type ToolResult = Required<Pick<McpToolUsage, 'tool' | 'result'>>;

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
  const ts = timestamp || new Date().toISOString();
  return {
    type: getDataFreshness(ts),
    timestamp: ts,
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
    let reputation: ReputationData | null = null;
    let totalOffers: number | null = null;

    for (const { tool, result } of toolResults) {
      // Parse the tool result text for structured data
      const toolParsed = parseLiveDataContent(result);

      if (tool === 'get_market_prices' && toolParsed.prices.length > 0) {
        allPrices.push(...toolParsed.prices);
      }

      if (tool === 'get_offerbook' && toolParsed.offers.length > 0) {
        allOffers.push(...toolParsed.offers);
        // Capture total offers count from the parsed result
        if (toolParsed.totalOffers !== null) {
          totalOffers = toolParsed.totalOffers;
        }
      }

      if (tool === 'get_reputation' && toolParsed.reputation) {
        reputation = toolParsed.reputation;
      }
    }

    return {
      prices: allPrices,
      offers: allOffers,
      reputation,
      totalOffers,
      hasLiveData: allPrices.length > 0 || allOffers.length > 0 || reputation !== null,
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
          currency={parsed.offers[0]?.currency || 'EUR'}
          meta={meta}
          maxOffers={5}
          totalOffers={parsed.totalOffers}
        />
      )}

      {/* Render reputation card if reputation data was found */}
      {parsed.reputation && (
        <ReputationCard reputation={parsed.reputation} />
      )}

      {/* Always render LLM text for helpful context (e.g., troubleshooting why offers don't appear) */}
      {content && (
        <MarkdownContent
          content={content}
          className={parsed.hasLiveData ? 'mt-2 text-sm text-muted-foreground' : ''}
        />
      )}
    </div>
  );
});
