---
id: bisq1-trade-funding-security-deposits
title: Bisq 1 trade funding, security deposits, and cancellation boundaries
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: high
source_refs:
- wiki:Security deposit
- wiki:Trading rules
- wiki:Deposit transaction
- wiki:Dispute Resolution in Bisq 1
- wiki:Mediation
- wiki:Arbitration
- wiki:Account limits
- wiki:Payment account age witness
- wiki:Support Agent Knowledge Base
- faq:1117
- faq:1155
- faq:1156
- faq:1174
---
## Canonical Support Answer

In Bisq 1 multisig trades, the trade amount and both security deposits are locked in the security deposit transaction after an offer is taken and the transaction confirms. The security deposit is the main economic incentive for both traders to follow the protocol rules; it is not held by Bisq as a custodial escrow account.

Before making or taking an offer, the wallet must have enough spendable BTC for the trade amount if applicable, security deposit, trading fee, and miner fees. A displayed wallet balance may still be hard to use if it is split across many small UTXOs or if wallet state is stale. If funding looks sufficient but Bisq says it is not, check spendable UTXOs and wallet sync before assuming a bug. Multiple smaller UTXOs may need to be consolidated into one, before the offer can be successfully taken.

An open offer deactivating before a trade starts is different from a funded trade with a confirmed deposit transaction. A maker fee might be lost if an offer publication fails, but the security deposit is not locked until the deposit transaction exists. If the deposit transaction is missing, use the failed-trade workflow; if it is confirmed, use mediation/dispute guidance for cancellation or payout problems.

After a trade is funded, a user usually cannot cancel it unilaterally without consequences. If a buyer cannot pay, payment details are invalid, a bank blocks the transfer, or the peer is unresponsive, the safe path is trader chat and mediation. Penalties depend on the trade rules, evidence, mediator/arbitrator review, and security-deposit size. Do not promise a no-penalty cancellation unless the protocol/support evidence clearly supports it.

Account limits and signing affect who can take offers and at what size. Sellers do not need account signing in the same way fiat buyers do; signing and limits are primarily about reducing chargeback risk for fiat payment methods. For very large trade-size questions, explain that users can participate in multiple trades of smaller amounts.

## Applies When

- The user asks whether BTC is frozen/locked when an offer is taken.
- The user asks how Bisq 1 multisig escrow/security deposits work.
- The user cannot place an offer despite apparently sufficient balance.
- The user asks whether an offer maker can lose a security deposit when an offer deactivates.
- The user asks how to cancel a funded trade without losing funds.
- The user asks what happens if payment cannot be made or confirmed.
- The user asks about account-signing limits, unsigned buyers, or who can take an offer.
- The user asks whether a seller can receive protection if the buyer is unresponsive.

## Do Not Say

- Do not describe Bisq as a custodial escrow service.
- Do not say a security deposit is locked before a valid deposit transaction exists.
- Do not promise cancellation without penalty after the trade is funded.
- Do not tell users to send funds to changed or invalid payment details outside mediation.
- Do not conflate Bisq 1 multisig security deposits with Bisq Easy reputation.

## Evidence / Sources

- `wiki:Security deposit` explains the Bisq 1 security-deposit model and why deposits protect honest traders.
- `wiki:Trading rules` documents behavior that can lead to penalties or mediation.
- `wiki:Deposit transaction` explains when trade/security-deposit funds are actually locked.
- `wiki:Dispute Resolution in Bisq 1`, `wiki:Mediation`, and `wiki:Arbitration` document cancellation/dispute resolution boundaries.
- `wiki:Account limits` and `wiki:Payment account age witness` document signing and fiat limit mechanics.
- `wiki:Support Agent Knowledge Base` documents transaction structure and trade transaction checks.
- `faq:1117` covers seller signing limits.
- `faq:1155`, `faq:1156`, and `faq:1174` cover invalid payment details, stuck confirmation, and delayed incoming payment cases.

## Review Notes

- Exact penalty percentages and account limits can change; verify current Bisq 1 docs/UI before quoting numbers.
- Technical deep-dives into transaction anatomy should point to source documentation or reviewed forum material rather than being invented from support-chat snippets.

## Last Change Summary

Added a consolidated Bisq 1 trade-funding page to absorb recurring candidates about security deposits, spendable balance, account limits, failed offer funding, and cancellation/dispute boundaries.
