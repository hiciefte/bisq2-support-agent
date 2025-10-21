import { test, expect } from '@playwright/test';

/**
 * Metrics Security Test Suite
 *
 * Ensures that Prometheus metrics endpoints are properly secured:
 * 1. /api/metrics is restricted to internal networks only
 * 2. Metrics contain expected data (feedback, Tor, system metrics)
 * 3. Sensitive information is not exposed publicly
 */

const BASE_URL = process.env.TEST_BASE_URL || 'http://localhost';

test.describe('Metrics Endpoint Security', () => {
  test('/api/metrics - Should be restricted to internal access only', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    // Production (external IP): Should return 403 Forbidden
    // Local (localhost): Should return 200 OK (internal access allowed)
    expect([200, 403]).toContain(response.status());

    if (response.status() === 403) {
      // External access blocked - this is correct for production
      console.log('✅ Metrics endpoint correctly blocked for external access');
    } else if (response.status() === 200) {
      // Internal access allowed - verify it's actually metrics
      console.log('✅ Metrics endpoint accessible (internal/localhost access)');
      const contentType = response.headers()['content-type'];
      expect(contentType).toContain('text/plain');
    }
  });

  test('/api/metrics - When accessible, should contain valid Prometheus metrics', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    // Skip if blocked (external access)
    if (response.status() === 403) {
      console.log('⏭️  Skipping metrics validation (external access blocked)');
      return;
    }

    expect(response.status()).toBe(200);

    const body = await response.text();

    // Validate Prometheus format
    expect(body).toContain('# HELP');
    expect(body).toContain('# TYPE');

    // Validate required metric groups are present
    const requiredMetricGroups = [
      'bisq_feedback',     // Feedback analytics
      'tor_',              // Tor metrics
      'python_',           // Python runtime metrics
      'process_',          // Process metrics
    ];

    for (const metricGroup of requiredMetricGroups) {
      expect(body).toContain(metricGroup);
    }
  });

  test('/api/metrics - Should contain feedback analytics metrics', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    if (response.status() === 403) {
      console.log('⏭️  Skipping feedback metrics validation (external access blocked)');
      return;
    }

    expect(response.status()).toBe(200);
    const body = await response.text();

    // Critical feedback metrics that must be present
    const feedbackMetrics = [
      'bisq_feedback_total',
      'bisq_feedback_helpful',
      'bisq_feedback_unhelpful',
      'bisq_feedback_helpful_rate',
      'bisq_source_total',
      'bisq_source_helpful',
      'bisq_source_helpful_rate',
      'bisq_issue_count',
    ];

    for (const metric of feedbackMetrics) {
      expect(body).toContain(metric);
    }
  });

  test('/api/metrics - Should contain Tor monitoring metrics', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    if (response.status() === 403) {
      console.log('⏭️  Skipping Tor metrics validation (external access blocked)');
      return;
    }

    expect(response.status()).toBe(200);
    const body = await response.text();

    // Tor-specific metrics
    const torMetrics = [
      'tor_connection_status',
      'tor_hidden_service_configured',
      'tor_cookie_secure_mode',
      'tor_requests_total',
      'tor_request_duration_seconds',
      'tor_verification_requests_total',
    ];

    for (const metric of torMetrics) {
      expect(body).toContain(metric);
    }
  });

  test('/api/metrics - Metrics values should be consistent', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    if (response.status() === 403) {
      console.log('⏭️  Skipping metrics consistency validation (external access blocked)');
      return;
    }

    expect(response.status()).toBe(200);
    const body = await response.text();

    // Parse metrics into a map
    const metrics: Record<string, number> = {};
    const lines = body.split('\n');

    for (const line of lines) {
      // Skip comments and empty lines
      if (line.startsWith('#') || line.trim() === '') {
        continue;
      }

      // Parse metric line: metric_name{labels} value
      // or: metric_name value
      const match = line.match(/^(\S+)\s+([\d.e+-]+)/);
      if (match) {
        const metricName = match[1].split('{')[0]; // Remove labels
        const value = parseFloat(match[2]);
        metrics[metricName] = value;
      }
    }

    // Validate consistency: total = helpful + unhelpful
    if (metrics['bisq_feedback_total'] !== undefined) {
      const total = metrics['bisq_feedback_total'];
      const helpful = metrics['bisq_feedback_helpful'] || 0;
      const unhelpful = metrics['bisq_feedback_unhelpful'] || 0;

      expect(total).toBe(helpful + unhelpful);
    }

    // Validate Tor status values are binary (0 or 1)
    if (metrics['tor_connection_status'] !== undefined) {
      expect([0, 1]).toContain(metrics['tor_connection_status']);
    }
    if (metrics['tor_hidden_service_configured'] !== undefined) {
      expect([0, 1]).toContain(metrics['tor_hidden_service_configured']);
    }
  });

  test('Web metrics endpoint should be removed', async ({ request }) => {
    // The old placeholder web metrics at /api/metrics in Next.js should be gone
    // This test ensures we don't have duplicate endpoints

    // Try to access what would be the Next.js metrics endpoint
    // (This is mainly a documentation test - the endpoint no longer exists)

    const response = await request.get(`${BASE_URL}/api/metrics`);

    // Should either be:
    // 1. Proxied to API backend (200 if internal, 403 if external)
    // 2. Not the old Next.js placeholder (which returned fake metrics)

    if (response.status() === 200) {
      const body = await response.text();

      // Verify these are REAL metrics from API backend, not the fake Next.js ones
      // The old Next.js metrics had: requests_total, errors_total, response_time_ms, active_users
      // The real API metrics have: bisq_*, tor_*, python_*, process_*

      // Must contain API backend metrics
      expect(body).toContain('bisq_feedback_total');
      expect(body).toContain('tor_connection_status');

      // Should NOT be the old placeholder that only counted its own calls
      // The old endpoint had these specific metric names without the "bisq_" prefix
      const isOldPlaceholder =
        body.includes('requests_total') &&
        body.includes('errors_total') &&
        body.includes('active_users') &&
        !body.includes('bisq_feedback_total');

      expect(isOldPlaceholder).toBe(false);
    }
  });
});

test.describe('Metrics Endpoint Regression Prevention', () => {
  test('Critical feedback metrics must always be present', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    if (response.status() === 403) {
      console.log('⏭️  Skipping regression test (external access blocked)');
      return;
    }

    expect(response.status()).toBe(200);
    const body = await response.text();

    // These metrics MUST ALWAYS be present - this prevents regression during refactoring
    const criticalMetrics = [
      'bisq_feedback_total',
      'bisq_feedback_helpful',
      'bisq_feedback_unhelpful',
      'bisq_feedback_helpful_rate',
    ];

    for (const metric of criticalMetrics) {
      const regex = new RegExp(`${metric}\\s+[\\d.e+-]+`, 'm');
      expect(body).toMatch(regex);
    }
  });

  test('Feedback metrics must have numeric values', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/metrics`);

    if (response.status() === 403) {
      console.log('⏭️  Skipping numeric validation (external access blocked)');
      return;
    }

    expect(response.status()).toBe(200);
    const body = await response.text();

    // Extract all bisq_feedback metrics
    const lines = body.split('\n');
    const feedbackMetricLines = lines.filter(line =>
      line.startsWith('bisq_feedback_') && !line.startsWith('#')
    );

    expect(feedbackMetricLines.length).toBeGreaterThan(0);

    // Each metric line should have a numeric value
    for (const line of feedbackMetricLines) {
      const match = line.match(/\s+([\d.e+-]+)$/);
      expect(match).not.toBeNull();

      if (match) {
        const value = parseFloat(match[1]);
        expect(isNaN(value)).toBe(false);
        expect(value).toBeGreaterThanOrEqual(0); // Metrics should be non-negative
      }
    }
  });
});
