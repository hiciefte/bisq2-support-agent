# RAG high latency

## Impact

Users may wait too long for answers, and upstream channel timeouts may route
otherwise valid responses to staff review.

## Confirm

1. Check `/health/ready` and the critical-service probe alerts.
2. Break down `rag_stage_latency_seconds` by stage to distinguish retrieval,
   reranking, and generation latency.
3. Compare latency with CPU, memory, throttling, request volume, and provider
   error metrics.

## Triage

1. For retrieval latency, inspect Qdrant readiness and resource pressure.
2. For generation latency, check provider availability and rate limiting while
   preserving the configured safety and relevance floors.
3. Reduce incoming autonomous traffic through the channel controls; do not
   bypass review routing or extend timeouts without evidence.
4. Roll back the latest release when the regression is release-bound and cannot
   be corrected within the incident window.

## Recovery

The P95 stage latency must remain below the alert threshold for at least fifteen
minutes, with `/health/ready` returning ready and no corresponding error-rate
alert firing.
