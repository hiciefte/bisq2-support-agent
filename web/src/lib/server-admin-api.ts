import { headers } from "next/headers";
import { API_BASE_URL_SERVER } from "@/lib/config";

function resolveServerApiBase(requestHeaders: Headers): string {
  if (API_BASE_URL_SERVER.startsWith("http://") || API_BASE_URL_SERVER.startsWith("https://")) {
    return API_BASE_URL_SERVER;
  }

  const forwardedProto = requestHeaders.get("x-forwarded-proto");
  const protocol = forwardedProto && forwardedProto.length > 0 ? forwardedProto : "http";
  const forwardedHost = requestHeaders.get("x-forwarded-host");
  const host = forwardedHost && forwardedHost.length > 0
    ? forwardedHost
    : requestHeaders.get("host");

  if (!host) {
    return API_BASE_URL_SERVER;
  }

  if (API_BASE_URL_SERVER.startsWith("/")) {
    return `${protocol}://${host}${API_BASE_URL_SERVER}`;
  }

  return `${protocol}://${host}/${API_BASE_URL_SERVER}`;
}

export async function fetchAdminApiJson<T>(
  endpoint: string,
  init?: RequestInit,
): Promise<T | null> {
  try {
    const requestHeaders = await headers();
    const apiBase = resolveServerApiBase(requestHeaders);
    const cookie = requestHeaders.get("cookie");
    const target = endpoint.startsWith("http")
      ? endpoint
      : `${apiBase}${endpoint.startsWith("/") ? endpoint : `/${endpoint}`}`;

    const response = await fetch(target, {
      ...init,
      cache: "no-store",
      headers: {
        Accept: "application/json",
        ...(cookie ? { Cookie: cookie } : {}),
        ...(init?.headers ?? {}),
      },
    });
    if (!response.ok) {
      return null;
    }

    return (await response.json()) as T;
  } catch {
    return null;
  }
}
