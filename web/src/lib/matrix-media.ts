/**
 * Helpers for converting Matrix `mxc://` URIs into URLs the admin UI can
 * render. The actual download is proxied by the FastAPI backend so the
 * Matrix access token never reaches the browser.
 */

import { API_BASE_URL } from "@/lib/config";

const MXC_PREFIX = "mxc://";

export interface ParsedMxc {
  serverName: string;
  mediaId: string;
}

export function parseMxcUri(uri: string | null | undefined): ParsedMxc | null {
  if (!uri || typeof uri !== "string") {
    return null;
  }
  if (!uri.startsWith(MXC_PREFIX)) {
    return null;
  }
  const remainder = uri.slice(MXC_PREFIX.length);
  const slashIndex = remainder.indexOf("/");
  if (slashIndex <= 0 || slashIndex === remainder.length - 1) {
    return null;
  }
  const serverName = remainder.slice(0, slashIndex);
  const mediaId = remainder.slice(slashIndex + 1);
  if (mediaId.includes("/")) {
    return null;
  }
  return { serverName, mediaId };
}

/**
 * Convert a Matrix `mxc://` URI into a backend proxy URL the admin UI
 * can render via `<img src=…>`.
 *
 * Only `mxc://` is accepted. Raw `https?://` URLs are intentionally
 * rejected so untrusted third parties cannot track admin viewers.
 */
export function resolveAvatarUrl(url: string | null | undefined): string | null {
  const parsed = parseMxcUri(url);
  if (!parsed) {
    return null;
  }
  return `${API_BASE_URL}/admin/security/matrix-media/${encodeURIComponent(parsed.serverName)}/${encodeURIComponent(parsed.mediaId)}`;
}
