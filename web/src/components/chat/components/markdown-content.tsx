/**
 * MarkdownContent - Chat-optimized markdown renderer
 *
 * Design principles applied:
 * - Speed Through Subtraction: Lightweight rendering, no extra interactions
 * - Spatial Consistency: prose-chat class uses 4px/8px/16px rhythm
 * - Progressive Disclosure: Markdown renders transparently when present
 * - Feedback Immediacy: Synchronous rendering, no loading states
 *
 * Security: react-markdown is XSS-safe by default (no raw HTML)
 */

import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import { ExternalLink } from 'lucide-react';
import { cn } from '@/lib/utils';

interface MarkdownContentProps {
  /** Markdown content to render */
  content: string;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Custom link component that opens in new tab with visual indicator
 */
function CustomLink({
  href,
  children,
}: {
  href?: string;
  children?: React.ReactNode;
}) {
  // Block javascript: URLs for security
  const safeHref =
    href && !href.toLowerCase().startsWith('javascript:') ? href : '#';

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
 * Renders markdown content with chat-optimized styling
 * Memoized to prevent unnecessary re-renders
 */
export const MarkdownContent = memo(function MarkdownContent({
  content,
  className,
}: MarkdownContentProps) {
  return (
    <div className={cn('prose-chat', className)}>
      <ReactMarkdown
        components={{
          // Custom link with external indicator and security
          a: ({ href, children }) => (
            <CustomLink href={href}>{children}</CustomLink>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
});
