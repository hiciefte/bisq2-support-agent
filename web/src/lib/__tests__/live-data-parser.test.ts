/**
 * Tests for live-data-parser.ts
 *
 * TDD: Tests define the expected backend-frontend contract
 *
 * Backend format (bisq_mcp_service.py):
 * - Total offers: [TOTAL EUR OFFERS: 57]
 * - Offer lines: "BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 USD) via STRIKE [Rep: 1.0]"
 */

import { parseLiveDataContent } from '../live-data-parser';

describe('parseLiveDataContent', () => {
  describe('total offers parsing', () => {
    it('should parse total offers from backend format [TOTAL EUR OFFERS: 57]', () => {
      const content = `There are currently 57 Euro offers available on Bisq 2.

[LIVE OFFERBOOK]
  BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 EUR) via SEPA [Rep: 4.5]
  BUY: 0.00100000 BTC @ 94000.00 (+2.50%) (94.00 EUR) via SEPA [Rep: 5.0]
[TOTAL EUR OFFERS: 57]
[Updated: 2024-01-18T10:30:00Z]`;

      const result = parseLiveDataContent(content);

      expect(result.totalOffers).toBe(57);
    });

    it('should parse total offers from filtered view format', () => {
      const content = `There are 56 EUR offers available.

[LIVE OFFERBOOK]
  BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 EUR) via SEPA [Rep: 4.5]
[TOTAL EUR OFFERS: 56]
[Filtered view: 14 offers to sell BTC to, 42 offers to buy BTC from]
[Updated: 2024-01-18T10:30:00Z]`;

      const result = parseLiveDataContent(content);

      expect(result.totalOffers).toBe(56);
    });

    it('should handle USD offers format [TOTAL USD OFFERS: 23]', () => {
      const content = `[LIVE OFFERBOOK]
  BUY: 0.00100000 BTC @ 95000.00 (+1.50%) (95.00 USD) via Zelle [Rep: 4.5]
[TOTAL USD OFFERS: 23]
[Updated: 2024-01-18T10:30:00Z]`;

      const result = parseLiveDataContent(content);

      expect(result.totalOffers).toBe(23);
    });

    it('should return null totalOffers when no total offers marker present', () => {
      const content = `There are some offers available.

[LIVE OFFERBOOK]
  BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 EUR) via SEPA [Rep: 4.5]
[Updated: 2024-01-18T10:30:00Z]`;

      const result = parseLiveDataContent(content);

      // Parser initializes totalOffers to null when not found
      expect(result.totalOffers).toBeNull();
    });

    it('should parse offers correctly alongside total count', () => {
      const content = `[LIVE OFFERBOOK]
  BUY: 0.00057557 BTC @ 95556.79 (+1.00%) (55.00 EUR) via SEPA [Rep: 4.5]
  SELL: 0.00100000 BTC @ 94000.00 (-2.50%) (94.00 EUR) via SEPA [Rep: 5.0]
[TOTAL EUR OFFERS: 57]
[Updated: 2024-01-18T10:30:00Z]`;

      const result = parseLiveDataContent(content);

      expect(result.totalOffers).toBe(57);
      expect(result.offers).toHaveLength(2);
      expect(result.offers?.[0].direction).toBe('buy');
      expect(result.offers?.[1].direction).toBe('sell');
    });
  });

  describe('clean content', () => {
    it('should remove total offers marker from clean content', () => {
      const content = `There are 57 EUR offers.
[TOTAL EUR OFFERS: 57]
[Updated: 2024-01-18T10:30:00Z]`;

      const result = parseLiveDataContent(content);

      expect(result.cleanContent).not.toContain('[TOTAL EUR OFFERS: 57]');
      expect(result.cleanContent).toContain('There are 57 EUR offers');
    });
  });
});
