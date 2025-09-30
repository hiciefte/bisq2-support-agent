"use client"

import { useState, useEffect, FormEvent } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardFooter, CardDescription } from "@/components/ui/card";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Pencil, Trash2, Loader2, PlusCircle, Filter, X, Search, RotateCcw } from 'lucide-react';
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useRouter } from 'next/navigation';
import { makeAuthenticatedRequest } from '@/lib/auth';

interface FAQ {
  id: string;
  question: string;
  answer: string;
  category: string;
  source: string;
}

interface FAQListResponse {
  faqs: FAQ[];
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function ManageFaqsPage() {
  const [faqData, setFaqData] = useState<FAQListResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isFormOpen, setIsFormOpen] = useState(false);
  const [editingFaq, setEditingFaq] = useState<FAQ | null>(null);
  const [formData, setFormData] = useState({ question: '', answer: '', category: '', source: 'Manual' });
  const [error, setError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize] = useState(10);

  // Filter state
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState({
    search_text: '',
    categories: [] as string[],
    source: ''
  });

  // Available categories and sources from the data
  const [availableCategories, setAvailableCategories] = useState<string[]>([]);
  const [availableSources, setAvailableSources] = useState<string[]>([]);

  const router = useRouter();

  useEffect(() => {
    // Since we're wrapped with SecureAuth, we know we're authenticated
    fetchFaqs();
  }, []);

  // Re-fetch data when filters change
  useEffect(() => {
    setCurrentPage(1); // Reset to first page when filters change
    fetchFaqs(1);
  }, [filters]);

  const fetchFaqs = async (page = 1) => {
    setIsLoading(true);
    try {
      // Build query parameters
      const params = new URLSearchParams({
        page: page.toString(),
        page_size: pageSize.toString(),
      });

      if (filters.search_text) {
        params.append('search_text', filters.search_text);
      }

      if (filters.categories.length > 0) {
        params.append('categories', filters.categories.join(','));
      }

      if (filters.source) {
        params.append('source', filters.source);
      }

      const response = await makeAuthenticatedRequest(`/admin/faqs?${params.toString()}`);
      if (response.ok) {
        const data = await response.json();
        setFaqData(data);
        setError(null);

        // Extract unique categories and sources for filter options
        if (data.faqs) {
          const categories = [...new Set(data.faqs.map((faq: FAQ) => faq.category).filter(Boolean))] as string[];
          const sources = [...new Set(data.faqs.map((faq: FAQ) => faq.source).filter(Boolean))] as string[];
          setAvailableCategories(categories);
          setAvailableSources(sources);
        }
      } else {
        const errorText = `Failed to fetch FAQs. Status: ${response.status}`;
        console.error(errorText);
        setError(errorText);
        if (response.status === 401 || response.status === 403) {
          // Let SecureAuth handle authentication errors
          window.location.reload();
        }
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while fetching FAQs.';
      console.error(errorText, error);
      setError(errorText);
    } finally {
      setIsLoading(false);
    }
  };


  const handleFormSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    const endpoint = editingFaq ? `/admin/faqs/${editingFaq.id}` : `/admin/faqs`;
    const method = editingFaq ? 'PUT' : 'POST';

    try {
      const response = await makeAuthenticatedRequest(endpoint, {
        method,
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(formData),
      });

      if (response.ok) {
        fetchFaqs(currentPage);
        setIsFormOpen(false);
        setEditingFaq(null);
        setFormData({ question: '', answer: '', category: '', source: 'Manual' });
        setError(null);
      } else {
        const errorText = `Failed to save FAQ. Status: ${response.status}`;
        console.error(errorText);
        setError(errorText);
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while saving the FAQ.';
      console.error(errorText, error);
      setError(errorText);
    } finally {
      setIsSubmitting(false);
    }
  };
  
  const handleEdit = (faq: FAQ) => {
    setEditingFaq(faq);
    setFormData({ question: faq.question, answer: faq.answer, category: faq.category, source: faq.source });
    setIsFormOpen(true);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };
  
  const handleDelete = async (id: string) => {
    setIsSubmitting(true);
    try {
      const response = await makeAuthenticatedRequest(`/admin/faqs/${id}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        fetchFaqs(currentPage);
        setError(null);
      } else {
        const errorText = `Failed to delete FAQ. Status: ${response.status}`;
        console.error(errorText);
        setError(errorText);
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while deleting the FAQ.';
      console.error(errorText, error);
      setError(errorText);
    } finally {
      setIsSubmitting(false);
    }
  };
  
  const openNewFaqForm = () => {
    setEditingFaq(null);
    setFormData({ question: '', answer: '', category: '', source: 'Manual' });
    setIsFormOpen(true);
    setError(null);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  const handlePageChange = (newPage: number) => {
    if (newPage >= 1 && newPage <= (faqData?.total_pages || 1)) {
      setCurrentPage(newPage);
      fetchFaqs(newPage);
    }
  };

  // Filter helper functions
  const handleSearchChange = (value: string) => {
    setFilters(prev => ({ ...prev, search_text: value }));
  };

  const handleCategoryToggle = (category: string) => {
    setFilters(prev => ({
      ...prev,
      categories: prev.categories.includes(category)
        ? prev.categories.filter(c => c !== category)
        : [...prev.categories, category]
    }));
  };

  const handleSourceChange = (source: string) => {
    setFilters(prev => ({ ...prev, source: source === 'all' ? '' : source }));
  };

  const clearAllFilters = () => {
    setFilters({
      search_text: '',
      categories: [],
      source: ''
    });
  };

  const hasActiveFilters = filters.search_text || filters.categories.length > 0 || filters.source;

  return (
    <div className="p-4 md:p-8 space-y-8 pt-16 lg:pt-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">FAQ Management</h1>
            <p className="text-muted-foreground">Create and manage frequently asked questions for the support system</p>
          </div>
          <div className="flex gap-2">
              <Button
                onClick={() => setShowFilters(!showFilters)}
                variant="outline"
                size="sm"
                className="border-border hover:border-primary"
              >
                <Filter className="mr-2 h-4 w-4" />
                Filters
                {hasActiveFilters && (
                  <Badge variant="secondary" className="ml-2 px-1.5 py-0.5 text-xs">
                    {[filters.search_text && 'text', filters.categories.length && `${filters.categories.length} cat`, filters.source && 'source'].filter(Boolean).length}
                  </Badge>
                )}
              </Button>
            </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg" role="alert">
              <strong className="font-bold">Error: </strong>
              <span className="block sm:inline">{error}</span>
          </div>
        )}

        {/* Filters Panel */}
        {showFilters && (
          <Card>
            <CardHeader className="relative">
              <Button
                onClick={() => setShowFilters(false)}
                variant="outline"
                size="sm"
                className="absolute right-2 top-2 h-8 w-8 p-0"
                aria-label="Close filters"
              >
                <X className="h-4 w-4" />
              </Button>
              <CardTitle className="flex items-center gap-2">
                <Filter className="h-5 w-5" />
                Filters
              </CardTitle>
              <CardDescription>
                Filter FAQs by text search, categories, and source
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Search Text */}
              <div className="space-y-2">
                <Label htmlFor="search">Search Text</Label>
                <div className="relative">
                  <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    id="search"
                    placeholder="Search in questions and answers..."
                    value={filters.search_text}
                    onChange={(e) => handleSearchChange(e.target.value)}
                    className="pl-10"
                  />
                </div>
              </div>

              {/* Categories */}
              <div className="space-y-2">
                <Label>Categories</Label>
                <div className="flex flex-wrap gap-2">
                  {availableCategories.map((category) => (
                    <Badge
                      key={category}
                      variant={filters.categories.includes(category) ? "default" : "outline"}
                      className="cursor-pointer hover:bg-primary hover:text-primary-foreground"
                      onClick={() => handleCategoryToggle(category)}
                    >
                      {category}
                    </Badge>
                  ))}
                  {availableCategories.length === 0 && (
                    <p className="text-sm text-muted-foreground">No categories available</p>
                  )}
                </div>
              </div>

              {/* Source */}
              <div className="space-y-2">
                <Label htmlFor="source">Source</Label>
                <Select value={filters.source || 'all'} onValueChange={handleSourceChange}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select source" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Sources</SelectItem>
                    {availableSources.map((source) => (
                      <SelectItem key={source} value={source}>
                        {source}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Filter Actions */}
              <div className="flex justify-between pt-4 border-t">
                <Button variant="outline" onClick={clearAllFilters} disabled={!hasActiveFilters} size="sm">
                  <RotateCcw className="mr-2 h-4 w-4" />
                  Reset Filters
                </Button>
                <div className="text-sm text-muted-foreground">
                  {hasActiveFilters && (
                    <span>
                      {[
                        filters.search_text && 'Text search',
                        filters.categories.length > 0 && `${filters.categories.length} categor${filters.categories.length === 1 ? 'y' : 'ies'}`,
                        filters.source && 'Source'
                      ].filter(Boolean).join(', ')} applied
                    </span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* FAQ Form */}
        {isFormOpen && (
          <Card className="bg-card border border-border shadow-sm">
          <CardHeader>
            <CardTitle>{editingFaq ? 'Edit FAQ' : 'Add New FAQ'}</CardTitle>
            <CardDescription>
              {editingFaq ? 'Update the details for this FAQ.' : 'Fill out the form to add a new FAQ to the knowledge base.'}
            </CardDescription>
          </CardHeader>
          <form onSubmit={handleFormSubmit}>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="question">Question</Label>
                <Input id="question" value={formData.question} onChange={(e) => setFormData({ ...formData, question: e.target.value })} required />
              </div>
              <div className="space-y-2">
                <Label htmlFor="answer">Answer</Label>
                <Textarea id="answer" value={formData.answer} onChange={(e) => setFormData({ ...formData, answer: e.target.value })} required />
              </div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="category">Category</Label>
                  <Input id="category" value={formData.category} onChange={(e) => setFormData({ ...formData, category: e.target.value })} required />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="source">Source</Label>
                  <Input id="source" value={formData.source} onChange={(e) => setFormData({ ...formData, source: e.target.value })} disabled />
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-end gap-2">
              <Button type="button" variant="outline" onClick={() => setIsFormOpen(false)}>Cancel</Button>
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                {editingFaq ? 'Save Changes' : 'Add FAQ'}
              </Button>
            </CardFooter>
          </form>
        </Card>
        )}

        {/* FAQ List */}
        <Card className="bg-card border border-border shadow-sm">
          <CardHeader className="flex flex-row items-center justify-between">
              <div>
                <CardTitle>FAQ List</CardTitle>
              <CardDescription>View, edit, or delete existing FAQs.</CardDescription>
            </div>
            {!isFormOpen && (
              <Button onClick={openNewFaqForm}>
                <PlusCircle className="mr-2 h-4 w-4" /> Add New FAQ
              </Button>
            )}
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !faqData?.faqs || faqData.faqs.length === 0 ? (
            <div className="text-center py-12">
              <h3 className="text-lg font-semibold">No FAQs Found</h3>
              <p className="text-muted-foreground mt-1">Get started by adding a new FAQ.</p>
              {!isFormOpen && (
                  <Button onClick={openNewFaqForm} className="mt-4">
                    <PlusCircle className="mr-2 h-4 w-4" /> Add New FAQ
                  </Button>
              )}
            </div>
          ) : (
            <div className="space-y-4">
              {faqData?.faqs.map((faq) => (
                <div key={faq.id} className="bg-card border border-border rounded-lg p-4 hover:shadow-sm transition-shadow">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 space-y-3">
                      <div>
                        <h3 className="font-semibold text-card-foreground text-base leading-relaxed">{faq.question}</h3>
                      </div>

                      <div>
                        <p className="text-muted-foreground text-sm leading-relaxed whitespace-pre-wrap">{faq.answer}</p>
                      </div>

                      <div className="flex items-center gap-4 text-sm text-muted-foreground">
                        <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground font-medium">
                          {faq.category}
                        </span>
                        <span>Source: {faq.source}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-1 ml-4">
                      <Button variant="ghost" size="icon" onClick={() => handleEdit(faq)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="icon" disabled={isSubmitting}>
                            <Trash2 className="h-4 w-4 text-red-500" />
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                            <AlertDialogDescription>
                              This action cannot be undone. This will permanently delete this FAQ.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancel</AlertDialogCancel>
                            <AlertDialogAction onClick={() => handleDelete(faq.id)}>Continue</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination Controls */}
          {faqData && faqData.total_pages > 1 && (
            <div className="flex items-center justify-between px-2 py-4">
              <div className="flex items-center space-x-6 lg:space-x-8">
                <div className="flex items-center space-x-2">
                  <p className="text-sm font-medium">
                    Showing {((faqData.page - 1) * faqData.page_size) + 1} to {Math.min(faqData.page * faqData.page_size, faqData.total_count)} of {faqData.total_count} entries
                  </p>
                </div>
              </div>
              <div className="flex items-center space-x-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(currentPage - 1)}
                  disabled={currentPage <= 1}
                >
                  Previous
                </Button>
                <div className="flex items-center space-x-1">
                  {Array.from({ length: Math.min(5, faqData.total_pages) }, (_, i) => {
                    const pageNum = Math.max(1, Math.min(faqData.total_pages - 4, currentPage - 2)) + i;
                    if (pageNum > faqData.total_pages) return null;
                    return (
                      <Button
                        key={pageNum}
                        variant={pageNum === currentPage ? "default" : "outline"}
                        size="sm"
                        onClick={() => handlePageChange(pageNum)}
                        className="w-8 h-8 p-0"
                      >
                        {pageNum}
                      </Button>
                    );
                  })}
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handlePageChange(currentPage + 1)}
                  disabled={currentPage >= faqData.total_pages}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </CardContent>
        </Card>
    </div>
  );
} 