import { NextResponse } from 'next/server';

// Basic metrics for demonstration
const metrics = {
  requests_total: 0,
  errors_total: 0,
  response_time_ms: {
    avg: 0,
    p95: 0,
    p99: 0
  },
  active_users: 0
};

// Increment request counter
metrics.requests_total++;

export async function GET() {
  // Format metrics in Prometheus format
  const prometheusMetrics = [
    `# HELP requests_total Total number of requests`,
    `# TYPE requests_total counter`,
    `requests_total ${metrics.requests_total}`,

    `# HELP errors_total Total number of errors`,
    `# TYPE errors_total counter`,
    `errors_total ${metrics.errors_total}`,

    `# HELP response_time_ms Response time in milliseconds`,
    `# TYPE response_time_ms gauge`,
    `response_time_ms{quantile="avg"} ${metrics.response_time_ms.avg}`,
    `response_time_ms{quantile="p95"} ${metrics.response_time_ms.p95}`,
    `response_time_ms{quantile="p99"} ${metrics.response_time_ms.p99}`,

    `# HELP active_users Number of active users`,
    `# TYPE active_users gauge`,
    `active_users ${metrics.active_users}`
  ].join('\n');

  return new NextResponse(prometheusMetrics, {
    headers: {
      'Content-Type': 'text/plain'
    }
  });
}
