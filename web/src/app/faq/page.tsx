'use client';

import { Suspense, useEffect, useState, useCallback } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Search, ChevronLeft, ChevronRight, X, RotateCcw } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
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

  // Clear all filters
  const clearFilters = () => {
    setSearchInput('');
    router.push('/faq');
  };

  const hasActiveFilters = currentSearch || currentCategory;

  return (
    <>
      {/* Search and Filters */}
      <div className="mb-6 space-y-3">
        {/* Search and Category Filter Row */}
        <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
          {/* Enhanced Search Input */}
          <div className="relative w-full sm:w-80">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/70 pointer-events-none z-10" />
            <Input
              type="text"
              placeholder="Search FAQs..."
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="pl-9 pr-9 h-10 bg-background/60 backdrop-blur-sm border-border/40 focus:border-primary focus:bg-background transition-all"
            />
            {searchInput && (
              <Button
                variant="ghost"
                size="sm"
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 p-0 hover:bg-muted"
                onClick={() => {
                  setSearchInput('');
                  updateParams({ search: '' });
                }}
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </Button>
            )}
          </div>

          {/* Category Filter Dropdown */}
          {categories.length > 0 && (
            <Select
              value={currentCategory || 'all'}
              onValueChange={(value) => {
                updateParams({ category: value === 'all' ? '' : value });
              }}
            >
              <SelectTrigger className="h-10 w-full sm:w-48 bg-background/60 backdrop-blur-sm border-border/40 focus:border-primary transition-all">
                <SelectValue placeholder="All Categories" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Categories</SelectItem>
                {categories.map((category) => (
                  <SelectItem key={category.slug} value={category.name}>
                    {category.name} ({category.count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          {/* Active Filters Indicator and Reset */}
          {hasActiveFilters && (
            <div className="flex items-center gap-2">
              <Badge variant="secondary" className="h-7 px-2.5 gap-1.5 text-xs font-normal">
                <span className="text-muted-foreground">Filters:</span>
                <span className="font-medium">
                  {(currentSearch ? 1 : 0) + (currentCategory ? 1 : 0)}
                </span>
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={clearFilters}
                className="h-7 px-2 text-muted-foreground hover:text-foreground gap-1"
              >
                <RotateCcw className="h-3 w-3" />
                <span className="text-xs">Reset</span>
              </Button>
            </div>
          )}
        </div>

        {/* Active Filter Tags (shown when filters are active) */}
        {hasActiveFilters && (
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs text-muted-foreground">Showing:</span>
            {currentSearch && (
              <Badge
                variant="outline"
                className="h-6 gap-1 px-2 text-xs font-normal cursor-pointer hover:bg-muted transition-colors"
                onClick={() => {
                  setSearchInput('');
                  updateParams({ search: '' });
                }}
              >
                &quot;{currentSearch}&quot;
                <X className="h-3 w-3 ml-0.5" />
              </Badge>
            )}
            {currentCategory && (
              <Badge
                variant="outline"
                className="h-6 gap-1 px-2 text-xs font-normal cursor-pointer hover:bg-muted transition-colors"
                onClick={() => updateParams({ category: '' })}
              >
                {currentCategory}
                <X className="h-3 w-3 ml-0.5" />
              </Badge>
            )}
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
