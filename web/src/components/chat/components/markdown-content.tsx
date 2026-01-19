/**
 * MarkdownContent - Chat-optimized markdown renderer
 *
 * Design principles applied:
 * - Speed Through Subtraction: Lightweight rendering, no extra interactions
 * - Spatial Consistency: prose-chat class uses 4px/8px/16px rhythm
 * - Progressive Disclosure: Markdown renders transparently when present
 * - Feedback Immediacy: Suspense fallback matches final output
 *
 * Performance optimizations:
 * - Dynamic import for react-markdown (~10KB gzipped) - only loaded when needed
 * - Stable component references via useMemo to prevent re-renders
 * - Memoized parent component
 *
 * Security: react-markdown is XSS-safe by default (no raw HTML)
 */

import { memo, useMemo, Suspense } from 'react';
import dynamic from 'next/dynamic';
import { ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';

// Dynamic import with SSR disabled - react-markdown only needed client-side
const ReactMarkdown = dynamic(() => import('react-markdown'), {
  ssr: false,
  loading: () => null, // Suspense handles loading state
});

interface MarkdownContentProps {
  /** Markdown content to render */
  content: string;
  /** Additional CSS classes */
  className?: string;
}

/** Allowed URL schemes (whitelist approach for security) */
const SAFE_URL_SCHEMES = ['http:', 'https:', 'mailto:', 'tel:'];

/**
 * Validate URL safety using a strict whitelist approach
 * @param href - The href to validate
 * @returns Safe href or '#' fallback
 */
function getSafeHref(href: string | undefined): string {
  if (!href) return '#';

  const normalizedHref = href.trim().toLowerCase();
  if (!normalizedHref) return '#';

  // Allow anchor links (start with #)
  if (normalizedHref.startsWith('#')) return href;

  // Allow relative URLs (no scheme - doesn't contain ':' before any '/')
  const colonIndex = normalizedHref.indexOf(':');
  const slashIndex = normalizedHref.indexOf('/');
  const isRelativeUrl = colonIndex === -1 || (slashIndex !== -1 && slashIndex < colonIndex);
  if (isRelativeUrl) return href;

  // Check if scheme is in whitelist
  const isSafeScheme = SAFE_URL_SCHEMES.some((scheme) =>
    normalizedHref.startsWith(scheme)
  );

  return isSafeScheme ? href : '#';
}

/**
 * Custom link component that opens in new tab with visual indicator
 * Defined outside memo component for stable reference
 */
function CustomLink({
  href,
  children,
}: {
  href?: string;
  children?: React.ReactNode;
}) {
  const safeHref = getSafeHref(href);

  return (
    <a
      href={safeHref}
      target="_blank"
      rel="noopener noreferrer"
      className="text-primary hover:underline inline-flex items-center gap-0.5"
    >
      {children}
      <ExternalLink className="h-3 w-3 flex-shrink-0" />
    </a>
  );
}

/**
 * Fallback content while markdown loads - shows plain text
 */
function MarkdownFallback({ content }: { content: string }) {
  return <span>{content}</span>;
}

/**
 * Renders markdown content with chat-optimized styling
 * Memoized to prevent unnecessary re-renders
 */
export const MarkdownContent = memo(function MarkdownContent({
  content,
  className,
}: MarkdownContentProps) {
  // Stable reference for custom components - prevents ReactMarkdown re-initialization
  const components = useMemo(
    () => ({
      // Custom link with external indicator and security
      a: ({ href, children }: { href?: string; children?: React.ReactNode }) => (
        <CustomLink href={href}>{children}</CustomLink>
      ),
    }),
    []
  );

  return (
    <div className={cn('prose-chat', className)}>
      <Suspense fallback={<MarkdownFallback content={content} />}>
        <ReactMarkdown components={components}>{content}</ReactMarkdown>
      </Suspense>
    </div>
  );
});
