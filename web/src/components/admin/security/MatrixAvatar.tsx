"use client";

import { useEffect, useState } from "react";
import { resolveAvatarUrl } from "@/lib/matrix-media";
import { cn } from "@/lib/utils";

export interface MatrixAvatarProps {
  /** mxc:// URI, https URL, or null/undefined when no avatar is known. */
  avatarUrl: string | null | undefined;
  /** Display name used to compute the fallback initials and the alt text. */
  displayName: string | null | undefined;
  /** Tailwind size classes; defaults to a 16x16 (h-16 w-16) circle. */
  className?: string;
  /** Optional override for fallback styling (e.g. red ring for suspect). */
  fallbackClassName?: string;
}

function computeInitials(name: string | null | undefined): string {
  if (!name) {
    return "?";
  }
  const trimmed = name.trim();
  if (!trimmed) {
    return "?";
  }
  const parts = trimmed.split(/\s+/).filter(Boolean);
  if (parts.length === 1) {
    return parts[0]!.slice(0, 2).toUpperCase();
  }
  return (parts[0]![0]! + parts[parts.length - 1]![0]!).toUpperCase();
}

/**
 * Avatar that renders Matrix `mxc://` URIs via the backend media proxy.
 *
 * Uses a plain `<img>` so the element exists in the DOM immediately
 * (predictable for tests) and falls back to initials on load errors or
 * when no URL is supplied.
 */
export function MatrixAvatar({
  avatarUrl,
  displayName,
  className,
  fallbackClassName,
}: MatrixAvatarProps) {
  const resolved = resolveAvatarUrl(avatarUrl);
  const [errored, setErrored] = useState(false);
  useEffect(() => {
    setErrored(false);
  }, [resolved]);
  const initials = computeInitials(displayName);
  const altName = displayName?.trim() || "Unknown user";
  const showImage = Boolean(resolved) && !errored;

  return (
    <div
      className={cn(
        "relative flex h-16 w-16 shrink-0 items-center justify-center overflow-hidden rounded-full bg-muted ring-1 ring-border/60",
        className,
      )}
      data-testid="matrix-avatar"
    >
      {showImage ? (
        // eslint-disable-next-line @next/next/no-img-element -- backend-proxied auth-cookie route is incompatible with next/image remote patterns
        <img
          src={resolved!}
          alt={`${altName} avatar`}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={() => setErrored(true)}
        />
      ) : (
        <span
          className={cn(
            "select-none text-base font-semibold tracking-wide text-foreground/80",
            fallbackClassName,
          )}
          aria-label={`${altName} initials`}
        >
          {initials}
        </span>
      )}
    </div>
  );
}
