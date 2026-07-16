# Release AI-quality gate

The release gate generates new answers with the release candidate's configured
model and full chat pipeline. It is separate from the fast pull-request path so
model cost and external-service variance do not slow ordinary reviews.

## What is bound to a release

The `Release AI Quality Gate` workflow runs for:

- pushes to one-segment `release/*` branches;
- version tags, which verify an existing result for their exact commit;
- a weekly drift check of the default branch; and
- explicit operator dispatches.

The workflow builds the API from the evaluated commit, starts an isolated
Qdrant-backed stack, and forces response and classification temperature to zero.
Matrix and Bisq response channels, chat-ops, and websocket escalation delivery
remain disabled. A synthetic Bisq API fixture exposes only reviewed market-price
and empty-offerbook data so the model must exercise the MCP tool path without
contacting users or production services.

The versioned input is
`api/data/evaluation/release_ai_quality_samples_v1.json`. It contains reviewed,
sanitized questions, staff answers, labels, and case-specific floors. Generated
answers are forbidden in that file. The set includes scam-warning, wiki-source,
diagnostic, explicit-escalation, live-price, and live-offerbook cases.

`api/app/scripts/release_ai_quality_gate.py` queries `/chat/query`, reuses the
staff-alignment behavior scorer, and enforces both aggregate thresholds and
per-case requirements. Per-case checks cover greeting avoidance, scam warning
presence or absence, wiki-link recall, diagnostic-question behavior, answer
length, remedy terms, review routing, and required MCP tools. Live-data cases
also require reviewed terms from the deterministic stub result to appear in the
answer, so merely naming a tool cannot pass the case.

The report binds its result to:

- the exact git commit;
- the configured model's SHA-256 identity, never its raw ID;
- temperature zero;
- the sample-set version and SHA-256; and
- a SHA-256 over the runtime prompt policy, soul, and prompt manager inputs.

Only the sanitized report is archived. It contains case IDs, metrics, routing
actions, and tool names. It excludes questions, answers, source text, tool
results, user identifiers, events, credentials, and service addresses. The
workflow clears any prior output before generation, the evaluator writes through
an atomic replacement, and a separate standard-library validator enforces an
exact allowlisted schema before upload. Missing or invalid output is replaced by
a text-free failing report and keeps the workflow failed.

## CI configuration

Repository administrators must first apply
`docs/runbooks/release-ai-quality-protection.md`. It creates the protected
`release-ai-quality` environment, reviewed release refs, and protected marker
namespace. Administrators then configure:

- environment secret `AI_QUALITY_GATE_OPENAI_API_KEY`;
- environment secret `AI_QUALITY_GATE_MARKER_TOKEN`, owned by the dedicated
  marker identity and limited to repository contents; and
- Actions variable `AI_QUALITY_GATE_OPENAI_MODEL`, set to the same model ID as
  the intended production release.

Neither credential may exist as a repository or organization secret. Every job
that can read one uses the protected environment, its required human reviewer,
and its `main` or `release/*` deployment policy. Version-tag verification uses
only the read-only default workflow token and never receives either credential.

The model variable must use the strict `openai:<model-id>` form. It is validated
before dotenv rendering, hashed before report construction, and never archived
as raw text.

The API image is built before runtime configuration exists. The API credential
is scoped only to the step that creates the isolated containers; Compose passes
it directly into the API container. It is never written to a workspace file,
sent in a Docker build context, echoed, or made available to artifact and marker
jobs. Context-specific `.dockerignore` files independently exclude dotenv files,
runtime data, secrets, local databases, generated Python output, and frontend
build caches. Rotate the credential using the protected-environment secret
procedure. Never paste its value into workflow logs, artifacts, issues, or
deployment configuration.

All third-party actions are pinned to reviewed commit SHAs. Sanitized reports
are retained as build artifacts for 30 days, including failed gate reports.

## Release and deployment flow

1. Push the candidate to a reviewed release branch.
2. Confirm the `Fresh-Answer AI Quality Gate` job completed successfully.
3. Review the sanitized artifact, including every per-case result.
4. If a model, prompt, retrieval, or tool change is intentional, update and
   re-review the versioned sample or floors in a separate change. Never lower a
   floor merely to make a release pass.
5. Create the intended version tag and confirm its marker-verification job.
6. Run the normal deployment or update script.

Before every fresh-answer run, the environment-scoped marker identity removes
prior quality markers for the exact commit. Runs targeting the same commit are
serialized even when one arrived from a branch and another from a tag. A passing
run publishes the lightweight tag
`release-ai-quality/<commit>/<model-sha256>`; a failed, timed-out, or cancelled
evaluation after invalidation leaves no marker. The model credential is not
available to either marker job.

A `v*` event never generates answers or receives provider credentials. It
requires the existing marker for the tag's exact commit and configured model.

`scripts/verify-release-ai-quality-gate.sh` reads exactly one strict
`OPENAI_MODEL` entry from the protected runtime environment file, derives its
SHA-256 without printing the value, and requires the remote marker for that
commit and model to point to the exact commit being deployed. It also queries
the authoritative workflow record for the commit. The newest eligible release,
scheduled, or manual fresh-answer run must be completed successfully; a failed,
cancelled, queued, or unreachable latest run rejects an older marker. A pass for
one model cannot authorize the same code with another model.

The verifier also requires the checked-out `HEAD`, tracked content, and every
nonignored untracked path to match the evaluated commit. Docker contexts exclude
ignored runtime and generated files that could otherwise contaminate a build.
Release updates reject local source changes before backup, fetch, reset, or
legacy stash handling. Preserve operational configuration and data only in the
documented ignored runtime paths; commit reviewed source changes normally.

Initial deployment verifies the workflow result, source tree, and marker after
protected runtime configuration is ready but before building any service.
Updates verify them after fetching the candidate but before migration, build,
restart, or health checks. Missing, unreachable, stale, dirty, or mismatched
commit/model evidence stops deployment; an update with a newly fetched candidate
follows the existing rollback path.

The marker is evidence that the automated floors passed, not permission to
enable an autonomous response channel. Channel launch remains a separate,
human-controlled process.

The committed protection runbook restricts `release/*` and `v*` lifecycle
operations to the chosen release manager, requires reviewed changes on release
branches, and allows only the dedicated marker identity to create, move, or
delete `release-ai-quality/**` tags. Applying and verifying those controls is a
human admin step; the deployment verifier still fails closed when a marker is
missing, moved, or unreachable.

## Failure triage

1. Download the sanitized report and identify failed case IDs and metrics.
2. Check whether the failure is aggregate, per-case, model configuration,
   release-stack readiness, retrieval, or MCP tool use.
3. Reproduce with the same commit, model ID, sample SHA, prompt SHA, and
   temperature zero.
4. Fix the model, prompt, retrieval, or tool behavior and run the release gate
   again. Every run invalidates prior evidence first; only success republishes
   it.
5. Treat repeated scheduled failures as model or dependency drift even when no
   application code changed.
