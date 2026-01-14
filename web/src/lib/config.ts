/**
 * Shared configuration for API endpoints
 *
 * In production: Uses '/api' (relative URL) which is proxied by nginx
 * In local development: Set NEXT_PUBLIC_API_URL=http://localhost:8000 for direct API access
 *
 * For server-side rendering in Docker:
 * - Server components need API_URL_INTERNAL (Docker network: http://api:8000)
 * - Client components use NEXT_PUBLIC_API_URL (browser: http://localhost:8000)
 */

// Client-side API URL (used by browser)
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api';

// Server-side API URL (used by SSR in Docker containers)
// Falls back to NEXT_PUBLIC_API_URL if not set (for non-Docker environments)
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
