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
- Bisq live ingress, reactions, reviewed sends, ChatOps notices, and autonomous
  sends require an exact match in both `BISQ2_ALLOWED_CHANNEL_IDS` and
  `BISQ2_ALLOWED_SENDER_PROFILE_IDS`. Either list being empty, malformed, or
  missing denies all access. Conflicting identifier aliases also deny access.
  These allowlists narrow scope; they never enable generation, autoresponse, or
  autonomous delivery.
- The same Bisq allowlists gate scheduled/admin FAQ-training ingestion even when
  the live Bisq channel is disabled. A blank scope intentionally makes that sync
  a no-op during the soak; this is a safety state, not a scheduler fault. Once
  both lists are valid and nonempty, the export API becomes a required readiness
  dependency even while the live channel stays disabled.
- A Bisq support channel is a group, not a private user conversation. Replies
  are visible to its participants. Use a dedicated upstream test channel/feed
  with only approved participants whenever possible; the sender-profile list is
  still mandatory as a second boundary.
- Every configured Bisq staff profile must also be in the sender-profile
  allowlist. When ChatOps is enabled, both its channel list and its in-scope
  staff-profile list must be nonempty. Staff authorization uses the immutable,
  case-sensitive profile ID; a display name or case-folded alias has no authority.
- Bisq training pairs a question and staff answer only within one exact allowed
  channel, using immutable profile provenance. Nested citation text is discarded;
  only a same-channel reference to another verified in-scope message survives.
- Bisq feedback reactions must match the exact native channel and originating
  sender recorded for the delivered answer. Follow-ups and reviewed escalation
  replies carry that provenance separately from the model-safe user ID.
- Bisq readiness requires the complete durable sync-state interface, a
  successful atomic state write, a fresh scope baseline, and acknowledged
  reaction/support WebSocket subscriptions on the current receive loop.
- Run exactly one API process/replica during this test phase. The Bisq sync-state
  file is atomic within that process but is not a multi-process coordination
  database. Horizontal API scaling requires a shared durable inbox first.
- Bisq ingress deliberately uses at-most-once deduplication for the test phase.
  An event is durably claimed after pure preprocessing and immediately before
  staff side effects or return to orchestration. A process loss after that claim
  is not replayed automatically; resend the approved test event and record the
  failed drill. This favors no duplicate external action, but it is not a
  release-grade delivery guarantee. A durable inbox/outbox with end-to-end
  acknowledgement is required before claiming resilient autonomous delivery.
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

For a long-running production soak, bind every deployed candidate to one exact
reviewed commit and its fresh quality-gate result. Label it as a soak or release
candidate; a final release tag is not required until final promotion. Any code,
model, prompt, retrieval, or tool change starts a new candidate and requires a
new gate result.

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
8. Record the approved test identities and test channels. Never use a normal
   public support channel or an uninvolved user's identity for a delivery drill.
9. Start with Matrix. Keep the Bisq channel disabled until both protected
   runtime allowlists contain only the dedicated test channel(s) and approved
   participant profiles. Expect scheduled/admin Bisq FAQ-training sync to process
   nothing while either list is blank; after configuration, it accepts only rows
   matching both exact dimensions. Expect the Bisq export startup probe and API
   readiness component to become required as soon as both lists are configured.
10. Confirm there is exactly one API process/replica and that the dedicated
    Bisq sync-state volume is writable. Do not proceed if readiness reports the
    persistence capability, persistence health, baseline, or subscription state
    unavailable.
11. Before enabling Bisq, drain or close every legacy pending Bisq escalation.
    If a case still needs action, recreate it only from a newly received,
    in-scope event with verified channel and originating-sender provenance.
    Never backfill missing origin identity from assumptions, unrelated metadata,
    or another record.
12. Before changing either Bisq allowlist, run the kill switch, disable the Bisq
    channel, and keep Bisq shadow mode on. Recreate the API container (do not
    merely restart it) after the protected configuration change so Compose
    reloads the environment, then enable only the Bisq channel and recreate the
    API container again.
    Confirm `/health/ready` reports `bisq2_test_scope` ready and that its
    `channel_count` and `sender_profile_count` equal the two independently
    reviewed counts. The response must not contain either list's values. Scope
    activation requires a fresh full baseline snapshot; readiness remains
    degraded and baseline acquisition retries independently of generation until
    one is available. Send only new test messages after readiness is green.

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

Measure each channel separately over one contiguous window of seven consecutive
healthy days. The cohort is every unique direct-delivery candidate generated for
that channel during the window. Give every candidate exactly one mutually
exclusive disposition:

- `accepted_unchanged`: accepted with no answer edit;
- `accepted_non_substantive_edit`: accepted after spelling, grammar, formatting,
  or another meaning-preserving edit;
- `accepted_substantive_edit`: accepted only after changing the answer's meaning,
  instructions, safety guidance, or source-supported facts;
- `rejected`: not accepted for delivery.

For that channel and window, `reviewed_count` is the number of candidates in the
cohort, `accepted_count` is the sum of the three accepted dispositions, and
`substantive_edit_count` is the number marked
`accepted_substantive_edit`. A substantively edited answer therefore counts in
both `accepted_count` and `substantive_edit_count`. Evaluate the unrounded integer
ratios against these approved initial floors:

- `reviewed_count >= 100`;
- `accepted_count / reviewed_count >= 0.95`;
- `substantive_edit_count / reviewed_count <= 0.10`.

Any readiness failure or critical alert during the window resets the seven-day
clock for that channel. The legacy `/admin/training/learning/readiness` endpoint
is a global learning-calibration signal with a different cohort and thresholds;
it is not this per-channel shadow promotion gate. These are minimum evidence
floors, not an automatic promotion: the launch owner must explicitly approve
every transition. Also require all of the following:

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

1. Confirm the Bisq test-scope component is ready and both counts match the two
   approved runtime-only allowlists.
2. Send one approved, high-confidence question from an approved profile in the
   dedicated test channel.
3. Verify exactly one reply arrives in that group channel and is visible only to
   its expected test participants.
4. Verify content, source rendering, and correlation identifiers.
5. Verify the canary reservation count increases by one.
6. Verify no other channel receives a message.
7. Exercise one sanitized out-of-scope fixture through the controlled ingress
   harness. Verify it creates no cache/history entry, review item, reaction side
   effect, transport request, or canary reservation.

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

Canary thresholds, canary observation duration, and the decision to enter
unrestricted delivery remain human decision points. Meeting the shadow floors
does not authorize any canary or autoresponse enablement.

## Rollback

At the first safety, privacy, routing, duplicate-delivery, or dependency concern:

1. Run `scripts/channel-launch-control.sh kill`.
2. Set the deployment environment guard to false before any API restart.
3. Disable the existing autoresponse policy for every affected channel.
4. Set the affected channel back to shadow mode.
5. Disable its canary policy; do not delete reservations or review evidence.
6. For Bisq containment incidents, atomically set
   `BISQ2_CHANNEL_ENABLED=false` and clear both protected runtime allowlists,
   then recreate the API while the kill switch remains active. Empty means deny
   all; disabling the channel keeps overall readiness healthy during rollback.
7. For an affected channel that remains enabled in shadow, verify a new direct
   candidate is queued with no user-facing delivery. If Bisq was disabled in step
   6, use the controlled ingress harness and verify that the fixture creates no
   candidate, cache/history entry, review item, reaction side effect, transport
   request, or canary reservation. Confirm the Bisq scope reports `disabled`; do
   not expect a queued item while the channel is disabled.
8. Confirm readiness and alerts, preserve sanitized incident evidence, and notify
   the launch and rollback owners.
9. Revert to the last approved release if the fault is release-specific, following
   the deployment rollback runbook.
10. Require a root-cause review, regression test, green release-quality gate, and a
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
