/**
 * Shared configuration for API endpoints
 *
 * In production: Uses '/api' (relative URL) which is proxied by nginx
 * In local development: Set NEXT_PUBLIC_API_URL=http://localhost:8000 for direct API access
 */

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || '/api';
