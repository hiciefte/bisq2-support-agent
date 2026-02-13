# ADR: Escalation Lifecycle Decisions

**Status**: Accepted
**Date**: 2026-02-09
**Context**: Escalation Learning Pipeline (spec: `claudedocs/spec/escalation-learning-pipeline/`)

## 1. Idempotency via message_id

**Decision**: Duplicate `message_id` on `create_escalation()` returns the existing escalation unchanged.

**Rationale**: Channel gateways may retry on timeout or network errors. Creating a duplicate escalation for the same user question would confuse staff and waste effort. Using `message_id` as a natural idempotency key avoids this without requiring client-generated idempotency tokens.

**Constraint**: The `message_id` column carries a UNIQUE index. Insert-or-return-existing is implemented via `INSERT OR IGNORE` followed by a SELECT on conflict.

## 2. Save-First Delivery Semantics

**Decision**: Escalation records are persisted to SQLite before delivery is attempted. Delivery failure does not block or roll back the escalation.

**Rationale**: A lost escalation (staff never sees the question) is worse than a delayed delivery notification (user gets the notification late). By saving first, the escalation is always queryable from the admin queue even if the outbound channel message fails.

**Constraint**: `delivery_status` tracks delivery outcome separately (`not_required`, `pending`, `delivered`, `failed`). Retries are bounded by `ESCALATION_DELIVERY_MAX_RETRIES` (default 3).

## 3. Polling Statuses

**Decision**: The user-facing polling endpoint returns two statuses: `pending` (no staff response yet) and `resolved` (staff responded or escalation was closed).

**Rationale**: Minimal surface area for the frontend. The admin side has richer states (open, claimed, responded, closed) but the user only needs to know whether help has arrived.

**Constraint**: Polling uses `message_id` (UUID from the original question), not sequential database IDs. This prevents enumeration attacks where a user could poll other users' escalations by incrementing an integer ID.

## 4. Channel Extensibility Contract

**Decision**: New channels integrate with escalation by implementing two abstract methods on `ChannelBase`:
- `get_delivery_target(metadata)` — extract the outbound target from channel metadata
- `format_escalation_message(username, escalation_id, support_handle)` — produce the user-facing notification text

**Rationale**: The `EscalationPostHook` and `ResponseDelivery` service delegate channel-specific logic to the adapter. This avoids `if channel == "matrix"` branches in shared code and makes adding a fourth channel a single-class change.

**Constraint**: `IncomingMessage.channel_metadata` must store the delivery target key (e.g., `room_id` for Matrix, `conversation_id` for Bisq2). Web returns empty string (no push delivery; polled from DB).

## 5. Bisq2 Transport Transition

**Decision**: Bisq2 channel prefers WebSocket for real-time delivery when available, falling back to HTTP polling when the WS connection is unavailable or degraded.

**Rationale**: The Bisq2 API may expose a WebSocket endpoint for bidirectional messaging. Using WS enables instant delivery notifications. However, the WS API contract is unconfirmed, so polling must remain the baseline.

**State machine**: `disconnected -> connecting -> connected -> degraded_polling -> connecting`

**Constraint**: WS enablement is gated by `ESCALATION_BISQ2_WS_ENABLED` feature flag (default False). The WS frame contracts (inbound/outbound) in the spec are proposed and must be validated against the actual Bisq2 API before enabling.

## 6. Claim TTL

**Decision**: Staff claims on escalations expire after `ESCALATION_CLAIM_TTL_MINUTES` (default 30). Expired claims are released for other staff to pick up.

**Rationale**: Prevents a staff member from accidentally locking an escalation indefinitely if they navigate away or lose connection.

## 7. Auto-Close and Retention

**Decision**: Unresponded escalations auto-close after `ESCALATION_AUTO_CLOSE_HOURS` (default 72). Closed/responded escalations are purged after `ESCALATION_RETENTION_DAYS` (default 90).

**Rationale**: Stale escalations clutter the admin queue. Retention purging keeps the database bounded without manual cleanup.

**Constraint**: Maintenance runs as an asyncio background task on a configurable interval.
