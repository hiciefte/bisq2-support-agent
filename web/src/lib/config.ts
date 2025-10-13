/**
 * Shared configuration for API endpoints
 */

const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`;
