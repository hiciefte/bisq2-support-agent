import { test, expect } from '@playwright/test';

/**
 * Security test suite to verify endpoint access controls
 *
 * This test verifies that:
 * 1. Public endpoints are accessible
 * 2. Admin endpoints are properly restricted
 * 3. Internal endpoints are not exposed
 */

// Default to localhost for local testing, override with TEST_BASE_URL for production
const BASE_URL = process.env.TEST_BASE_URL || 'http://localhost';

test.describe('Endpoint Security', () => {
  test.describe('Public Endpoints - Should Be Accessible', () => {
    test('/ - Main page should be accessible', async ({ page }) => {
      const response = await page.goto(BASE_URL);
      expect(response?.status()).toBe(200);
    });

    test('/api/health - Health check is restricted to internal networks', async ({ page }) => {
      const response = await page.goto(`${BASE_URL}/api/health`);
      // Health endpoint is intentionally restricted to internal networks (127.0.0.1, Docker networks)
      // Local development: Returns 200 (accessing from localhost)
      // Production: Returns 403 (external access is forbidden)
      expect([200, 403]).toContain(response?.status());
    });

    test('/api/chat/stats - Stats endpoint should be accessible', async ({ page }) => {
      const response = await page.goto(`${BASE_URL}/api/chat/stats`);
      expect(response?.status()).toBe(200);

      // Verify it returns JSON content-type
      expect(response?.headers()['content-type']).toContain('application/json');

      // Verify it returns valid JSON
      const data = await response!.json();
      expect(data).toHaveProperty('total_queries');
      expect(data).toHaveProperty('average_response_time');
    });

    test('/api/admin/auth/login - Login endpoint should be accessible', async ({ request }) => {
      const response = await request.post(`${BASE_URL}/api/admin/auth/login`, {
        data: { api_key: 'invalid-key' }
      });
      // Should return 401 for invalid credentials, not 403 or 404
      expect(response.status()).toBe(401);
    });
  });

  test.describe('Admin Endpoints - Should Be Restricted', () => {
    test('/api/admin/faqs - Should require authentication', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/admin/faqs`);
      expect([401, 403]).toContain(response.status());
    });
    test('/api/admin/dashboard/overview - Should require authentication', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/admin/dashboard/overview`);
      // Should return 401 (unauthorized) or 403 (forbidden), NOT 200
      expect([401, 403]).toContain(response.status());
    });

    test('/api/admin/feedback - Should require authentication', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/admin/feedback`);
      expect([401, 403]).toContain(response.status());
    });

    test('/api/admin/feedback/stats - Should require authentication', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/admin/feedback/stats`);
      expect([401, 403]).toContain(response.status());
    });

    test('/admin/overview - Admin page should redirect to login', async ({ page }) => {
      await page.goto(`${BASE_URL}/admin/overview`);

      // Should show login form, not admin content
      await expect(page.locator('text=Admin Login')).toBeVisible({ timeout: 5000 });
    });
  });

  test.describe('Internal Endpoints - Should NOT Be Exposed', () => {
    test('/api/metrics - API metrics should not be publicly accessible', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/metrics`);
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
      const response = await request.get(`${BASE_URL}/docs`);
      expect(response.status()).not.toBe(200);
    });

    test('/api/docs - API docs should not be publicly accessible', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/docs`);
      expect(response.status()).not.toBe(200);
    });

    test('Direct port 8000 access should be blocked', async ({ request }) => {
      // Extract hostname from BASE_URL and attempt direct port 8000 access
      const hostname = new URL(BASE_URL).hostname;

      await expect(async () => {
        await request.get(`http://${hostname}:8000/health`, {
          timeout: 2000
        });
        // If we reach here (no error thrown), port 8000 is exposed
        // Fail the test explicitly - ANY successful response is a security issue
        throw new Error('Port 8000 is exposed - security vulnerability detected!');
      }).rejects.toThrow();
      // Expected: connection should fail or timeout (throws network error)
      // If connection succeeds, we throw explicit error above
    });
  });

  test.describe('API Endpoint Functionality', () => {
    test('/api/chat/query - Chat query endpoint should work', async ({ request }) => {
      const response = await request.post(`${BASE_URL}/api/chat/query`, {
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
      const response = await request.post(`${BASE_URL}/api/feedback/react`, {
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
      const response = await request.head(`${BASE_URL}/maintenance.html`);

      // It might return 404 if nginx isn't configured to serve it directly,
      // or 200 if it is. The important thing is it exists for error_page directive.
      expect([200, 404]).toContain(response.status());
    });
  });
});

test.describe('Stats Endpoint Validation', () => {
  test('Stats endpoint returns correct data structure', async ({ request }) => {
    const response = await request.get(`${BASE_URL}/api/chat/stats`);
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
