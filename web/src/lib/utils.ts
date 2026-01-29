import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Generate FAQ slug from question and ID.
 * Mirrors the backend slug generation algorithm in api/app/services/faq/slug_manager.py
 *
 * @param question - The FAQ question text
 * @param faqId - The FAQ ID (string or number)
 * @returns URL-safe slug string
 */
export async function generateFaqSlug(question: string, faqId: string | number): Promise<string> {
  const MAX_SLUG_LENGTH = 60;
  const RESERVED_SLUGS = new Set([
    "admin", "api", "static", "assets", "health", "metrics",
    "login", "logout", "search", "new", "edit", "delete",
    "create", "update", "categories", "null", "undefined", "true", "false"
  ]);

  // Normalize unicode to ASCII (simplified - remove accents/diacritics)
  let slug = question
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "") // Remove diacritics
    .replace(/[^\x00-\x7F]/g, "");   // Remove non-ASCII

  // Lowercase and strict character allowlist
  slug = slug.toLowerCase();
  slug = slug.replace(/[^a-z0-9\s-]/g, "");
  slug = slug.replace(/\s+/g, "-");
  slug = slug.replace(/-+/g, "-");   // Collapse consecutive hyphens
  slug = slug.replace(/^-|-$/g, ""); // Trim leading/trailing hyphens

  // Truncate at word boundary (leave room for hash suffix: 8 chars + 1 hyphen)
  if (slug.length > MAX_SLUG_LENGTH - 9) {
    slug = slug.slice(0, MAX_SLUG_LENGTH - 9);
    const lastHyphen = slug.lastIndexOf("-");
    if (lastHyphen > 0) {
      slug = slug.slice(0, lastHyphen);
    }
  }

  // Generate 8-char SHA256 hash suffix from FAQ ID
  const idString = String(faqId);
  const encoder = new TextEncoder();
  const data = encoder.encode(idString);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  const hashSuffix = hashArray.map(b => b.toString(16).padStart(2, "0")).join("").slice(0, 8);

  // Handle empty or reserved slugs
  if (!slug || RESERVED_SLUGS.has(slug)) {
    return `faq-${hashSuffix}`;
  }

  return `${slug}-${hashSuffix}`;
}
