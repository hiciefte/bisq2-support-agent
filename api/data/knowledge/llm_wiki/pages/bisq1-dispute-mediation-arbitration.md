---
id: bisq1-dispute-mediation-arbitration
title: Bisq 1 mediation and arbitration flow
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: high
source_refs:
- wiki:Dispute Resolution in Bisq 1
- wiki:Mediation
- wiki:Arbitration
- wiki:Trading rules
- wiki:Security deposit
- wiki:Account limits
- wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees
---
## Canonical Support Answer

Bisq 1 dispute resolution has stages: trader chat, mediation, and arbitration. Most trade problems should first be handled through the built-in trader chat and then mediation. Keep communication inside Bisq whenever possible so the mediator can review the trade context and evidence.

Mediation can be opened from the trade flow when the trade period has expired and a button becomes available to optionally start a dispute; in some Bisq 1 situations support staff may tell the user to use the trade panel shortcut such as `Ctrl+O` or `Cmd+O`. A mediator can review transaction IDs, payment proof, chat contents, and trade-rule compliance, then propose a payout. A mediator does not unilaterally control the multisig funds; the proposal needs the protocol's normal cooperation/signature path. Mediators and traders have up to 48 hours to reply in support chat. Traders who do not reply within 48 hours can be penalized by the mediator.

If a buyer sent fiat and the BTC seller has not released BTC, the buyer should keep the trade data intact, communicate in trader chat, and open mediation when the trade period expires, and the relevant button is available. The buyer should be ready to provide proof of payment. If the seller says payment details are wrong, the payment method failed, or the payment was sent from/to unexpected details, route through mediation instead of giving informal off-platform instructions.

Arbitration is the last-resort stage after mediation fails or a mediation proposal is rejected and the delayed payout transaction can be published. The delayed payout transaction is time locked: 10 days after deposit confirmation for altcoin trades and 20 days after deposit confirmation for fiat trades, both denominated in number of blocks. Arbitration decisions are based on the evidence, mediator feedback, trade rules, and on-chain transaction state; RefundAgent, the contributor role responsible for arbitration, has up to 5 days to reply in chat, so users should remain responsive and provide requested evidence.

Once the timelock on the DPT (delayed payout transaction) has expired, arbitration can also be started using the `Ctrl+O` or `Cmd+O` shortcut from the trade panel, or by dumping the DPTs from the command line, and broadcasting the transaction hex.

If the deposit transaction is missing, invalid, or not found on-chain, use the failed-trade workflow instead of treating it as a normal mediation/arbitration case. If the deposit transaction exists and the app or payout state is inconsistent, collect the trade ID, maker fee txid, taker fee txid, deposit txid, payout/delayed-payout txid if present, and logs/screenshots for mediator or support review.

## Applies When

- The user asks what happens after mediation fails.
- The user asks when arbitration can be opened.
- The user asks who decides disputed payouts in Bisq 1.
- The user asks what proof to provide in mediation.
- The buyer paid fiat in Bisq 1 but BTC was not released.
- The seller or buyer is unresponsive during a trade, mediation, or arbitration.
- Both peers want to cancel or unwind a Bisq 1 trade after payment or banking problems.
- The user asks why funds are locked after mediation/arbitration or how a payout proposal is accepted.
- The user asks whether security deposits protect honest traders in the Bisq 1 multisig protocol.

## Do Not Say

- Do not say the mediator can unilaterally move multisig funds.
- Do not recommend opening arbitration before the protocol makes it available.
- Do not promise a specific payout before mediator/arbitrator review.
- Do not describe Bisq 1 cancellation as a simple local reject button when funds or payment may be involved.
- Do not tell the user to delete `PendingTrades`, dispute lists, or other database files as a first-line fix for locked funds.
- Do not tell a buyer to send fiat to changed or mismatching payment details without mediation review.
- Do not route missing/invalid deposit transactions through normal mediation if the trade never locked funds.

## Evidence / Sources

- `wiki:Dispute Resolution in Bisq 1` describes trader chat, mediation, arbitration, response expectations, 48-hour dispute-chat expectations, and payout suggestions.
- `wiki:Mediation` documents mediator duties, proof requests, and transaction checks.
- `wiki:Arbitration` explains arbitration availability, delayed payout transaction mechanics, 10/20-day delayed-payout timing, arbitrator response expectations, and DAO reimbursement context.
- `wiki:Trading rules` documents communication boundaries and payment-rule expectations.
- `wiki:Security deposit` explains the Bisq 1 security-deposit model.
- `wiki:Account limits` explains why fiat account limits and signing exist for chargeback-risk methods.
- `wiki:Failed Trades - Reimbursement of Trade Fees and Miner Fees` distinguishes missing/invalid deposit transactions from normal locked-funds disputes.

## Review Notes

- Current UI shortcuts/buttons for opening mediation/arbitration should be verified against the user's Bisq 1 version.
- Some production candidates contained case-specific Matrix handles, named traders, or broad risk claims; those were intentionally omitted from the reusable page.

## Last Change Summary

Curated the production dispute cluster into a single Bisq 1 mediation/arbitration page covering escalation stages, evidence collection, delayed-payout timing, failed-trade boundaries, and unsafe advice to avoid.
