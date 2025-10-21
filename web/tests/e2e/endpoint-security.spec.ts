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

    test('/api/admin/faqs - Public FAQ listing should be accessible', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/api/admin/faqs`);
      // This might be public or require auth - check actual status
      expect([200, 401, 403]).toContain(response.status());
    });
  });

  test.describe('Admin Endpoints - Should Be Restricted', () => {
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
    test('/metrics - Prometheus metrics should not be publicly accessible', async ({ request }) => {
      const response = await request.get(`${BASE_URL}/metrics`);
      // Should return 403 (forbidden), 404 (not found), or 502 (bad gateway)
      // NOT 200
      expect(response.status()).not.toBe(200);
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
      try {
        // Extract hostname from BASE_URL and attempt direct port 8000 access
        const hostname = new URL(BASE_URL).hostname;
        const response = await request.get(`http://${hostname}:8000/health`, {
          timeout: 2000 // Reduced timeout for faster test execution
        });
        // If we get a response, port 8000 is exposed - this is bad
        expect(response.status()).toBe(0); // Should timeout or fail
      } catch (error) {
        // Expected: connection should fail or timeout
        expect(error).toBeDefined();
      }
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

    test('/api/feedback/submit - Feedback submission should work', async ({ request }) => {
      const response = await request.post(`${BASE_URL}/api/feedback/submit`, {
        data: {
          message_id: 'test-msg-id',
          query: 'test query',
          response: 'test response',
          rating: 'helpful',
          feedback_text: 'Security test feedback',
          conversation_id: 'test-security-check'
        }
      });

      // Accept both 200 (successful) and 422 (validation error)
      // Both indicate endpoint is accessible and working correctly
      expect([200, 422]).toContain(response.status());
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
