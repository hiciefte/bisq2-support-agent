import type { Source } from "@/components/chat/types/chat.types";

const FAQ_REF_PREFIX = "faq:";
const WIKI_REF_PREFIX = "wiki:";
const FAQ_SLUG_PATTERN = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;
const COMPACT_SOURCE_REF_PATTERN =
  /(^|[\s(,;])((?:faq:[a-z0-9][a-z0-9-]*[a-z0-9]|wiki:[A-Za-z0-9][A-Za-z0-9_-]*))(?=$|[\s),.;\]])/g;

export function linkifySourceRefsInMarkdown(
  markdown: string,
  sourceRefLinks: Record<string, string>,
  sources: Source[] | null = null,
): string {
  const links = {
    ...sourceRefLinksFromSources(sources),
    ...sourceRefLinks,
  };

  const withBacktickedRefs = markdown.replace(
    /`((?:faq|wiki):[^`\n]+?)`/g,
    (match, rawRef: string) => {
      const ref = rawRef.trim();
      const href = resolveSourceRefHref(ref, links);
      return href ? markdownLink(ref, href) : match;
    },
  );

  return withBacktickedRefs.replace(
    COMPACT_SOURCE_REF_PATTERN,
    (match, prefix: string, ref: string) => {
      const href = resolveSourceRefHref(ref, links);
      return href ? `${prefix}${markdownLink(ref, href)}` : match;
    },
  );
}

function sourceRefLinksFromSources(
  sources: Source[] | null | undefined,
): Record<string, string> {
  const links: Record<string, string> = {};

  for (const source of sources ?? []) {
    if (source.type === "faq") {
      const slug = source.slug || faqSlugFromUrl(source.url);
      if (!slug || !isValidFaqSlug(slug)) continue;
      const href = `/faq/${encodeURIComponent(slug)}`;
      if (source.id) links[`${FAQ_REF_PREFIX}${source.id}`] = href;
      if (source.faq_id) links[`${FAQ_REF_PREFIX}${source.faq_id}`] = href;
      links[`${FAQ_REF_PREFIX}${slug}`] = href;
    }

    if (source.type === "wiki" && source.title) {
      const href = safeSourceHref(source.url) || wikiUrlForTitle(source.title);
      if (href) links[`${WIKI_REF_PREFIX}${source.title}`] = href;
    }
  }

  return links;
}

function resolveSourceRefHref(
  ref: string,
  sourceRefLinks: Record<string, string>,
): string | null {
  const resolved = safeSourceHref(sourceRefLinks[ref]);
  if (resolved) return resolved;

  if (ref.startsWith(FAQ_REF_PREFIX)) {
    const value = ref.slice(FAQ_REF_PREFIX.length).trim();
    if (!/^\d+$/.test(value) && isValidFaqSlug(value)) {
      return `/faq/${encodeURIComponent(value)}`;
    }
  }

  if (ref.startsWith(WIKI_REF_PREFIX)) {
    return wikiUrlForTitle(ref.slice(WIKI_REF_PREFIX.length).trim());
  }

  return null;
}

function markdownLink(label: string, href: string): string {
  return `[${escapeMarkdownLinkLabel(label)}](${escapeMarkdownHref(href)})`;
}

function escapeMarkdownLinkLabel(label: string): string {
  return label.replace(/([\\[\]])/g, "\\$1");
}

function escapeMarkdownHref(href: string): string {
  return href.replace(/\s/g, "%20").replace(/\(/g, "%28").replace(/\)/g, "%29");
}

function faqSlugFromUrl(url: string | undefined): string | null {
  const value = url?.trim();
  if (!value) return null;
  let path = value;
  if (value.startsWith("http")) {
    try {
      path = new URL(value).pathname;
    } catch {
      return null;
    }
  }
  const match = path.match(/\/faq\/([^/?#]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function isValidFaqSlug(value: string): boolean {
  return (
    value.length <= 100 &&
    FAQ_SLUG_PATTERN.test(value) &&
    !value.includes("--") &&
    !value.includes("..")
  );
}

function wikiUrlForTitle(title: string): string | null {
  if (!title || title.length > 200 || /[<>"'\n\r\0]/.test(title)) return null;
  return `https://bisq.wiki/${encodeURIComponent(title.replace(/ /g, "_"))}`;
}

function safeSourceHref(href: string | undefined): string | null {
  const value = href?.trim();
  if (!value) return null;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? value : null;
  } catch {
    return null;
  }
}
