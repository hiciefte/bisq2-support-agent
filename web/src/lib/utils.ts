import { clsx, type ClassValue } from "clsx"
import { sha256 } from "@noble/hashes/sha256"
import { bytesToHex } from "@noble/hashes/utils"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Generate SHA-256 hash suffix using @noble/hashes.
 * This provides consistent hashing in both secure (HTTPS) and non-secure (HTTP) contexts.
 * The @noble/hashes library is a pure-JS implementation that works everywhere.
 *
 * @param input - The string to hash
 * @returns First 8 characters of the SHA-256 hex digest
 */
function generateHashSuffix(input: string): string {
  const encoder = new TextEncoder();
  const data = encoder.encode(input);
  const hash = sha256(data);
  return bytesToHex(hash).slice(0, 8);
}

/**
 * Generate FAQ slug from question and ID.
 * Mirrors the backend slug generation algorithm in api/app/services/faq/slug_manager.py
 *
 * @param question - The FAQ question text
 * @param faqId - The FAQ ID (string or number)
 * @returns URL-safe slug string
 */
export function generateFaqSlug(question: string, faqId: string | number): string {
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

  // Generate 8-char hash suffix from FAQ ID
  const hashSuffix = generateHashSuffix(String(faqId));

  // Handle empty or reserved slugs
  if (!slug || RESERVED_SLUGS.has(slug)) {
    return `faq-${hashSuffix}`;
  }

  return `${slug}-${hashSuffix}`;
}
