# LLM Wiki Bootstrap Curation Report

Generated from the local production mirror on 2026-06-18. This report intentionally avoids raw support-chat content; it records page-level curation decisions and candidate-group handling.

## Scope

- Pending production candidates mirrored locally: 700
- Reviewable local queue items after curation/rematch: 302
- LLM Wiki pages after curation: 20
- All pages are `proposed`; none are indexable until human review.
- Source references are restricted to resolvable `wiki:`, `faq:`, or `llm_wiki:` refs.

## Curated Pages

- `bisq1-deposit-confirmed-stuck` (45 matched review items): Confirmed deposit vs missing/pending deposit; SPV and mediation boundaries.
- `bisq1-data-directory-wallet-recovery` (32 matched review items): Data-directory moves, seed restore limits, old wallet migration, Bisq 1/Bisq 2 boundary.
- `bisq1-dispute-mediation-arbitration` (35 matched review items): Mediation/arbitration stages, delayed-payout timing, evidence and unsafe file deletion boundaries.
- `bisq1-wallet-spv-balance` (27 matched review items): Wallet balance, UTXO/SPV checks, BSQ, emergency-wallet and external XMR account boundaries.
- `bisq2-easy-mediation-and-risk` (24 matched review items): Bisq Easy non-escrow risk, cancellation after/no fiat, address-sharing, ACH and mediation.
- `bisq1-failed-trade-fees` (19 matched review items): Missing/invalid deposit, fee-loss reimbursement, DPT/DAO boundary.
- `bisq2-startup-network-notifications` (16 matched review items): Bisq 2 startup/network/notification/mediation-button troubleshooting.
- `bisq1-dao-dpt-state-error` (12 matched review items): DAO-state, DPT mismatch, snapshot-height and seed-node workaround caution.
- `bisq1-bsq-fee-payment` (11 matched review items): BSQ as colored bitcoin, swaps, fee payment, spendability/dust caution.
- `bisq1-trade-funding-security-deposits` (11 matched review items): Security deposits, spendable balance, cancellation, account-limit boundaries.
- `bisq2-reputation-basics` (9 matched review items): Bisq Easy reputation methods, profile binding, missing reputation checks.
- `bisq1-network-tor-price-feed` (8 matched review items): Tor/peer/price-feed/custom-node troubleshooting vs wallet-state boundary.
- `bisq1-offer-fee-tx-not-found` (6 matched review items): Offer deactivation from missing maker fee vs account-limit/visibility issues.
- `bisq1-fiat-stablecoin-routing` (5 matched review items): Fiat-to-BTC-to-altcoin/stablecoin routing and non-custodial boundary.
- `bisq1-sepa-payment-name-proof` (5 matched review items): SEPA details, name mismatch, fallback to normal SEPA and proof boundaries.
- `bisq1-payout-output-inconsistency` (4 matched review items): Payout/output/address-reuse checks.
- `bisq2-btc-only-altcoin-path` (4 matched review items): Bisq Easy BTC scope and Bisq 1 altcoin path.
- `bisq2-profile-data-recovery` (4 matched review items): Bisq 2 profile/data-directory recovery and device transfer.
- `bisq2-overview-trade-totals`: Overview/history/stale notification and reporting limits.
- `bisq2-wallet-lightning-onchain`: Bisq 2 external wallet, Lightning and on-chain receiving.

## Intentionally Not Promoted As New Pages

- `bisq1-altcoin-instant-stuck`: Deleted before activation because Altcoin Instant is not a separate durable stuck-trade support flow; the usable guidance is covered by `bisq1-deposit-confirmed-stuck`, `bisq1-failed-trade-fees`, and `bisq1-dispute-mediation-arbitration`.

- `multisig-v1-trading` (10 candidates: 372, 441, 448, 511, 512, 523, 613, 628, 808, 861): Mixed low-quality/wrong-target candidates: named support-agent status, temporary maintenance, huge trade sizing, Zelle DBA judgment, forum-only transaction-anatomy request. Durable pieces were already folded into dispute/trade-funding/SEPA/BTC-scope pages.
- `multisig-v1-installation` (4 candidates: 446, 541, 791, 875): Version/Start9/MSI incident candidates are time-sensitive or platform-specific; durable network/update guidance is covered in network/DAO pages.
- `multisig-v1-account` (2 candidates: 656, 930): DAO reimbursement and account-signing edge cases need separate policy verification before promotion.
- `multisig-v1-payment-methods` (2 candidates: 718, 771): One-off Zelle signing and CBM/USPMO details; keep in FAQ/payment-method sources unless recurrence justifies a page.
- `multisig-v1-troubleshooting` (2 candidates: 419, 431): Generic CPU/memory/SPV operational notes; durable SPV pieces folded into wallet/network pages, exact memory tuning not promoted.
- `bisq-easy-trading` (2 candidates: 395, 956): Developer API state-field guess and mediation button behavior; durable mediation-button guidance folded into Bisq 2 troubleshooting.
- `bisq-easy-payment-methods` (1 candidates: 364): Single gift-card path candidate; not enough durable support value for an LLM Wiki page.
- `multisig-v1-general` (1 candidates: 698): Single SPV acronym candidate; not a support playbook.
- `multisig-v1-security` (1 candidates: 284): Wallet address reuse/privacy covered by wallet docs; arbitrator privacy candidate is too specific without durable source.

## Quality Gates Added

- Added a regression test that rejects non-durable LLM Wiki seed sources such as `support:` refs.
- The same test verifies each `wiki:` source exists in the local wiki dump and each `faq:` source exists in the local FAQ database by ID or slug.
- Existing seed-page tests still assert that bootstrap pages require human review and are not loaded into RAG while `proposed`.

## Human Review Guidance

Review the curated markdown pages directly, not the raw candidates. Promote a page only after the support admin agrees that the canonical answer, applicability, do-not-say list, and source evidence are correct. If a page needs correction, edit the page itself; do not create another FAQ for the same concept unless the information is user-facing and intentionally public.
