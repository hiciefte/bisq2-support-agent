---
id: bisq1-trade-funding-security-deposits
title: Bisq 1 funding, reservations and security deposits
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: ai-review:codex:knowledge-resolution-20260918
reviewed_at: '2026-09-18T09:25:43.205138+00:00'
risk_level: high
source_refs:
- https://bisq.wiki/Security_deposit
- https://bisq.wiki/Deposit_transaction
- https://bisq.wiki/Funding_your_wallet
- https://bisq.wiki/Account_limits
- https://bisq.wiki/Trading_rules
- https://bisq.wiki/Cloning_an_offer
- https://bisq.wiki/Trading_costs
- https://bisq.wiki/Resyncing_SPV_file
- https://bisq.wiki/Dispute_Resolution_in_Bisq_1
- https://bisq.wiki/Support_Agent_Knowledge_Base
- https://bisq.network/blog/bisq-v1-2-released/
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/offer/bisq_v1/CreateOfferService.java#L154
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/offer/bisq_v1/TakeOfferModel.java#L123
- https://bisq.wiki/Trading_fees
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/trade/protocol/bisq_v1/tasks/seller_as_maker/SellerAsMakerCreatesUnsignedDepositTx.java
---
## Canonical Support Answer

Bisq 1 multisig trades lock the full BTC sale amount plus the seller's security deposit and the buyer's security deposit in a shared 2-of-2 deposit. Bisq is not a custodian and support does not hold a third spending key. Funding protects the trade but does not guarantee a dispute outcome. Wait for the application's valid payment stage before sending fiat or altcoins.

### Funding an offer or trade

Use the exact funding requirement displayed for that offer: deposit, applicable trading/mining fees and, for a BTC seller, the BTC being sold. No historical starter balance is universally sufficient. The maker chooses permitted deposit settings subject to current app minimums; check the actual offer rather than an old numerical example. You cannot generally sell the entire wallet balance while also needing deposits and fees. A larger deposit does not guarantee prompt payment.

External funding is a Bitcoin transfer to the displayed funding address; it does not require connecting or exposing the external wallet's keys. If Open external wallet invokes an unconfigured Bitcoin URI handler or app-store prompt, manually copy the intended address and amount into your own wallet instead. Verify address and amount before sending. A confirmed external funding transaction is not itself confirmation of the shared deposit. If Waiting for funds persists, inspect address, amount, spendable outputs and local sync with support.

Displayed total, available, reserved and locked balances are different. Fragmented inputs, fees or stale local state can affect spendability. Do not consolidate blindly or assume consolidation reduces the required deposit; preserve active-trade state and assess actual outputs first. Both peers need connectivity for taking an offer and the initial protocol exchange; later absence must be handled according to the actual trade stage, not assumed harmless.

### Untaken offers and normal payout

Untaken offers reserve funds locally; removing one does not create a refund transaction. Confirm all clones using the same reservation are removed and none was taken. Already spent maker fees, including BSQ fees, are not automatically returned. A taken, funded trade is different and needs mediation for cancellation.

In a normal completed payout the BTC buyer receives the trade amount plus their own deposit, and the BTC seller receives their own deposit, subject to transaction fees. The sale amount is not paid out of the penalty deposit. Verify the payout if balances or completion status disagree. A withdrawal has a Bitcoin transaction ID but no trade ID because it is not a trade. Similar input/output amounts in a multi-input transaction do not prove a one-to-one ownership mapping.

### Limits, signing and payment problems

Account and offer limits apply per trade rather than as a daily allowance; current amounts depend on payment method, account age and signing. Chargeback-risk signing restrictions primarily constrain BTC buying. An unsigned seller can be legitimate, but signed status is not a safety guarantee. Offer size is not a universal new-user filter; making an offer does not remove applicable method limits. Multiple legitimate trades remain separate commitments with their own fees and constraints.

For invalid Pix/Wise/Zelle/Revolut/Interac details, bank limits, payment rejection or requested replacement links/accounts, select the trade and open mediation before changing the contract payment details. An alternative discussed in trader chat is not automatic authorization. Explain the exact error without inferring a blacklist or scam. If already paid, preserve proof and do not pay again. See the dispute page for deadline, cancellation and penalty handling.

## Applies When

Funding requirements, deposit protection, unsigned accounts, available/reserved/locked balance, cancelling an untaken offer, or normal payout allocation.

## Ranged offers, funding errors and duplicate transfers

For a conventional offer with a 0.1–0.2 BTC range, the maker’s trading fee is calculated when the offer is created from its maximum amount, 0.2 BTC. The taker’s trading fee uses the amount actually chosen within the range. Applicable minimum fees still apply. Security-deposit amounts are stored in the offer and taken from that offer, so choosing the lower trade amount does not simply recalculate them as the displayed percentage of 0.1 BTC. Verify the exact deposit and fee totals in the confirmation screen. These rules concern conventional Bisq 1 offers, not Bisq Easy or atomic BSQ swaps.

Identify the receiving address and both transaction IDs before doing anything else. A transfer to a Bisq wallet funding address is different from an extra output sent to the trade’s shared multisig address. Inspect both transfers in Funds > Transactions and the trade details. If the second transfer is not available to spend, preserve the data and ask verified support to identify its output and spending conditions. Do not assume trade completion will release an extra multisig payment or send another transaction to recover it.

An InsufficientMoneyException at deposit construction means the wallet could not assemble required inputs for that attempt; it does not prove funds disappeared or that resync will supply funds. Compare the complete funding requirement, usable outputs and reservations before another attempt.

Both traders contribute through their funding chains. An unfamiliar input address does not by itself identify the peer; inspect the transaction graph rather than infer ownership from amounts.

## Evidence / Sources

- [Security deposit](https://bisq.wiki/Security_deposit)
- [Deposit transaction](https://bisq.wiki/Deposit_transaction)
- [Funding your wallet](https://bisq.wiki/Funding_your_wallet)
- [Account limits](https://bisq.wiki/Account_limits)
- [Trading rules](https://bisq.wiki/Trading_rules)
- [Cloning an offer](https://bisq.wiki/Cloning_an_offer)
- [Trading costs](https://bisq.wiki/Trading_costs)

- https://bisq.wiki/Resyncing_SPV_file
- https://bisq.wiki/Dispute_Resolution_in_Bisq_1
- https://bisq.wiki/Support_Agent_Knowledge_Base
- https://bisq.network/blog/bisq-v1-2-released/
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/offer/bisq_v1/CreateOfferService.java#L154
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/offer/bisq_v1/TakeOfferModel.java#L123
- https://bisq.wiki/Trading_fees
- https://github.com/bisq-network/bisq/blob/b3f44d2b4cda28dd04cd0218cb6e99cbe7c48e63/core/src/main/java/bisq/core/trade/protocol/bisq_v1/tasks/seller_as_maker/SellerAsMakerCreatesUnsignedDepositTx.java

## Review Notes

Independently checked against original conversations and primary references by the parent AI reviewer. This amendment resolves candidate IDs 486, 616, 861, 1134, 1336, 1527. Earlier review evidence remains in the private batch audit. Preserve version and protocol qualifications and do not infer missing case outcomes.

## Last Change Summary

Resolved the remaining reviewed candidates using verified technical behavior and conditional diagnostic guidance. Reviewer: `ai-review:codex:knowledge-resolution-20260918`. New pages are explicitly identified in the private publication manifest.
