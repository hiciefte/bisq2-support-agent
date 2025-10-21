/**
 * Environment configuration for E2E tests
 *
 * Centralizes environment variable access and URL normalization
 * to ensure consistent configuration across all test files.
 */

/**
 * Normalize API URL to ensure it's absolute
 *
 * Handles cases where NEXT_PUBLIC_API_URL might be:
 * - Relative path (e.g., '/')
 * - Absolute URL (e.g., 'http://localhost:8000')
 * - Undefined
 *
 * @param url - The URL to normalize
 * @returns Absolute URL string
 */
export const normalizeApiUrl = (url: string | undefined): string => {
  const defaultUrl = 'http://localhost:8000';
  if (!url) return defaultUrl;

  // If URL starts with '/', prepend base origin
  if (url.startsWith('/')) {
    const baseOrigin = process.env.TEST_BASE_ORIGIN || 'http://localhost:8000';
    return `${baseOrigin}${url}`;
  }

  // If it's already absolute (starts with http:// or https://), return as-is
  if (url.startsWith('http://') || url.startsWith('https://')) {
    return url;
  }

  // Otherwise, default to localhost
  return defaultUrl;
};

/**
 * API base URL - normalized to ensure absolute URL
 */
export const API_BASE_URL = normalizeApiUrl(process.env.NEXT_PUBLIC_API_URL);

/**
 * Web application base URL
 */
export const WEB_BASE_URL = process.env.TEST_BASE_URL || 'http://localhost:3000';

/**
 * Admin API key for authentication
 */
export const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'dev_admin_key';

/**
 * Test timeout for container restart operations (in milliseconds)
 */
export const RESTART_TEST_TIMEOUT_MS = parseInt(
  process.env.RESTART_TEST_TIMEOUT_MS ?? '180000',
  10
);
