/**
 * Mock for react-markdown to avoid ESM issues in Jest
 * Actual markdown rendering is validated via Playwright E2E tests
 */

import React from 'react';

type LinkProps = { href?: string; children?: React.ReactNode };
type ImageProps = { src?: string; alt?: string };

interface ReactMarkdownProps {
  children: string;
  components?: {
    a?: React.ComponentType<LinkProps> | ((props: LinkProps) => React.ReactNode);
    img?: React.ComponentType<ImageProps> | ((props: ImageProps) => React.ReactNode);
  };
}

/**
 * Simple mock that parses basic markdown patterns
 * This is sufficient for unit testing the component structure
 */
function MockReactMarkdown({ children, components }: ReactMarkdownProps) {
  const content = children || '';

  // Parse basic markdown patterns for testing
  const parseMarkdown = (text: string): React.ReactNode[] => {
    const elements: React.ReactNode[] = [];
    let remaining = text;
    let key = 0;

    // Process in order: code blocks, inline code, bold, italic, links
    const patterns: Array<{
      regex: RegExp;
      render: (match: RegExpMatchArray) => React.ReactNode;
    }> = [
      // Images: ![alt](src)
      {
        regex: /!\[([^\]]*)\]\(([^)]*)\)/,
        render: (match) => {
          const ImageComponent = components?.img;
          const alt = match[1];
          const src = match[2];
          if (ImageComponent) {
            return (
              <React.Fragment key={key++}>
                {React.createElement(
                  ImageComponent as React.ComponentType<ImageProps>,
                  { src, alt },
                )}
              </React.Fragment>
            );
          }
          // eslint-disable-next-line @next/next/no-img-element
          return <img key={key++} src={src} alt={alt} />;
        },
      },
      // Code blocks: ```code```
      {
        regex: /```\n?([\s\S]*?)\n?```/,
        render: (match) => (
          <pre key={key++}>
            <code>{match[1]}</code>
          </pre>
        ),
      },
      // Inline code: `code`
      {
        regex: /`([^`]+)`/,
        render: (match) => <code key={key++}>{match[1]}</code>,
      },
      // Bold: **text** or __text__
      {
        regex: /\*\*([^*]+)\*\*|__([^_]+)__/,
        render: (match) => <strong key={key++}>{match[1] || match[2]}</strong>,
      },
      // Italic: *text* or _text_
      {
        regex: /(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)/,
        render: (match) => <em key={key++}>{match[1] || match[2]}</em>,
      },
      // Links: [text](url)
      {
        regex: /\[([^\]]+)\]\(([^)]+)\)/,
        render: (match) => {
          const LinkComponent = components?.a;
          const href = match[2];
          const text = match[1];
          if (LinkComponent) {
            return (
              <React.Fragment key={key++}>
                {React.createElement(
                  LinkComponent as React.ComponentType<LinkProps>,
                  { href },
                  text,
                )}
              </React.Fragment>
            );
          }
          return (
            <a key={key++} href={href} target="_blank" rel="noopener noreferrer">
              {text}
            </a>
          );
        },
      },
    ];

    while (remaining.length > 0) {
      let earliestMatch: { index: number; match: RegExpMatchArray; pattern: (typeof patterns)[0] } | null = null;

      for (const pattern of patterns) {
        const match = remaining.match(pattern.regex);
        if (match && match.index !== undefined) {
          if (!earliestMatch || match.index < earliestMatch.index) {
            earliestMatch = { index: match.index, match, pattern };
          }
        }
      }

      if (earliestMatch) {
        // Add text before match
        if (earliestMatch.index > 0) {
          elements.push(remaining.slice(0, earliestMatch.index));
        }
        // Add matched element
        elements.push(earliestMatch.pattern.render(earliestMatch.match));
        // Continue with remaining text
        remaining = remaining.slice(earliestMatch.index + earliestMatch.match[0].length);
      } else {
        // No more matches, add remaining text
        elements.push(remaining);
        break;
      }
    }

    return elements;
  };

  // Handle lists
  const renderList = (text: string): React.ReactNode => {
    const lines = text.split('\n');
    const unorderedItems: string[] = [];
    const orderedItems: string[] = [];
    const paragraphs: string[] = [];

    for (const line of lines) {
      if (line.match(/^- /)) {
        unorderedItems.push(line.replace(/^- /, ''));
      } else if (line.match(/^\d+\. /)) {
        orderedItems.push(line.replace(/^\d+\. /, ''));
      } else if (line.trim()) {
        paragraphs.push(line);
      }
    }

    const elements: React.ReactNode[] = [];
    let key = 100;

    if (unorderedItems.length > 0) {
      elements.push(
        <ul key={key++}>
          {unorderedItems.map((item, i) => (
            <li key={i}>{parseMarkdown(item)}</li>
          ))}
        </ul>
      );
    }

    if (orderedItems.length > 0) {
      elements.push(
        <ol key={key++}>
          {orderedItems.map((item, i) => (
            <li key={i}>{parseMarkdown(item)}</li>
          ))}
        </ol>
      );
    }

    // Handle paragraphs (double newline separated)
    if (paragraphs.length > 0 && !unorderedItems.length && !orderedItems.length) {
      const paragraphBlocks = text.split(/\n\n+/);
      for (const block of paragraphBlocks) {
        if (block.trim()) {
          const trimmedBlock = block.trim();
          if (trimmedBlock.startsWith('```') && trimmedBlock.endsWith('```')) {
            elements.push(<React.Fragment key={key++}>{parseMarkdown(trimmedBlock)}</React.Fragment>);
          } else {
            elements.push(<p key={key++}>{parseMarkdown(trimmedBlock)}</p>);
          }
        }
      }
    } else if (paragraphs.length > 0) {
      for (const para of paragraphs) {
        elements.push(<p key={key++}>{parseMarkdown(para)}</p>);
      }
    }

    return elements.length > 0 ? elements : parseMarkdown(text);
  };

  return <>{renderList(content)}</>;
}

export default MockReactMarkdown;
