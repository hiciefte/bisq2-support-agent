# Public Bisq monitoring evidence

`get_bisq_network_status(area)` reads the public monitor for `tor`, `price_nodes`,
or `seed_nodes`. Its output helps staff investigate a current support question;
it does not certify service health or diagnose a user's device.

The tool is advertised by the existing local MCP endpoint. Astra discovers it
through the Responses adapter's existing `tools/list` and local `tools/call`
bridge. The existing MCP enablement setting also gates conversational access.
Explicit present network-status questions can use this tool when document
retrieval has no match, including streamed requests. Other no-document fallback
and safety behavior remains unchanged. A current-status answer requires a fresh
structured result from this specific tool. Missing, malformed, stale or partial
evidence produces an unconfirmed-status response for staff review; the returned
tool metadata retains available observations and coverage.
Each explicitly requested area requires a fresh report matching that same tool
call's arguments. Questions about the whole network remain unconfirmed because
none of the supported areas establishes whole-network coverage.

## What the metrics mean

Semantics were checked against upstream bisq-monitor commit
[`c7ab53ed`](https://github.com/bisq-network/bisq-monitor/tree/c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf).
This does not prove that the public monitor runs that exact commit.

| Area | Evidence | Limits |
| --- | --- | --- |
| Tor | Elapsed milliseconds when the monitor starts its own Tor process | The task does not emit a failure datapoint on its catch path. Missing data is unknown. It does not check every Tor connection. |
| Price nodes | Reported USD prices and request-error samples | Positive prices do not verify accuracy or all currencies. Error streams are sparse: no error sample does not prove no failures. |
| Seed nodes | Serial ping/pong RTT, with `-1` denoting a failed probe | Uses the monitor's configured legacy Bisq seed nodes. Failures can originate in the probe or network path. |

Primary definitions:

- [TorStartupTime.java](https://github.com/bisq-network/bisq-monitor/blob/c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf/src/main/java/bisq/monitor/monitor/tasks/TorStartupTime.java)
- [PriceNodeData.java](https://github.com/bisq-network/bisq-monitor/blob/c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf/src/main/java/bisq/monitor/monitor/tasks/PriceNodeData.java)
- [SeedNodeRoundTripTime.java](https://github.com/bisq-network/bisq-monitor/blob/c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf/src/main/java/bisq/monitor/monitor/tasks/SeedNodeRoundTripTime.java)
- [Metrics.java](https://github.com/bisq-network/bisq-monitor/blob/c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf/src/main/java/bisq/monitor/reporter/Metrics.java)
- [Example task intervals](https://github.com/bisq-network/bisq-monitor/blob/c7ab53edd9dd2c9a23fa9bd9fe09a45a4490dabf/src/main/resources/example_monitor.properties)

The upstream `bisq_v2` root is a metric namespace, not proof of Bisq 2 product
coverage. The price task source appends `.error` to a prefix already ending in a
dot, while the public dashboard references a single-dot error path. The fixed
price query includes both variants; absence of either is never a health claim.

## Limits and interpretation

Only a fixed public HTTPS Graphite endpoint and server-owned targets are used.
There is no arbitrary URL, PromQL, Graphite expression, user identifier or
credential argument. HTTP GET requests do not follow redirects or environment
proxies, use a five-second transport timeout and an eight-second overall deadline,
and are not retried. Each area uses a fifteen-minute window, at most 64 returned
series and 900 points per series, with a 256 KiB decoded response-body limit.
The cache lasts thirty seconds, and timestamps are evaluated again on cache hits.

The six-hundred-second freshness rule is an evidence-use policy, chosen to allow
two nominal five-minute intervals from the upstream example configuration. It is
not an SLA or a guarantee of the public monitor's configured cadence. Graphite
may aggregate datapoints into buckets, so positive samples do not prove the
absence of short failures. Counts refer to metric series, not unique nodes.

Results use `observations_available`, `failure_observed`, or `unknown`. A fresh
failure means the monitor recorded a failed probe, not a global outage. Missing
or stale coverage keeps the overall status unknown, even when some fresh
observations are available. Raw node identifiers and metric paths are omitted.
Every supported result includes coverage, timestamps, freshness and the public
dashboard link. `incident_reference` is null because no authoritative incident
feed is connected. Internal support-agent Prometheus/Grafana metrics are separate
and are not exposed by this tool.

## Verification

Tests cover fixed request construction, positive and negative observations,
stale/missing/partial data, HTTP/timeout/malformed/oversized responses, invalid
arguments without requests, caching, identifier removal, actual MCP dispatch,
Responses function-loop discovery and output, and the RAG zero-document and
streaming paths. The tests do not invoke a model or public network.
