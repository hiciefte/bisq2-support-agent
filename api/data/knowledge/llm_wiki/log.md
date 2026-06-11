# Internal LLM Wiki Log

## 2026-06-10

- Converted the generated support playbooks into internal LLM Wiki pages.
- Kept support playbooks as `page_type: support_playbook` instead of a top-level RAG source.
- Added schema, index, and log files so future support-chat learning creates reviewable LLM Wiki diffs instead of bloating public FAQs.
- Initial pages still require local human review before production activation.
- Tightened RAGAS regressions: removed low-signal indexed page-type header, clarified Bisq Easy BTC-only wording, added SPV-vs-mediation guidance for stuck Bisq 1 deposits, and added a Bisq 2 overview trade-totals known issue.

## 2026-06-10 - second RAGAS tightening pass

- Fixed score-based protocol routing so Bisq 1-only fee/deposit/error terms override the Bisq Easy default.
- Added exact support-query trigger wording to BTC scope, reputation, failed-trade fee, fee-transaction, payout-output, and arbitration pages.
- Separated arbitration payout/reimbursement guidance from timeout guidance to reduce unsupported answer drift.

- Added Bisq 1 payout/output-error routing terms after live query testing showed the payout-output sample still asked for clarification.
