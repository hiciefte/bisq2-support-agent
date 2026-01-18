import { Suspense } from 'react';
import Link from 'next/link';
import { Metadata } from 'next';
import { ChevronLeft } from 'lucide-react';
import { FaqFilters, FaqGrid, FaqCardSkeleton } from '@/components/faq';
import {
  fetchPublicFAQs,
  fetchPublicFAQCategories,
} from '@/lib/faqPublicApi';

// Revalidate every 15 minutes for ISR
export const revalidate = 900;

export const metadata: Metadata = {
  title: 'Frequently Asked Questions - Bisq 2 Support',
  description:
    'Browse frequently asked questions about Bisq 2, trading, reputation, and more. Find answers to common questions about the Bisq decentralized exchange.',
};

interface FaqPageProps {
  searchParams: Promise<{
    page?: string;
    search?: string;
    category?: string;
  }>;
}

// Loading skeleton component
function FaqGridSkeleton() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <FaqCardSkeleton key={i} />
      ))}
    </div>
  );
}

export default async function FaqBrowsePage({ searchParams }: FaqPageProps) {
  // Await searchParams (Next.js 15 requirement)
  const resolvedParams = await searchParams;
  const page = parseInt(resolvedParams.page || '1', 10);
  const search = resolvedParams.search || '';
  const category = resolvedParams.category || '';

  // Fetch data server-side in parallel
  const [faqsResponse, categories] = await Promise.all([
    fetchPublicFAQs({
      page,
      limit: 12,
      search: search || undefined,
      category: category || undefined,
    }),
    fetchPublicFAQCategories(),
  ]);

  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-4">
            <Link
              href="/"
              className="text-muted-foreground hover:text-foreground transition-colors"
            >
              <ChevronLeft className="h-5 w-5" />
              <span className="sr-only">Back to Chat</span>
            </Link>
            <h1 className="text-xl font-semibold">Frequently Asked Questions</h1>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        {/* Filters - Client Component */}
        <div className="mb-6">
          <Suspense fallback={<div className="h-10 bg-muted/50 rounded animate-pulse" />}>
            <FaqFilters
              categories={categories}
              initialSearch={search}
              initialCategory={category}
            />
          </Suspense>
        </div>

        {/* FAQ Grid - Client Component with Server-Fetched Initial Data */}
        <Suspense fallback={<FaqGridSkeleton />}>
          <FaqGrid
            initialFaqs={faqsResponse.data}
            initialPagination={faqsResponse.pagination}
          />
        </Suspense>
      </main>
    </div>
  );
}
