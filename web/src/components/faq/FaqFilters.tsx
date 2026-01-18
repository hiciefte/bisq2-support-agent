'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Search, X, Filter } from 'lucide-react';
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
import { PublicFAQCategory } from '@/lib/faqPublicApi';

interface FaqFiltersProps {
  categories: PublicFAQCategory[];
  initialSearch?: string;
  initialCategory?: string;
}

export function FaqFilters({
  categories,
  initialSearch = '',
  initialCategory = '',
}: FaqFiltersProps) {
  const router = useRouter();
  const searchParams = useSearchParams();

  const [searchInput, setSearchInput] = useState(initialSearch);
  const [selectedCategory, setSelectedCategory] = useState(initialCategory);

  // Use refs to access current values in debounced callback without stale closures
  const searchInputRef = useRef(searchInput);
  const selectedCategoryRef = useRef(selectedCategory);

  // Keep refs in sync with state
  useEffect(() => {
    searchInputRef.current = searchInput;
  }, [searchInput]);

  useEffect(() => {
    selectedCategoryRef.current = selectedCategory;
  }, [selectedCategory]);

  const updateUrlParams = useCallback(
    ({ search, category }: { search: string; category: string }) => {
      const params = new URLSearchParams(searchParams.toString());

      // Always reset to page 1 when filters change
      params.delete('page');

      if (search) {
        params.set('search', search);
      } else {
        params.delete('search');
      }

      if (category) {
        params.set('category', category);
      } else {
        params.delete('category');
      }

      const queryString = params.toString();
      router.push(`/faq${queryString ? `?${queryString}` : ''}`, {
        scroll: false,
      });
    },
    [router, searchParams]
  );

  // Debounce search input - use refs to avoid stale closure
  useEffect(() => {
    const timer = setTimeout(() => {
      updateUrlParams({
        search: searchInputRef.current,
        category: selectedCategoryRef.current,
      });
    }, 300);
    return () => clearTimeout(timer);
  }, [searchInput, updateUrlParams]);

  // Update URL when category changes (immediate, no debounce)
  useEffect(() => {
    updateUrlParams({
      search: searchInputRef.current,
      category: selectedCategoryRef.current,
    });
  }, [selectedCategory, updateUrlParams]);

  const handleClearFilters = () => {
    setSearchInput('');
    setSelectedCategory('');
    router.push('/faq', { scroll: false });
  };

  const hasActiveFilters = searchInput || selectedCategory;

  return (
    <div className="space-y-4">
      {/* Search and Category Filter Row */}
      <div className="flex flex-col sm:flex-row gap-4">
        {/* Search Input */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search FAQs..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-10"
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
              aria-label="Clear search"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {/* Category Filter */}
        <div className="w-full sm:w-48">
          <Select
            value={selectedCategory || 'all'}
            onValueChange={(value) => setSelectedCategory(value === 'all' ? '' : value)}
          >
            <SelectTrigger>
              <Filter className="h-4 w-4 mr-2" />
              <SelectValue placeholder="All Categories" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Categories</SelectItem>
              {categories.map((cat) => (
                <SelectItem key={cat.slug} value={cat.slug}>
                  {cat.name} ({cat.count})
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Active Filters Display */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm text-muted-foreground">Active filters:</span>
          {searchInput && (
            <Badge variant="secondary" className="gap-1">
              Search: &quot;{searchInput}&quot;
              <button
                onClick={() => setSearchInput('')}
                className="ml-1 hover:text-foreground"
                aria-label="Remove search filter"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          )}
          {selectedCategory && (
            <Badge variant="secondary" className="gap-1">
              Category:{' '}
              {categories.find((c) => c.slug === selectedCategory)?.name ||
                selectedCategory}
              <button
                onClick={() => setSelectedCategory('')}
                className="ml-1 hover:text-foreground"
                aria-label="Remove category filter"
              >
                <X className="h-3 w-3" />
              </button>
            </Badge>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClearFilters}
            className="text-muted-foreground hover:text-foreground"
          >
            Clear all
          </Button>
        </div>
      )}
    </div>
  );
}
