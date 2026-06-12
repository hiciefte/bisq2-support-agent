# Product

## Register

product

## Users

This product serves Bisq support operators, support admins, and project maintainers who need to keep automated Bisq 2 support reliable under real operational pressure. They use the admin UI to review escalations, inspect quality signals, tune knowledge, manage FAQs, monitor trust and security signals, and verify that Matrix and Bisq 2 support flows stay healthy.

End users interact indirectly through the web chat, Matrix support rooms, and Bisq 2 support chat. They need accurate, source-backed answers, clear escalation when automation is not confident, and no exposure of private support data beyond what is required to resolve their issue.

## Product Purpose

Bisq 2 Support Agent is a RAG-based support system for Bisq 2. It combines wiki content, curated FAQs, LLM Wiki pages, support conversations, Bisq 2 live data, Matrix ingest, human feedback, and monitoring into one reviewable support workflow.

The product exists to answer common Bisq 2 support questions safely, reduce repeated human work, and turn recurring support evidence into a lean maintained knowledge base. Success means the assistant answers correctly when evidence is strong, escalates cleanly when evidence is weak, and gives support admins a clear path to improve the underlying knowledge without creating FAQ sprawl.

## Brand Personality

Calm, precise, and operator-grade.

The voice is concise and factual. It should feel like an expert support tool built for privacy-sensitive financial software, not a chatbot demo. UI copy should explain the next action, why it matters, and what evidence is being used. Avoid hype, vague confidence language, decorative personality, and unexplained internal labels.

## Anti-references

- Generic AI SaaS dashboards with decorative gradients, vague confidence badges, and unclear automation.
- Dark neon crypto dashboards, purple default palettes, and glassmorphism used for decoration.
- FAQ sprawl where every support discussion becomes a separate public answer.
- Opaque automation where a human cannot see why a response was generated or why a knowledge change is proposed.
- Dense admin screens that expose internal pipeline terms before explaining the operator's job.
- Playful copy in operator surfaces when the task involves security, trust monitoring, support escalation, or production health.
- Duplicate evidence lists, repeated badges, and redundant lanes that make the review order unclear.

## Design Principles

1. **Evidence before confidence.** The interface must show what sources support a claim before asking an admin to trust or approve it.
2. **Reviewable automation.** AI output is never a black box. Proposed answers, knowledge diffs, confidence thresholds, escalations, and alerts must be inspectable and reversible.
3. **One maintained knowledge source.** The long-term target is a lean LLM Wiki that absorbs recurring support learning. FAQs remain durable public answers, not the default sink for every support conversation.
4. **Progressive disclosure by risk.** Safe, routine items can stay compact. Risky, unsupported, security-sensitive, or user-facing changes need fuller context and explicit confirmation.
5. **Operator calm.** Admin screens should reduce cognitive load with clear queue order, action-oriented labels, stable layout, and restrained visual emphasis.
6. **Production parity.** Local and production flows should behave predictably. Monitoring, deployment, nginx routing, Matrix rooms, and Bisq API pairing need visible health states when they affect support quality.

## Accessibility & Inclusion

Target WCAG 2.2 AA for the web UI. Support keyboard navigation, visible focus states, readable contrast in light and dark themes, reduced-motion-safe interactions, and labels that do not rely on color alone.

Operator screens should use plain language for non-native English readers. Dates, source references, alert states, confidence states, and destructive actions must be explicit. Source links must be reachable, durable when possible, and clearly marked when they point to private or temporary evidence.
