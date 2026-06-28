---
id: bisq2-btc-only-altcoin-path
title: 'Bisq Easy BTC scope: buying and selling Bitcoin only'
type: llm_wiki
page_type: support_playbook
status: reviewed
protocol: bisq_easy
reviewed_by: suddenwhipvapor
reviewed_at: '2026-06-27'
risk_level: low
source_refs:
- wiki:Bisq Easy
- wiki:Trade Protocols
- faq:53
- faq:69
- faq:70
- faq:88
- faq:107
- faq:340
- faq:697
- faq:1058
---
## Canonical Support Answer

Bisq Easy is currently BTC-focused from the user's asset perspective: it allows users to buy or sell bitcoin. It is especially useful for a new user who needs their first BTC UTXO without KYC and without a security deposit.

For the direct question "Is Bisq Easy only for buying Bitcoin?", answer: no, Bisq Easy can be used to both buy and sell BTC, but BTC is still the central asset in Bisq Easy. Do not phrase this as direct stablecoin or altcoin trading.

Users may pay for BTC with fiat, and some Bisq Easy documentation mentions paying with altcoins, but support should not present Bisq Easy as a stablecoin or altcoin trading venue. If the user wants altcoins or other non-BTC assets, the normal guidance is to point them to Bisq 1. Bisq does not receive fiat or custody digital assets, whether bitcoin, altcoins, or stablecoins. Users looking to obtain altcoins or stablecoins can first acquire BTC, then use Bisq 1 where supported altcoin markets exist, or wait for future Bisq 2 protocols that may support other assets.

Bisq 1 and Bisq 2 can both be relevant: Bisq Easy can help a new user obtain initial BTC, while Bisq 1 currently offers the multisig protocol and additional markets, featuring larger volume and liquidity, and smaller spread.

## Applies When

- The user asks whether Bisq Easy is BTC-only.
- The user asks whether Bisq Easy is only for buying Bitcoin.
- The user asks if Bisq Easy also supports selling Bitcoin.
- The user asks whether they can buy stablecoins directly with fiat through Bisq.
- The user asks whether they need both Bisq 1 and Bisq 2.
- The user asks how to get from fiat to altcoins using Bisq.

## Do Not Say

- Do not say users send fiat to Bisq itself.
- Do not say Bisq Easy directly supports stablecoin custody or fiat-to-stablecoin exchange.
- Do not answer "Bisq Easy BTC-only?" by implying users can directly buy non-BTC assets on Bisq Easy.
- Do not answer "Is Bisq Easy only for buying Bitcoin?" with "sell Bitcoin for fiat or altcoins"; say "buy or sell BTC" and keep non-BTC assets separate.
- Do not confuse planned future Bisq 2 protocols with currently available Bisq Easy behavior.

## Evidence / Sources

- `wiki:Bisq Easy` describes Bisq Easy as a protocol to buy or sell bitcoin, with fiat/altcoin wording referring to how BTC can be paid for rather than a direct stablecoin custody flow.
- `wiki:Trade Protocols` says Bisq Easy is the sole implemented Bisq 2 protocol and lists future protocols separately.
- `faq:53`, `faq:1058`, and `faq:340` explain Bisq Easy as a path to first BTC/UTXO and later Bisq 1 use.
- `faq:107` and `faq:697` point altcoin trading to Bisq 1 after obtaining BTC.
- `faq:69` and `faq:70` compare selling between Bisq 1 and Bisq Easy.

## Review Notes

- Improved wording and semantics
- Clearly presented Bisq 1 as the platform for normal trading, and Bisq Easy as introduction for nocoiners
- General outlook of the original article was acceptable

## Last Change Summary

Clarified Bisq Easy scope, and altcoin/stablecoin paths availability
