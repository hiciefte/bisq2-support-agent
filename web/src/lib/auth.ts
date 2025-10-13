/**
 * Authentication utilities for admin interface
 */

import { API_BASE_URL } from './config';

export interface LoginResponse {
  message: string;
  authenticated: boolean;
}

export interface LogoutResponse {
  message: string;
  authenticated: boolean;
}

// Session timeout callback - will be set by SecureAuth component
let sessionTimeoutCallback: (() => void) | null = null;

/**
 * Register callback to handle session timeout
 * Returns an unsubscribe function to clean up the callback
 */
export function registerSessionTimeoutCallback(callback: () => void): () => void {
  sessionTimeoutCallback = callback;

  // Return unsubscribe function
  return () => {
    sessionTimeoutCallback = null;
  };
}

/**
 * Handle session timeout by calling registered callback
 */
function handleSessionTimeout(): void {
  if (sessionTimeoutCallback) {
    sessionTimeoutCallback();
  }
}

/**
 * Login with API key using secure cookie-based authentication
 */
export async function loginWithApiKey(apiKey: string): Promise<LoginResponse> {
  const response = await fetch(`${API_BASE_URL}/admin/auth/login`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    credentials: 'include', // Important: include cookies in requests
    body: JSON.stringify({
      api_key: apiKey,
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Login failed' }));
    throw new Error(error.detail || 'Login failed');
  }

  return await response.json();
}

/**
 * Logout and clear authentication cookie
 */
export async function logout(): Promise<LogoutResponse> {
  const response = await fetch(`${API_BASE_URL}/admin/auth/logout`, {
    method: 'POST',
    credentials: 'include', // Important: include cookies in requests
  });

  if (!response.ok) {
    // Even if logout fails on server, consider it successful client-side
    console.warn('Logout request failed, but continuing with client-side logout');
  }

  try {
    return await response.json();
  } catch {
    return { message: 'Logout successful', authenticated: false };
  }
}

/**
 * Make authenticated API request with automatic cookie handling and session timeout detection
 */
export async function makeAuthenticatedRequest(
  endpoint: string,
  options: RequestInit = {}
): Promise<Response> {
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;

  const response = await fetch(url, {
    ...options,
    credentials: 'include', // Important: include cookies in requests
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  // Detect session timeout (401 Unauthorized)
  if (response.status === 401) {
    console.warn('Session expired (401 Unauthorized), triggering logout');
    handleSessionTimeout();
  }

  return response;
}

/**
 * Check if user is authenticated by making a test request
 * Since we can't access HTTP-only cookies from JS, we need to check with server
 */
export async function checkAuthStatus(): Promise<boolean> {
  try {
    const response = await makeAuthenticatedRequest('/admin/dashboard/overview');
    return response.ok;
  } catch {
    return false;
  }
}
