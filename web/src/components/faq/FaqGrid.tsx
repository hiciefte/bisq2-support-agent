'use client';

import { useCallback, useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { FaqCard } from './FaqCard';
import { fetchPublicFAQs, PublicFAQ, Pagination } from '@/lib/faqPublicApi';

interface FaqGridProps {
  initialFaqs: PublicFAQ[];
  initialPagination: Pagination;
}

export function FaqGrid({ initialFaqs, initialPagination }: FaqGridProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [faqs, setFaqs] = useState<PublicFAQ[]>(initialFaqs);
  const [pagination, setPagination] = useState<Pagination>(initialPagination);
  const [isLoading, setIsLoading] = useState(false);

  // Current filter values from URL
  const search = searchParams.get('search') || '';
  const category = searchParams.get('category') || '';
  const parsedPage = parseInt(searchParams.get('page') || '1', 10);
  // Validate page number: must be positive integer, default to 1 if invalid
  const page = Number.isNaN(parsedPage) || parsedPage < 1 ? 1 : parsedPage;

  // Fetch FAQs when URL params change
  useEffect(() => {
    // Use AbortController to cancel in-flight requests on param changes
    const abortController = new AbortController();

    const loadFaqs = async () => {
      setIsLoading(true);
      try {
        const result = await fetchPublicFAQs({
          page,
          limit: 12,
          search: search || undefined,
          category: category || undefined,
        });

        // Only update state if this request wasn't aborted
        if (!abortController.signal.aborted) {
          setFaqs(result.data);
          setPagination(result.pagination);
        }
      } catch (error) {
        // Ignore abort errors, log others
        if (error instanceof Error && error.name !== 'AbortError') {
          console.error('Failed to load FAQs:', error);
        }
      } finally {
        if (!abortController.signal.aborted) {
          setIsLoading(false);
        }
      }
    };

    // Skip initial load if we have initial data and params match
    const isInitialLoad =
      page === 1 && !search && !category && initialFaqs.length > 0;

    if (!isInitialLoad) {
      loadFaqs();
    }

    // Cleanup: abort any pending request when deps change or unmount
    return () => {
      abortController.abort();
    };
  }, [search, category, page, initialFaqs.length]);

  const handlePageChange = useCallback(
    (newPage: number) => {
      const params = new URLSearchParams(searchParams.toString());
      if (newPage > 1) {
        params.set('page', String(newPage));
      } else {
        params.delete('page');
      }
      const queryString = params.toString();
      router.push(`/faq${queryString ? `?${queryString}` : ''}`, {
        scroll: true,
      });
    },
    [router, searchParams]
  );

  // Loading skeleton
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="p-4 border rounded-lg space-y-3">
              <Skeleton className="h-5 w-3/4" />
              <Skeleton className="h-4 w-full" />
              <Skeleton className="h-4 w-2/3" />
            </div>
          ))}
        </div>
      </div>
    );
  }

  // No results
  if (faqs.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-muted-foreground">
          No FAQs found matching your criteria.
        </p>
        {(search || category) && (
          <Button
            variant="link"
            onClick={() => router.push('/faq')}
            className="mt-2"
          >
            Clear filters
          </Button>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Results Count */}
      <p className="text-sm text-muted-foreground">
        Showing {faqs.length} of {pagination.total_items} FAQs
        {(search || category) && ' matching your filters'}
      </p>

      {/* FAQ Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {faqs.map((faq) => (
          <FaqCard key={faq.id} faq={faq} />
        ))}
      </div>

      {/* Pagination */}
      {pagination.total_pages > 1 && (
        <div className="flex items-center justify-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => handlePageChange(pagination.page - 1)}
            disabled={!pagination.has_prev}
          >
            <ChevronLeft className="h-4 w-4 mr-1" />
            Previous
          </Button>
          <span className="text-sm text-muted-foreground px-4">
            Page {pagination.page} of {pagination.total_pages}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={() => handlePageChange(pagination.page + 1)}
            disabled={!pagination.has_next}
          >
            Next
            <ChevronRight className="h-4 w-4 ml-1" />
          </Button>
        </div>
      )}
    </div>
  );
}
