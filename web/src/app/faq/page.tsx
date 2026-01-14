'use client';

import { Suspense, useEffect, useState, useCallback } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search, ChevronLeft, ChevronRight, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { FaqCard, FaqCardSkeleton } from '@/components/faq/FaqCard';
import {
  fetchPublicFAQs,
  fetchPublicFAQCategories,
  type PublicFAQ,
  type PublicFAQCategory,
  type Pagination,
} from '@/lib/faqPublicApi';

function FaqBrowseContent() {
  const router = useRouter();
  const searchParams = useSearchParams();

  // State
  const [faqs, setFaqs] = useState<PublicFAQ[]>([]);
  const [categories, setCategories] = useState<PublicFAQCategory[]>([]);
  const [pagination, setPagination] = useState<Pagination | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Get current filter values from URL
  const currentPage = Number(searchParams.get('page')) || 1;
  const currentSearch = searchParams.get('search') || '';
  const currentCategory = searchParams.get('category') || '';

  // Local state for search input (debounced)
  const [searchInput, setSearchInput] = useState(currentSearch);

  // Update URL with new params
  const updateParams = useCallback(
    (updates: { page?: number; search?: string; category?: string }) => {
      const params = new URLSearchParams(searchParams.toString());

      if (updates.page !== undefined) {
        if (updates.page === 1) {
          params.delete('page');
        } else {
          params.set('page', String(updates.page));
        }
      }

      if (updates.search !== undefined) {
        if (updates.search === '') {
          params.delete('search');
        } else {
          params.set('search', updates.search);
        }
        // Reset to page 1 when search changes
        params.delete('page');
      }

      if (updates.category !== undefined) {
        if (updates.category === '') {
          params.delete('category');
        } else {
          params.set('category', updates.category);
        }
        // Reset to page 1 when category changes
        params.delete('page');
      }

      const queryString = params.toString();
      router.push(`/faq${queryString ? `?${queryString}` : ''}`);
    },
    [router, searchParams]
  );

  // Fetch categories on mount
  useEffect(() => {
    fetchPublicFAQCategories()
      .then(setCategories)
      .catch((err) => console.error('Failed to fetch categories:', err));
  }, []);

  // Fetch FAQs when filters change
  useEffect(() => {
    setIsLoading(true);
    setError(null);

    fetchPublicFAQs({
      page: currentPage,
      limit: 12,
      search: currentSearch,
      category: currentCategory,
    })
      .then((response) => {
        setFaqs(response.data);
        setPagination(response.pagination);
      })
      .catch((err) => {
        console.error('Failed to fetch FAQs:', err);
        setError('Failed to load FAQs. Please try again.');
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, [currentPage, currentSearch, currentCategory]);

  // Debounced search
  useEffect(() => {
    const timer = setTimeout(() => {
      if (searchInput !== currentSearch) {
        updateParams({ search: searchInput });
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [searchInput, currentSearch, updateParams]);

  // Handle category click
  const handleCategoryClick = (categoryName: string) => {
    if (currentCategory === categoryName) {
      updateParams({ category: '' });
    } else {
      updateParams({ category: categoryName });
    }
  };

  // Clear all filters
  const clearFilters = () => {
    setSearchInput('');
    router.push('/faq');
  };

  const hasActiveFilters = currentSearch || currentCategory;

  return (
    <>
      {/* Search and Filters */}
      <div className="mb-6 space-y-4">
        {/* Search Input */}
        <div className="relative max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            type="search"
            placeholder="Search FAQs..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-10"
          />
        </div>

        {/* Category Filters */}
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {categories.map((category) => (
              <Badge
                key={category.slug}
                variant={currentCategory === category.name ? 'default' : 'outline'}
                className="cursor-pointer hover:bg-primary/10 transition-colors"
                onClick={() => handleCategoryClick(category.name)}
              >
                {category.name} ({category.count})
              </Badge>
            ))}
          </div>
        )}

        {/* Active Filters / Clear */}
        {hasActiveFilters && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <span>Showing results for:</span>
            {currentSearch && (
              <Badge variant="secondary" className="gap-1">
                &quot;{currentSearch}&quot;
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => {
                    setSearchInput('');
                    updateParams({ search: '' });
                  }}
                />
              </Badge>
            )}
            {currentCategory && (
              <Badge variant="secondary" className="gap-1">
                {currentCategory}
                <X
                  className="h-3 w-3 cursor-pointer"
                  onClick={() => updateParams({ category: '' })}
                />
              </Badge>
            )}
            <Button
              variant="ghost"
              size="sm"
              onClick={clearFilters}
              className="text-muted-foreground hover:text-foreground"
            >
              Clear all
            </Button>
          </div>
        )}
      </div>

      {/* Error State */}
      {error && (
        <div className="text-center py-12">
          <p className="text-destructive mb-4">{error}</p>
          <Button onClick={() => window.location.reload()}>Try Again</Button>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {Array.from({ length: 6 }).map((_, i) => (
            <FaqCardSkeleton key={i} />
          ))}
        </div>
      )}

      {/* FAQ Grid */}
      {!isLoading && !error && (
        <>
          {faqs.length === 0 ? (
            <div className="text-center py-12">
              <p className="text-muted-foreground mb-4">
                No FAQs found{hasActiveFilters ? ' matching your filters' : ''}.
              </p>
              {hasActiveFilters && (
                <Button variant="outline" onClick={clearFilters}>
                  Clear Filters
                </Button>
              )}
            </div>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {faqs.map((faq) => (
                <FaqCard key={faq.id} faq={faq} />
              ))}
            </div>
          )}

          {/* Pagination */}
          {pagination && pagination.total_pages > 1 && (
            <div className="flex items-center justify-center gap-2 mt-8">
              <Button
                variant="outline"
                size="sm"
                disabled={!pagination.has_prev}
                onClick={() => updateParams({ page: currentPage - 1 })}
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
                disabled={!pagination.has_next}
                onClick={() => updateParams({ page: currentPage + 1 })}
              >
                Next
                <ChevronRight className="h-4 w-4 ml-1" />
              </Button>
            </div>
          )}

          {/* Total Count */}
          {pagination && (
            <p className="text-center text-sm text-muted-foreground mt-4">
              {pagination.total_items} FAQ{pagination.total_items !== 1 ? 's' : ''} total
            </p>
          )}
        </>
      )}
    </>
  );
}

function FaqBrowseLoading() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <FaqCardSkeleton key={i} />
      ))}
    </div>
  );
}

export default function FaqBrowsePage() {
  return (
    <div className="min-h-screen bg-background">
      {/* Header */}
      <header className="border-b bg-card/50 backdrop-blur-sm sticky top-0 z-10">
        <div className="container mx-auto px-4 py-4">
          <div className="flex items-center gap-4">
            <Link href="/" className="text-muted-foreground hover:text-foreground transition-colors">
              <ChevronLeft className="h-5 w-5" />
              <span className="sr-only">Back to Chat</span>
            </Link>
            <h1 className="text-xl font-semibold">Frequently Asked Questions</h1>
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6">
        <Suspense fallback={<FaqBrowseLoading />}>
          <FaqBrowseContent />
        </Suspense>
      </main>
    </div>
  );
}
