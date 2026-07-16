# Channel launch runbook

Use this runbook only after the fail-closed delivery, public-boundary, and
truthful-readiness workstreams are merged and their checks are green. It is a
human-operated procedure. Nothing in this runbook authorizes an unattended
production change.

## Safety invariants

- `AUTONOMOUS_DELIVERY_ENABLED=false` is the startup-safe default.
- Matrix and Bisq launch policies start in shadow mode.
- Existing Matrix and Bisq generation and autoresponse policies remain disabled
  until a human explicitly starts the relevant phase.
- Shadow mode runs the full answer pipeline but persists every direct-delivery
  candidate in the review queue. It sends no answer or queue notification to a
  channel user.
- A shadow review record keeps the original routing action and records
  `launch_control=shadow_mode; would_have_sent=<action>` as its routing reason.
- The global kill switch is read for every dispatch. It does not prevent a staff
  member from sending a reviewed escalation response manually.
- Canary limits are rolling one-hour and 24-hour limits. A reservation is made
  before transport delivery, so a failed attempt conservatively consumes quota.
  Duplicate message IDs never receive a second reservation.
- During canary, unreserved acknowledgments, timeout and dispatch-failure notices,
  and automatic review-queue notifications remain suppressed. Primary answers
  and feedback messages may send only after their own atomic reservation.
- The protected status output exposes only a per-channel
  `canary_reservation_count`; it never exposes raw or hashed message identifiers.
- Reservation keys are one-way hashes rather than raw channel message IDs. The
  scheduled privacy-retention job deletes them after two days, or sooner when
  the configured privacy window is shorter.

## Control interface

Set `ADMIN_BASE_URL` and `ADMIN_API_KEY` in the operator shell without printing
either value. When using the website gateway, the base URL includes its `/api`
prefix. Inspect the current state:

```bash
scripts/channel-launch-control.sh status
```

Stop autonomous delivery immediately:

```bash
scripts/channel-launch-control.sh kill
```

The admin kill-switch change is immediate and persists across restarts. A false
`AUTONOMOUS_DELIVERY_ENABLED` environment guard forces the admin switch off at
startup and prevents runtime enable. A fresh database starts with the admin
control disabled even when the environment guard is true. A true environment
guard permits, but never performs or overrides, an admin enable or stop.

## Roles and evidence

Assign these people before a drill:

- launch owner: authorizes each phase transition;
- support reviewer: reviews drafts and records correctness/safety outcomes;
- operator: changes controls and watches readiness/alerts;
- rollback owner: has authority to stop the canary immediately.

Create a sanitized evidence record containing the release identifier, timestamps,
channel, test-case identifiers, review outcomes, relevant alert names, and the
final go/no-go decision. Do not copy user messages, credentials, room identifiers,
service addresses, or session material into the evidence record.

## Phase 0: preflight

1. Confirm the release-binding AI-quality gate passed for the exact release.
2. Confirm `/health/ready` is ready and every required component is healthy.
3. Confirm critical-service targets, scheduler heartbeat, and alert delivery are
   healthy; run the alert-delivery drill if its periodic result is stale.
4. Confirm the global launch control reports disabled.
5. Confirm Matrix and Bisq policies report `shadow_mode=true`,
   `canary_enabled=false`, zero canary limits, and zero
   `canary_reservation_count` on a fresh launch database.
6. Confirm the review queue is available and staff can claim, edit, send, and
   close a synthetic review item.
7. Confirm the rollback owner can execute the kill-switch command and can disable
   existing channel autoresponse policy independently.
8. Record the approved test identities and test conversations. Never use an
   uninvolved user's conversation for a delivery drill.

No phase transition is allowed while readiness is degraded, alert delivery is
unverified, the review queue is unavailable, or the rollback owner is absent.

## Phase 1: shadow mode

Keep global autonomous delivery disabled while first validating basic queue
plumbing. A true would-have-sent shadow run requires the raw routing decision to
reach launch control: after confirming `shadow_mode=true`, a human enables both
generation and the existing autoresponse policy for only the channel under test.
The launch owner then changes the environment guard to true, restarts and checks
readiness, and enables the global admin control. Shadow mode remains the delivery
barrier.
Verify each generated direct-delivery candidate appears in the review queue with
its original routing action. If the channel autoresponse policy stays disabled,
its older queue override masks the original would-have-sent decision and does not
qualify as shadow evidence.

For each channel, exercise a reviewed and sanitized sample containing:

- routine documentation questions;
- live-data questions and an unavailable-live-data case;
- scams, seed words, urgent trade issues, and other mandatory escalations;
- ambiguous, low-relevance, and unsupported questions;
- multilingual questions where supported;
- repeated and concurrent inbound events.

For every direct-delivery candidate, verify:

- no answer or queue notice reached the user;
- exactly one pending review record exists;
- the AI draft and sources are present;
- the original direct routing action is present;
- the routing reason records `launch_control=shadow_mode` and the
  `would_have_sent` decision;
- the reviewer can reject, edit, or manually send the draft.

### Shadow exit criteria

The launch owner must define the observation duration and minimum reviewed sample
before the phase begins. At minimum, require all of the following:

- zero unsafe autonomous-send candidates;
- zero missing or duplicate review records;
- zero user-facing delivery from shadow decisions;
- all safety, live-data failure, and low-relevance cases route as expected;
- reviewer acceptance and edit-rate targets are met separately for each channel;
- timeouts and dependency failures fail closed;
- every incident found in shadow has a tracked fix and a passing regression test;
- readiness and critical alerts remain healthy for the entire window.

If any criterion fails, keep shadow mode on and the global switch off.

## Phase 2: bounded canary

The launch owner must choose separate hourly and daily limits for Matrix and Bisq.
The hourly limit must not exceed the daily limit. Start with the smallest volume
that can validate a real delivery, and increase only after reviewing every prior
canary send.

Configure limits without leaving shadow mode:

```bash
scripts/channel-launch-control.sh canary matrix on HOURLY_LIMIT DAILY_LIMIT
scripts/channel-launch-control.sh canary bisq2 on HOURLY_LIMIT DAILY_LIMIT
```

After a four-eyes review of the reported policy, turn shadow off for only the
channel being tested:

```bash
scripts/channel-launch-control.sh shadow matrix off
```

If it is not already enabled for the shadow run, enable the global switch only
after the existing channel autoresponse policy and the canary configuration have
both been reviewed:

```bash
CONFIRM_AUTONOMOUS_DELIVERY=YES scripts/channel-launch-control.sh enable
```

Never canary both channels for the first time in the same window. Traffic above
either rolling limit must create a review record with the original
`would_have_sent` action and must not reach the user.

## Delivery and failure drills

Run each drill with an approved test identity. Record only sanitized outcomes.

### Matrix delivery

1. Send one approved, high-confidence test question.
2. Verify exactly one reply arrives in the intended test thread.
3. Verify the reply content, sources, language, and correlation identifier.
4. Verify the canary reservation count increases by one.
5. Verify no other room or user receives a message.

### Bisq delivery

1. Send one approved, high-confidence test question in the test conversation.
2. Verify exactly one reply arrives in that conversation.
3. Verify content, source rendering, and correlation identifiers.
4. Verify the canary reservation count increases by one.
5. Verify no other conversation receives a message.

### Escalation

1. Submit a mandatory-escalation and a low-confidence question.
2. Verify no AI answer is delivered autonomously.
3. Verify one review record contains the draft, routing reason, and source context.
4. Claim and manually answer one case; verify the reviewed answer reaches only the
   originating test conversation.

### Timeout

1. In a controlled test window, inject an approved timeout into the live-data or
   model dependency used by the test case.
2. Verify the request produces the deterministic unavailable response or a review
   item, according to policy.
3. Verify static text is not presented as current live data.
4. Restore the dependency and verify readiness before continuing.

### Duplicate event

1. Replay the same approved event identifier through the test ingress.
2. Verify at most one answer is delivered and at most one canary reservation is
   retained.
3. Verify a duplicate that reaches launch control is denied with
   `duplicate_reservation` and routed to review.

### Transport failure

1. In a controlled test window, inject one approved Matrix or Bisq send failure.
2. Verify the failure is logged and alerts fire where configured.
3. Verify the failed attempt consumes canary quota and is not retried beyond the
   existing idempotency policy.
4. Restore the transport and verify readiness before continuing.

### Kill switch

1. While the canary is healthy, run `scripts/channel-launch-control.sh kill`.
2. Submit a new direct-delivery candidate.
3. Verify it enters review with `launch_control=kill_switch` and no channel message
   is sent.
4. Verify an already queued case can still be handled manually by staff.
5. Do not re-enable until the launch owner records approval.

## Promotion criteria

Before increasing a cap or disabling canary mode, require:

- every canary send reviewed and classified;
- zero safety-policy violations or cross-conversation deliveries;
- no unexplained duplicates, timeouts, or stale live-data claims;
- alerting and readiness remained healthy;
- support staffing covers the next observation window;
- rollback owner and launch owner both approve the new limit in the evidence record.

Canary thresholds, observation duration, acceptance/edit-rate targets, and the
decision to enter unrestricted delivery remain human decision points.

## Rollback

At the first safety, privacy, routing, duplicate-delivery, or dependency concern:

1. Run `scripts/channel-launch-control.sh kill`.
2. Set the deployment environment guard to false before any API restart.
3. Disable the existing autoresponse policy for every affected channel.
4. Set the affected channel back to shadow mode.
5. Disable its canary policy; do not delete reservations or review evidence.
6. Verify a new direct candidate is queued with no user-facing delivery.
7. Confirm readiness and alerts, preserve sanitized incident evidence, and notify
   the launch and rollback owners.
8. Revert to the last approved release if the fault is release-specific, following
   the deployment rollback runbook.
9. Require a root-cause review, regression test, green release-quality gate, and a
   new explicit launch-owner approval before another canary.

Useful rollback commands:

```bash
scripts/channel-launch-control.sh kill
scripts/channel-launch-control.sh shadow matrix on
scripts/channel-launch-control.sh shadow bisq2 on
scripts/channel-launch-control.sh canary matrix off
scripts/channel-launch-control.sh canary bisq2 off
scripts/channel-launch-control.sh status
```
