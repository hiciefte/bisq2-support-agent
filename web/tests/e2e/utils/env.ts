/**
 * Environment configuration for E2E tests
 *
 * Centralizes environment variable access and URL normalization
 * to ensure consistent configuration across all test files.
 */

/**
 * Build a default API URL that matches the configured test host.
 */
const getDefaultApiUrl = (): string => {
  const fallbackHost = "localhost";
  const configuredWebBaseUrl = process.env.TEST_BASE_URL;

  if (!configuredWebBaseUrl) {
    return `http://${fallbackHost}:8000`;
  }

  try {
    const { hostname } = new URL(configuredWebBaseUrl);
    return `http://${hostname || fallbackHost}:8000`;
  } catch {
    return `http://${fallbackHost}:8000`;
  }
};

const DEFAULT_API_URL = getDefaultApiUrl();

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
  const defaultUrl = DEFAULT_API_URL;
  if (!url) return defaultUrl;

  // If URL starts with '/', prepend base origin
  if (url.startsWith('/')) {
    const baseOrigin = process.env.TEST_BASE_ORIGIN || DEFAULT_API_URL;
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
export const ADMIN_API_KEY = process.env.ADMIN_API_KEY || 'dev_admin_key_with_sufficient_length';

/**
 * Test timeout for container restart operations (in milliseconds)
 */
export const RESTART_TEST_TIMEOUT_MS = parseInt(
  process.env.RESTART_TEST_TIMEOUT_MS ?? '180000',
  10
);
