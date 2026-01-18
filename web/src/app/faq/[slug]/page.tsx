import { Metadata } from 'next';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { ChevronLeft, MessageCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { fetchPublicFAQBySlug, fetchAllFAQSlugs } from '@/lib/faqPublicApi';

// Revalidate every 15 minutes (consistent with FAQ list page)
export const revalidate = 900;

interface FaqDetailPageProps {
  params: Promise<{ slug: string }>;
}

/**
 * Generate static params for all FAQ pages at build time
 * This enables static generation with ISR for FAQ detail pages
 */
export async function generateStaticParams() {
  const slugs = await fetchAllFAQSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: FaqDetailPageProps): Promise<Metadata> {
  const resolvedParams = await params;
  const faq = await fetchPublicFAQBySlug(resolvedParams.slug);

  if (!faq) {
    return {
      title: 'FAQ Not Found - Bisq 2 Support',
    };
  }

  return {
    title: `${faq.question} - Bisq 2 FAQ`,
    description: faq.answer.substring(0, 160),
  };
}

export default async function FaqDetailPage({ params }: FaqDetailPageProps) {
  const resolvedParams = await params;
  const faq = await fetchPublicFAQBySlug(resolvedParams.slug);

  if (!faq) {
    notFound();
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-4">
            <Link
              href="/faq"
              className="text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
            >
              <ChevronLeft className="h-5 w-5" />
              <span className="text-sm">Back to FAQs</span>
            </Link>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-8 max-w-3xl">
        <Card>
          <CardHeader>
            <div className="flex items-start justify-between gap-4">
              <CardTitle className="text-xl leading-relaxed">
                {faq.question}
              </CardTitle>
            </div>
            {faq.category && (
              <Badge variant="secondary" className="w-fit mt-2">
                {faq.category}
              </Badge>
            )}
          </CardHeader>
          <CardContent>
            <div className="prose prose-invert max-w-none">
              <p className="text-muted-foreground whitespace-pre-wrap leading-relaxed">
                {faq.answer}
              </p>
            </div>

            {faq.updated_at && (
              <p className="text-xs text-muted-foreground mt-6 pt-4 border-t">
                Last updated:{' '}
                {new Date(faq.updated_at).toLocaleDateString('en-US', {
                  year: 'numeric',
                  month: 'long',
                  day: 'numeric',
                })}
              </p>
            )}
          </CardContent>
        </Card>

        {/* Call to Action */}
        <div className="mt-8 text-center">
          <p className="text-muted-foreground mb-4">
            Need more help with this topic?
          </p>
          <Link href="/">
            <Button>
              <MessageCircle className="h-4 w-4 mr-2" />
              Ask the Support Assistant
            </Button>
          </Link>
        </div>
      </main>
    </div>
  );
}
