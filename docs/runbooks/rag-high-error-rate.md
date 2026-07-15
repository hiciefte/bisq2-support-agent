# RAG high error rate

## Impact

Answers may fail, time out, or enter human review more often than expected. Keep
Matrix and Bisq autonomous delivery disabled until the error rate and readiness
checks have recovered.

## Confirm

1. Check `/health/ready` through the normal internal service path and record the
   degraded component names.
2. Inspect the `RAGHighErrorRate` graph and compare it with request volume,
   stage latency, and dependency-probe alerts.
3. Review recent API logs for the first repeated exception class. Do not paste
   credentials, user messages, or session material into an incident record.

## Triage

1. If `vector_store` is unavailable, check Qdrant health and collection
   presence before rebuilding anything.
2. If an enabled Matrix or Bisq dependency is unavailable, keep that channel in
   review-only operation and restore the dependency independently.
3. If errors began with a release, compare the deployed build with the last
   known-good merge and use the documented rollback script if recovery cannot
   be completed safely.

## Recovery

The readiness endpoint must remain ready and the RAG error rate must stay below
the alert threshold for at least fifteen minutes. Confirm a reviewed web query
before closing the incident.
