---
id: bisq1-payout-output-inconsistency
title: Bisq 1 payout output and address-reuse inconsistency after payment confirmation
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: multisig_v1
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: high
source_refs:
- wiki:Trade payout address reuse issue
- wiki:Support Agent Knowledge Base
- wiki:Mediation
---
## Canonical Support Answer

If a Bisq 1 trade status shows completed right after payment was marked as sent, separate UI state from on-chain payout state. First check whether the payout transaction actually exists and whether the buyer received the expected trade amount plus security deposit in the Bisq wallet transaction history or on a block explorer.

For the question "After confirming payment received, a trade shows cancelled/output errors. What should be checked?", answer with the checks, not a conclusion: payout transaction existence, buyer wallet history, block explorer status, deposit transaction ID, and any payout transaction details.

If the payout is not visible or the app state is inconsistent, keep the trade data intact and open mediation or contact support with the trade ID, onion address, deposit transaction ID, and any payout transaction details. A mediator/support agent may need those transaction IDs to determine whether funds are still locked, already paid out, or affected by an address-reuse/output-state bug.

## Applies When

- A Bisq 1 trade shows cancelled/output errors after confirming payment received.
- The user asks what should be checked after confirming payment received but seeing cancelled/output errors.
- The buyer sees a completed trade but no incoming payout transaction.
- The seller pressed payment received but the peer reports no BTC payout.
- Support needs to distinguish wallet display state from the actual multisig payout.

## Do Not Say

- Do not tell the user to delete trade data before transaction state is understood.
- Do not assume an SPV resync is sufficient when the issue may require mediator visibility.
- Do not say the payout happened unless the payout transaction or wallet history confirms it.
- Do not claim funds are lost before checking the payout transaction and deposit transaction state.

## Evidence / Sources

- `wiki:Trade payout address reuse issue` documents cases where one side can see a completed trade while the actual payout path still needs verification or mediation.
- `wiki:Support Agent Knowledge Base` lists maker fee, taker fee, deposit, delayed payout, and payout transactions as support-agent evidence points.
- `wiki:Mediation` says mediators check maker fee, taker fee, and deposit transaction IDs and can request more details when funds may be stuck.

## Review Notes

- Exact current UI wording for the affected output errors should be verified from logs/screenshots.

## Last Change Summary

Converted from generated support playbook into internal LLM Wiki page after RAGAS exposed payout/output weakness; ready for local support-admin review.
