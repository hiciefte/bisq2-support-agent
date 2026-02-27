/**
 * Shared configuration for API endpoints
 *
 * SECURITY: All API calls (client-side AND server-side) route through nginx to ensure:
 * - Rate limiting is enforced (prevents DoS attacks)
 * - Security headers are applied (CSP, X-Frame-Options, etc.)
 * - Centralized access logging for security monitoring
 *
 * Configuration:
 * - Production: Uses '/api' (relative URL) proxied by nginx
 * - Local dev: Uses 'http://localhost:8000' for direct API access (dev only)
 * - SSR in Docker: Uses 'http://nginx:80' to route through nginx (NOT direct to api:8000)
 */

// Client-side API URL (used by browser)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api';

// Server-side API URL (used by SSR in Docker containers)
// SECURITY: Routes through nginx for rate limiting and security headers
// Falls back to client URL for non-Docker environments
export const API_BASE_URL_SERVER =
  process.env.API_URL_INTERNAL ||
  process.env.NEXT_PUBLIC_API_URL ||
  '/api';

/**
 * Get the appropriate API URL based on execution context
 * Use this for fetch calls that may run on server or client
 */
export function getApiBaseUrl(): string {
  // Check if running on server (Node.js environment)
  if (typeof window === 'undefined') {
    return API_BASE_URL_SERVER;
  }
  return API_BASE_URL;
}

/**
 * Build an API URL that always targets exactly one `/api` prefix.
 *
 * Supports both base URL styles:
 * - Base already includes `/api` (e.g. "/api", "http://nginx:80/api")
 * - Base points to host root (e.g. "http://localhost:8000")
 */
export function buildApiUrl(pathAfterApi: string, baseUrl: string = getApiBaseUrl()): string {
  const trimmedBase = baseUrl.replace(/\/+$/, '');
  const normalizedPath = pathAfterApi.startsWith('/') ? pathAfterApi : `/${pathAfterApi}`;
  const apiPath = normalizedPath.startsWith('/api/') || normalizedPath === '/api'
    ? normalizedPath
    : `/api${normalizedPath}`;

  if (!trimmedBase) {
    return apiPath;
  }

  if (trimmedBase.endsWith('/api') && apiPath.startsWith('/api/')) {
    return `${trimmedBase}${apiPath.slice(4)}`;
  }

  if (trimmedBase.endsWith('/api') && apiPath === '/api') {
    return trimmedBase;
  }

  return `${trimmedBase}${apiPath}`;
}

export function isAbsoluteHttpUrl(url: string): boolean {
  return /^https?:\/\//i.test(url);
}
