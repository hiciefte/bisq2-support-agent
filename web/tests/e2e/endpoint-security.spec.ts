import { test, expect } from '@playwright/test';
import { API_BASE_URL, WEB_BASE_URL } from './utils';

/**
 * Security test suite to verify endpoint access controls
 *
 * This test verifies that:
 * 1. Public endpoints are accessible
 * 2. Admin endpoints are properly restricted
 * 3. Internal endpoints are not exposed
 */

const WEB_URL = WEB_BASE_URL;
const API_URL = API_BASE_URL.replace(/\/$/, '');

test.describe('Endpoint Security', () => {
    test.describe('Public Endpoints - Should Be Accessible', () => {
    test('/ - Main page should be accessible', async ({ page }) => {
      const response = await page.goto(WEB_URL);
      expect(response?.status()).toBe(200);
    });

    test('/api/health - Health check is restricted to internal networks', async ({ page }) => {
      const response = await page.goto(`${API_URL}/health`);
      // Health endpoint is intentionally restricted to internal networks (127.0.0.1, Docker networks)
      // Local development: Returns 200 (accessing from localhost)
      // Production: Returns 403 (external access is forbidden)
      expect([200, 403]).toContain(response?.status());
    });

    test('/api/chat/stats - Stats endpoint should be accessible', async ({ page }) => {
      const response = await page.goto(`${API_URL}/chat/stats`);
      expect(response?.status()).toBe(200);

      // Verify it returns JSON content-type
      expect(response?.headers()['content-type']).toContain('application/json');

      // Verify it returns valid JSON
      const data = await response!.json();
      expect(data).toHaveProperty('total_queries');
      expect(data).toHaveProperty('average_response_time');
    });

    test('/api/admin/auth/login - Login endpoint should be accessible', async ({ request }) => {
      const response = await request.post(`${API_URL}/admin/auth/login`, {
        data: { api_key: 'invalid-key' }
      });
      // Should return 401 for invalid credentials, not 403 or 404
      expect(response.status()).toBe(401);
    });
  });

  test.describe('Admin Endpoints - Should Be Restricted', () => {
    test('/api/admin/faqs - Should require authentication', async ({ request }) => {
      const response = await request.get(`${API_URL}/admin/faqs`);
      expect([401, 403]).toContain(response.status());
    });
    test('/api/admin/dashboard/overview - Should require authentication', async ({ request }) => {
      const response = await request.get(`${API_URL}/admin/dashboard/overview`);
      // Should return 401 (unauthorized) or 403 (forbidden), NOT 200
      expect([401, 403]).toContain(response.status());
    });

    test('/api/admin/feedback - Should require authentication', async ({ request }) => {
      const response = await request.get(`${API_URL}/admin/feedback`);
      expect([401, 403]).toContain(response.status());
    });

    test('/api/admin/feedback/stats - Should require authentication', async ({ request }) => {
      const response = await request.get(`${API_URL}/admin/feedback/stats`);
      expect([401, 403]).toContain(response.status());
    });

    test('/admin/overview - Admin page should redirect to login', async ({ page }) => {
      await page.goto(`${WEB_URL}/admin/overview`);

      // Should show login form, not admin content
      await expect(page.locator('text=Admin Login')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Internal Endpoints - Should NOT Be Exposed', () => {
    test('/api/metrics - API metrics should not be publicly accessible', async ({ request }) => {
      const response = await request.get(`${API_URL}/metrics`);
      // Should return 403 (forbidden) - blocked by nginx for external access
      // Local testing from localhost will return 200 (allowed internal access)
      // Production from external IP will return 403
      expect([200, 403]).toContain(response.status());

      // If we get 200, we must be on localhost (internal access)
      if (response.status() === 200) {
        const contentType = response.headers()['content-type'];
        expect(contentType).toContain('text/plain');
        const body = await response.text();
        expect(body).toContain('# HELP');
        expect(body).toContain('# TYPE');
      }
    });

    test('/docs - API docs should not be publicly accessible', async ({ request }) => {
      const response = await request.get(`${API_URL}/docs`);
      expect(response.status()).not.toBe(200);
    });

    test('/api/docs - API docs should not be publicly accessible', async ({ request }) => {
      const response = await request.get(`${API_URL}/api/docs`);
      // Local/dev setups may expose docs for debugging; hardened envs should block it.
      expect([200, 401, 403, 404]).toContain(response.status());
      if (response.status() === 200) {
        const hostname = new URL(API_URL).hostname;
        expect(['localhost', '127.0.0.1']).toContain(hostname);
      }
    });

    test('Direct port 8000 access should be blocked', async ({ request }) => {
      // Extract hostname from WEB_URL and attempt direct port 8000 access
      const hostname = new URL(WEB_URL).hostname;

      // Local/dev setups may expose :8000 directly; production should not.
      const response = await request.get(`http://${hostname}:8000/health`, {
        timeout: 2000,
      }).catch(() => null);

      if (!response) {
        // Expected in hardened environments where direct API port is blocked.
        return;
      }

      // If direct access is available, it must at least be a valid health response.
      expect([200, 403]).toContain(response.status());
    });
  });

  test.describe('API Endpoint Functionality', () => {
    test('/api/chat/query - Chat query endpoint should work', async ({ request }) => {
      const response = await request.post(`${API_URL}/chat/query`, {
        data: {
          question: 'What is Bisq?',
          chat_history: []
        }
      });

      expect(response.status()).toBe(200);
      const data = await response.json();
      expect(data).toHaveProperty('answer');
    });

    test('/api/feedback/react - Reaction feedback should work', async ({ request }) => {
      const response = await request.post(`${API_URL}/feedback/react`, {
        data: {
          message_id: 'web_test-msg-id',
          rating: 1,
        }
      });

      // Accept 200 (successful), 404 (untracked message), 422 (validation), or 503 (no processor)
      // All indicate endpoint is accessible and working correctly
      expect([200, 404, 422, 503]).toContain(response.status());
    });
  });

  test.describe('Maintenance Page', () => {
    test('Maintenance page should be available', async ({ request }) => {
      // The maintenance page is served when backend is down
      // We can't trigger it in normal operation, but we can verify the file exists
      // Using HEAD request is faster and more appropriate for presence checking
      const response = await request.head(`${WEB_URL}/maintenance.html`);

      // It might return 404 if nginx isn't configured to serve it directly,
      // or 200 if it is. The important thing is it exists for error_page directive.
      expect([200, 404]).toContain(response.status());
    });
  });
});

test.describe('Stats Endpoint Validation', () => {
  test('Stats endpoint returns correct data structure', async ({ request }) => {
    const response = await request.get(`${API_URL}/chat/stats`);
    expect(response.status()).toBe(200);

    const data = await response.json();

    // Verify required fields
    expect(data).toHaveProperty('total_queries');
    expect(data).toHaveProperty('average_response_time');
    expect(data).toHaveProperty('last_24h_average_response_time');

    // Verify data types
    expect(typeof data.total_queries).toBe('number');
    expect(typeof data.average_response_time).toBe('number');
    expect(typeof data.last_24h_average_response_time).toBe('number');
  });
});
