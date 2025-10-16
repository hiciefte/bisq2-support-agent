"use client"

import { useState, useEffect, useCallback, useRef, FormEvent } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardFooter, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger, DialogClose } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DatePicker } from "@/components/ui/date-picker";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle, AlertDialogTrigger } from "@/components/ui/alert-dialog";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Loader2,
  MessageCircle,
  ThumbsDown,
  ThumbsUp,
  Search,
  Filter,
  Calendar,
  FileText,
  PlusCircle,
  Eye,
  RotateCcw,
  Download,
  AlertTriangle,
  TrendingUp,
  X,
  Trash2
} from 'lucide-react';
import { useRouter } from 'next/navigation';
import { format } from 'date-fns';
import { loginWithApiKey, logout, makeAuthenticatedRequest } from '@/lib/auth';
import { ConversationHistory } from '@/components/admin/ConversationHistory';
import { ConversationMessage } from '@/types/feedback';

interface FeedbackItem {
  message_id: string;
  question: string;
  answer: string;
  rating: number;
  timestamp: string;
  conversation_history?: ConversationMessage[];
  sources?: Array<{
    title: string;
    type: string;
    content: string;
  }>;
  sources_used?: Array<{
    title: string;
    type: string;
    content: string;
  }>;
  metadata?: {
    explanation?: string;
    issues?: string[];
    response_time?: number;
  };
  is_positive: boolean;
  is_negative: boolean;
  explanation?: string;
  issues: string[];
  has_no_source_response: boolean;
  // Feedback tracking fields
  is_processed?: boolean;
  processed_at?: string;
  faq_id?: string;
}

interface FeedbackListResponse {
  feedback_items: FeedbackItem[];
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  filters_applied: Record<string, any>;
}

interface FeedbackStats {
  total_feedback: number;
  positive_count: number;
  negative_count: number;
  helpful_rate: number;
  common_issues: Record<string, number>;
  recent_negative_count: number;
  needs_faq_count: number;
  source_effectiveness: Record<string, any>;
  feedback_by_month: Record<string, number>;
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

export default function ManageFeedbackPage() {
  // Authentication state
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isCheckingAuth, setIsCheckingAuth] = useState<boolean>(true);
  const [loginError, setLoginError] = useState('');

  // Data state
  const [feedbackData, setFeedbackData] = useState<FeedbackListResponse | null>(null);
  const [stats, setStats] = useState<FeedbackStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [filters, setFilters] = useState({
    rating: 'all',
    date_from: undefined as Date | undefined,
    date_to: undefined as Date | undefined,
    issues: [] as string[],
    source_types: [] as string[],
    search_text: '',
    needs_faq: false,
    page: 1,
    page_size: 25,
    sort_by: 'newest'
  });

  // UI state
  const [activeTab, setActiveTab] = useState<'all' | 'negative' | 'needs_faq'>('all');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [showFeedbackDetail, setShowFeedbackDetail] = useState(false);

  // FAQ creation state
  const [showCreateFAQ, setShowCreateFAQ] = useState(false);
  const [selectedFeedbackForFAQ, setSelectedFeedbackForFAQ] = useState<FeedbackItem | null>(null);
  const [faqForm, setFaqForm] = useState({
    message_id: '',
    suggested_question: '',
    suggested_answer: '',
    category: '',
    additional_notes: ''
  });
  const [isSubmittingFAQ, setIsSubmittingFAQ] = useState(false);
  const [customCategory, setCustomCategory] = useState('');
  const [isCustomCategory, setIsCustomCategory] = useState(false);

  // Delete feedback state
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [feedbackToDelete, setFeedbackToDelete] = useState<FeedbackItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);

  // Common FAQ categories
  const predefinedCategories = [
    'General',
    'Trading',
    'Reputation',
    'Security',
    'Payments',
    'Technical',
    'Bisq Easy',
    'Bisq 2',
    'Fees',
    'Account'
  ];

  const router = useRouter();

  // Check if there are any active filters
  const hasActiveFilters = filters.search_text ||
    filters.rating !== 'all' ||
    filters.date_from ||
    filters.date_to ||
    filters.issues.length > 0 ||
    filters.source_types.length > 0 ||
    filters.needs_faq;

  // Common issue types for filtering
  const ISSUE_TYPES = [
    'too_verbose', 'too_technical', 'not_specific', 'inaccurate',
    'outdated', 'not_helpful', 'missing_context', 'confusing'
  ];

  const SOURCE_TYPES = ['faq', 'wiki', 'unknown'];

  // Refs to track previous data hashes for smart updates
  const previousFeedbackHashRef = useRef<string>('');
  const previousStatsHashRef = useRef<string>('');
  const savedScrollPositionRef = useRef<number | null>(null);

  // Restore scroll position after background refresh if it was saved
  useEffect(() => {
    if (savedScrollPositionRef.current !== null) {
      window.scrollTo(0, savedScrollPositionRef.current);
      savedScrollPositionRef.current = null;
    }
  }, [feedbackData, stats]);

  useEffect(() => {
    // SECURITY: No longer using localStorage for API keys - migrating to secure HTTP-only cookies
    // const storedApiKey = localStorage.getItem('admin_api_key');
    // This component will be replaced by the SecureAuth wrapper in the layout
    // For now, just set loading to false since authentication is handled at layout level
    setIsLoading(false);
  }, []);

  const fetchFeedbackList = useCallback(async () => {
    // Adjust filters based on active tab
    const adjustedFilters = { ...filters };
    if (activeTab === 'negative') {
      adjustedFilters.rating = 'negative';
    } else if (activeTab === 'needs_faq') {
      adjustedFilters.needs_faq = true;
    }

    const params = new URLSearchParams();
    Object.entries(adjustedFilters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '' &&
          !(Array.isArray(value) && value.length === 0) && value !== false) {
        if (Array.isArray(value)) {
          params.append(key, value.join(','));
        } else if (value instanceof Date) {
          // Convert Date objects to ISO date strings
          params.append(key, format(value, 'yyyy-MM-dd'));
        } else {
          params.append(key, value.toString());
        }
      }
    });

    const response = await makeAuthenticatedRequest(`/admin/feedback/list?${params}`);

    if (response.ok) {
      const data = await response.json();

      // Calculate hash of new data for comparison
      const dataHash = JSON.stringify(data);

      // Only update state if data has actually changed
      if (dataHash !== previousFeedbackHashRef.current) {
        previousFeedbackHashRef.current = dataHash;
        setFeedbackData(data);
      }
    } else {
      throw new Error(`Failed to fetch feedback. Status: ${response.status}`);
    }
  }, [filters, activeTab]);

  const fetchStats = useCallback(async () => {
    const response = await makeAuthenticatedRequest('/admin/feedback/stats');

    if (response.ok) {
      const data = await response.json();

      // Calculate hash of new data for comparison
      const dataHash = JSON.stringify(data);

      // Only update state if data has actually changed
      if (dataHash !== previousStatsHashRef.current) {
        previousStatsHashRef.current = dataHash;
        setStats(data);
      }
    } else {
      throw new Error(`Failed to fetch stats. Status: ${response.status}`);
    }
  }, []);

  const fetchData = useCallback(async (isBackgroundRefresh = false) => {
    // Save scroll position for background refreshes
    if (isBackgroundRefresh) {
      savedScrollPositionRef.current = window.scrollY;
    }

    // Only show loading spinner if not a background refresh
    if (!isBackgroundRefresh) {
      setIsLoading(true);
    }

    try {
      await Promise.all([
        fetchFeedbackList(),
        fetchStats()
      ]);
      setError(null);
    } catch (err) {
      console.error('Error fetching data:', err);
      setError('Failed to fetch feedback data');
    } finally {
      if (!isBackgroundRefresh) {
        setIsLoading(false);
      }
    }
  }, [fetchFeedbackList, fetchStats]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    // Auto-refresh every 30 seconds (background refresh - no loading spinner)
    const intervalId = setInterval(() => {
      fetchData(true);
    }, 30000);

    // Cleanup interval on unmount
    return () => clearInterval(intervalId);
  }, [fetchData]);

  const handleLogin = async (e: FormEvent) => {
    e.preventDefault();
    const key = (e.target as HTMLFormElement).apiKey.value;
    if (key) {
      try {
        // Use the secure cookie-based authentication
        await loginWithApiKey(key);
        setLoginError('');
        // Fetch data after successful login
        await fetchData();
        // Notify layout of auth change
        window.dispatchEvent(new CustomEvent('admin-auth-changed'));
      } catch (error) {
        setLoginError('Login failed. Please check your API key.');
        console.error('Login error:', error);
      }
    }
  };

  const handleLogout = async () => {
    try {
      await logout();
      // Notify layout of auth change
      window.dispatchEvent(new CustomEvent('admin-auth-changed'));
      setFeedbackData(null);
      setStats(null);
      router.push('/admin/manage-feedback');
    } catch (error) {
      console.error('Logout error:', error);
    }
  };

  const handleFilterChange = (key: string, value: any) => {
    setFilters(prev => ({
      ...prev,
      [key]: value,
      page: 1 // Reset to first page when filters change
    }));
  };

  const resetFilters = () => {
    setFilters({
      rating: 'all',
      date_from: undefined,
      date_to: undefined,
      issues: [],
      source_types: [],
      search_text: '',
      needs_faq: false,
      page: 1,
      page_size: 25,
      sort_by: 'newest'
    });
  };

  const fetchFullFeedbackDetails = async (feedback: FeedbackItem): Promise<FeedbackItem> => {
    try {
      const response = await makeAuthenticatedRequest(`/admin/feedback/${feedback.message_id}`);

      if (response.ok) {
        const fullFeedback = await response.json();
        return {
          ...feedback,
          conversation_history: fullFeedback.conversation_history || []
        };
      }
    } catch (error) {
      console.error('Error fetching feedback details:', error);
    }

    // Fall back to list data
    return feedback;
  };

  const openFeedbackDetail = async (feedback: FeedbackItem) => {
    const fullFeedback = await fetchFullFeedbackDetails(feedback);
    setSelectedFeedback(fullFeedback);
    setShowFeedbackDetail(true);
  };

  const openCreateFAQ = async (feedback: FeedbackItem) => {
    const fullFeedback = await fetchFullFeedbackDetails(feedback);
    setSelectedFeedbackForFAQ(fullFeedback);

    setFaqForm({
      message_id: feedback.message_id,
      suggested_question: feedback.question,
      suggested_answer: '',
      category: 'General',
      additional_notes: feedback.explanation || ''
    });
    setIsCustomCategory(false);
    setCustomCategory('');
    setShowCreateFAQ(true);
  };

  const handleCreateFAQ = async (e: FormEvent) => {
    e.preventDefault();

    setIsSubmittingFAQ(true);
    try {
      const response = await makeAuthenticatedRequest('/admin/feedback/create-faq', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(faqForm),
      });

      if (response.ok) {
        setShowCreateFAQ(false);
        setFaqForm({
          message_id: '',
          suggested_question: '',
          suggested_answer: '',
          category: '',
          additional_notes: ''
        });
        setIsCustomCategory(false);
        setCustomCategory('');
        // Refresh data to reflect changes
        fetchData();
        setError(null);
      } else {
        const errorText = `Failed to create FAQ. Status: ${response.status}`;
        setError(errorText);
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while creating the FAQ.';
      setError(errorText);
    } finally {
      setIsSubmittingFAQ(false);
    }
  };

  const handleDeleteFeedback = async () => {
    if (!feedbackToDelete) return;

    setIsDeleting(true);
    try {
      const response = await makeAuthenticatedRequest(`/admin/feedback/${feedbackToDelete.message_id}`, {
        method: 'DELETE',
      });

      if (response.ok || response.status === 204) {
        // Success - close dialog and refresh data
        setShowDeleteConfirm(false);
        setFeedbackToDelete(null);
        // Refresh data to reflect deletion
        await fetchData();
        setError(null);
      } else if (response.status === 404) {
        setError('Feedback not found. It may have already been deleted.');
        setShowDeleteConfirm(false);
        setFeedbackToDelete(null);
        // Refresh to sync with server state
        await fetchData();
      } else {
        const errorText = `Failed to delete feedback. Status: ${response.status}`;
        setError(errorText);
      }
    } catch (error) {
      const errorText = 'An unexpected error occurred while deleting feedback.';
      setError(errorText);
      console.error('Delete feedback error:', error);
    } finally {
      setIsDeleting(false);
    }
  };

  const openDeleteConfirmation = (feedback: FeedbackItem) => {
    setFeedbackToDelete(feedback);
    setShowDeleteConfirm(true);
  };

  const exportFeedback = async () => {
    if (!feedbackData || feedbackData.feedback_items.length === 0) return;

    // Helper function to escape CSV values properly
    const escapeCSV = (value: any): string => {
      if (value === null || value === undefined) return '';
      const str = String(value);
      // Escape double quotes by doubling them, and wrap in quotes if contains comma, quote, or newline
      if (str.includes('"') || str.includes(',') || str.includes('\n') || str.includes('\r')) {
        return `"${str.replace(/"/g, '""')}"`;
      }
      return str;
    };

    const csvData = feedbackData.feedback_items.map(item => ({
      message_id: item.message_id,
      timestamp: item.timestamp,
      rating: item.rating,
      question: item.question,
      answer: item.answer,
      explanation: item.explanation || '',
      issues: item.issues ? item.issues.join(';') : '',
      has_no_source: item.has_no_source_response
    }));

    const csvContent = [
      Object.keys(csvData[0]).join(','),
      ...csvData.map(row => Object.values(row).map(val => escapeCSV(val)).join(','))
    ].join('\n');

    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `feedback-export-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
  };

  const formatDate = (timestamp: string) => {
    return new Date(timestamp).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getIssueColor = (issue: string) => {
    const colors = {
      'inaccurate': 'bg-red-100 text-red-800',
      'too_technical': 'bg-yellow-100 text-yellow-800',
      'too_verbose': 'bg-blue-100 text-blue-800',
      'confusing': 'bg-purple-100 text-purple-800',
      'not_helpful': 'bg-gray-100 text-gray-800'
    };
    return colors[issue as keyof typeof colors] || 'bg-gray-100 text-gray-800';
  };

  // Authentication is handled by SecureAuth wrapper in layout

  return (
    <div className="p-4 md:p-8 space-y-8 pt-16 lg:pt-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Feedback Management</h1>
            <p className="text-muted-foreground">Monitor and analyze user feedback for the support assistant</p>
          </div>
          <div className="flex gap-2">
              <Button onClick={() => setShowFilters(!showFilters)} variant="outline" size="sm" className="border-border hover:border-primary">
                <Filter className="mr-2 h-4 w-4" />
                Filters
                {hasActiveFilters && (
                  <Badge variant="secondary" className="ml-2 px-1.5 py-0.5 text-xs">
                    {[
                      filters.search_text && 'text',
                      filters.rating !== 'all' && 'rating',
                      filters.date_from && 'date',
                      filters.issues.length && `${filters.issues.length} issue${filters.issues.length > 1 ? 's' : ''}`,
                      filters.source_types.length && `${filters.source_types.length} source${filters.source_types.length > 1 ? 's' : ''}`,
                      filters.needs_faq && 'needs FAQ'
                    ].filter(Boolean).length}
                  </Badge>
                )}
              </Button>
              <Button onClick={exportFeedback} variant="outline" size="sm" className="border-border hover:border-primary">
                <Download className="mr-2 h-4 w-4" />
                Export
              </Button>
            </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
            <strong className="font-bold">Error: </strong>
            <span className="block sm:inline">{error}</span>
          </div>
        )}


        {/* Tabs */}
        <div className="bg-card rounded-lg shadow-sm border border-border">
          <div className="flex space-x-1 border-b border-border px-6 pt-4">
            <button
              className={`px-4 py-2 font-medium text-sm rounded-t-lg transition-colors ${activeTab === 'all' ? 'border-b-2 border-primary text-primary bg-accent' : 'text-muted-foreground hover:text-card-foreground hover:bg-accent'}`}
              onClick={() => setActiveTab('all')}
            >
          All Feedback
        </button>
            <button
              className={`px-4 py-2 font-medium text-sm rounded-t-lg transition-colors ${activeTab === 'negative' ? 'border-b-2 border-primary text-primary bg-accent' : 'text-muted-foreground hover:text-card-foreground hover:bg-accent'}`}
              onClick={() => setActiveTab('negative')}
            >
          Negative Only
        </button>
            <button
              className={`px-4 py-2 font-medium text-sm rounded-t-lg transition-colors ${activeTab === 'needs_faq' ? 'border-b-2 border-primary text-primary bg-accent' : 'text-muted-foreground hover:text-card-foreground hover:bg-accent'}`}
              onClick={() => setActiveTab('needs_faq')}
                >
              Needs FAQ Creation
            </button>
          </div>
        </div>

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
            <CardTitle>Filters</CardTitle>
            <CardDescription>Filter feedback by various criteria</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Search Text</Label>
                <Input
                  placeholder="Search in questions, answers..."
                  value={filters.search_text}
                  onChange={(e) => handleFilterChange('search_text', e.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label>Date From</Label>
                <DatePicker
                  value={filters.date_from}
                  onChange={(date) => handleFilterChange('date_from', date)}
                  placeholder="Select start date"
                />
              </div>
              <div className="space-y-2">
                <Label>Date To</Label>
                <DatePicker
                  value={filters.date_to}
                  onChange={(date) => handleFilterChange('date_to', date)}
                  placeholder="Select end date"
                />
              </div>
            </div>
            <div className="flex justify-between items-center">
              <Button onClick={resetFilters} variant="outline" size="sm">
                <RotateCcw className="mr-2 h-4 w-4" />
                Reset Filters
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Feedback List */}
      <Card>
        <CardHeader>
          <CardTitle>
            Feedback List
            {feedbackData && (
              <span className="text-sm font-normal text-muted-foreground ml-2">
                ({feedbackData.total_count} items)
              </span>
            )}
          </CardTitle>
          <CardDescription>
            {activeTab === 'all' && 'All user feedback'}
            {activeTab === 'negative' && 'Negative feedback only'}
            {activeTab === 'needs_faq' && 'Feedback that would benefit from FAQ creation'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : !feedbackData || feedbackData.feedback_items.length === 0 ? (
            <div className="text-center py-12">
              <MessageCircle className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
              <h3 className="text-lg font-semibold">No Feedback Found</h3>
              <p className="text-muted-foreground">No feedback matches your current filters.</p>
            </div>
          ) : (
            <div className="space-y-4">
              {feedbackData.feedback_items.map((feedback) => (
                <Card key={feedback.message_id} className="border-l-4 border-l-gray-200">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 space-y-2">
                        <div className="flex items-center space-x-2">
                          {feedback.is_positive ? (
                            <ThumbsUp className="h-5 w-5 text-primary" />
                          ) : (
                            <ThumbsDown className="h-5 w-5 text-red-500" />
                          )}
                          <span className="text-sm text-muted-foreground">
                            {formatDate(feedback.timestamp)}
                          </span>
                          {feedback.has_no_source_response && (
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                              No Source Available
                            </span>
                          )}
                        </div>

                        <div>
                          <span className="font-medium text-sm text-muted-foreground">Question:</span>
                          <p className="text-sm mt-1">{feedback.question}</p>
                        </div>

                        {feedback.explanation && (
                          <div>
                            <span className="font-medium text-sm text-muted-foreground">User Feedback:</span>
                            <p className="text-sm mt-1 text-red-700">{feedback.explanation}</p>
                          </div>
                        )}

                        {feedback.issues && feedback.issues.length > 0 && (
                          <div className="flex flex-wrap gap-1 mt-2">
                            {feedback.issues.map((issue, idx) => (
                              <span key={idx} className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getIssueColor(issue)}`}>
                                {issue.replace('_', ' ')}
                              </span>
                            ))}
                          </div>
                        )}

                        {feedback.is_negative && !feedback.is_processed && (
                          <div className="pt-1">
                            <Button
                              onClick={() => openCreateFAQ(feedback)}
                              size="sm"
                              variant="outline"
                            >
                              <PlusCircle className="h-4 w-4 mr-1" />
                              Create FAQ
                            </Button>
                          </div>
                        )}

                        {feedback.is_processed && feedback.faq_id && (
                          <div className="pt-1">
                            <span className="inline-flex items-center px-3 py-1.5 rounded-md text-xs font-medium bg-green-100 text-green-800 border border-green-200">
                              ✓ FAQ Created
                            </span>
                          </div>
                        )}
                      </div>

                      <div className="flex items-center gap-1 ml-4">
                        <Button
                          onClick={() => openFeedbackDetail(feedback)}
                          variant="ghost"
                          size="icon"
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button
                          onClick={() => openDeleteConfirmation(feedback)}
                          variant="ghost"
                          size="icon"
                        >
                          <Trash2 className="h-4 w-4 text-red-500" />
                        </Button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}

              {/* Pagination */}
              {feedbackData && feedbackData.total_pages > 1 && (
                <div className="flex items-center justify-between px-2 py-4">
                  <div className="flex items-center space-x-6 lg:space-x-8">
                    <div className="flex items-center space-x-2">
                      <p className="text-sm font-medium">
                        Showing {((filters.page - 1) * filters.page_size) + 1} to {Math.min(filters.page * filters.page_size, feedbackData.total_count)} of {feedbackData.total_count} entries
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleFilterChange('page', Math.max(1, filters.page - 1))}
                      disabled={filters.page <= 1}
                    >
                      Previous
                    </Button>
                    <div className="flex items-center space-x-1">
                      {Array.from({ length: Math.min(5, feedbackData.total_pages) }, (_, i) => {
                        const pageNum = Math.max(1, Math.min(feedbackData.total_pages - 4, filters.page - 2)) + i;
                        if (pageNum > feedbackData.total_pages) return null;
                        return (
                          <Button
                            key={pageNum}
                            variant={pageNum === filters.page ? "default" : "outline"}
                            size="sm"
                            onClick={() => handleFilterChange('page', pageNum)}
                          >
                            {pageNum}
                          </Button>
                        );
                      })}
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleFilterChange('page', Math.min(feedbackData.total_pages, filters.page + 1))}
                      disabled={filters.page >= feedbackData.total_pages}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Feedback Detail Dialog */}
      <Dialog open={showFeedbackDetail} onOpenChange={setShowFeedbackDetail}>
        <DialogContent className="max-w-4xl max-h-[80vh] overflow-y-auto [&>button]:hidden">
          <DialogHeader className="relative">
            <DialogClose asChild>
              <Button
                variant="outline"
                size="sm"
                className="absolute right-0 top-0 h-8 w-8 p-0"
                aria-label="Close dialog"
              >
                <X className="h-4 w-4" />
              </Button>
            </DialogClose>
            <DialogTitle>Feedback Details</DialogTitle>
            <DialogDescription>
              Complete feedback information and response details
            </DialogDescription>
          </DialogHeader>
          {selectedFeedback && (
            <div className="space-y-4">
              {/* Basic Info Grid */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                <div>
                  <span className="font-medium text-card-foreground font-medium">Rating:</span>
                  <div className="flex items-center space-x-2 mt-1">
                    {selectedFeedback.is_positive ? (
                      <ThumbsUp className="h-4 w-4 text-primary" />
                    ) : (
                      <ThumbsDown className="h-4 w-4 text-red-500" />
                    )}
                    <span>{selectedFeedback.is_positive ? 'Positive' : 'Negative'}</span>
                  </div>
                </div>
                <div>
                  <span className="font-medium text-card-foreground font-medium">Message ID:</span>
                  <p className="mt-1">{selectedFeedback.message_id}</p>
                </div>
                <div>
                  <span className="font-medium text-card-foreground font-medium">Timestamp:</span>
                  <p className="mt-1">{formatDate(selectedFeedback.timestamp)}</p>
                </div>
                {selectedFeedback.has_no_source_response && (
                  <div>
                    <span className="font-medium text-card-foreground font-medium">No Source Available:</span>
                    <div className="mt-1">
                      <span className="inline-flex items-center px-2 py-1 rounded-full text-xs font-medium bg-orange-100 text-orange-800">
                        Yes
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* Performance Metrics */}
              {selectedFeedback.metadata && (
                <div className="grid grid-cols-2 gap-4 text-sm">
                  {selectedFeedback.metadata.response_time && (
                    <div>
                      <span className="font-medium text-card-foreground font-medium">Response Time:</span>
                      <p className="mt-1">{selectedFeedback.metadata.response_time.toFixed(2)}s</p>
                    </div>
                  )}
                </div>
              )}

              {/* Question & Answer */}
              <div>
                <span className="font-medium text-card-foreground font-medium">Question:</span>
                <p className="mt-1 p-3 bg-accent rounded text-card-foreground">{selectedFeedback.question}</p>
              </div>

              <div>
                <span className="font-medium text-card-foreground font-medium">Answer:</span>
                <p className="mt-1 p-3 bg-accent rounded text-card-foreground">{selectedFeedback.answer}</p>
              </div>

              {/* User Feedback */}
              {selectedFeedback.explanation && (
                <div>
                  <span className="font-medium text-card-foreground font-medium">User Feedback:</span>
                  <p className="mt-1 p-3 bg-red-50 rounded border-l-4 border-red-200 text-red-900">{selectedFeedback.explanation}</p>
                </div>
              )}

              {/* Conversation History */}
              {selectedFeedback.conversation_history && selectedFeedback.conversation_history.length > 1 && (
                <ConversationHistory messages={selectedFeedback.conversation_history} />
              )}

              {/* Issues */}
              {selectedFeedback.issues && selectedFeedback.issues.length > 0 && (
                <div>
                  <span className="font-medium text-card-foreground font-medium">Issues Identified:</span>
                  <div className="flex flex-wrap gap-2 mt-2">
                    {selectedFeedback.issues.map((issue, idx) => (
                      <span key={idx} className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getIssueColor(issue)}`}>
                        {issue.replace('_', ' ')}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Sources Used */}
              {selectedFeedback.sources_used && selectedFeedback.sources_used.length > 0 && (
                <div>
                  <span className="font-medium text-card-foreground font-medium">Sources Used:</span>
                  <div className="mt-1 space-y-2">
                    {selectedFeedback.sources_used.map((source, idx) => (
                      <div key={idx} className="p-3 border rounded-lg bg-blue-50">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-medium text-blue-900">{source.title}</span>
                          <span className="px-2 py-1 bg-blue-200 text-blue-800 rounded text-xs font-medium">
                            {source.type}
                          </span>
                        </div>
                        <div className="text-card-foreground font-medium text-sm">{source.content.substring(0, 300)}...</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Available Sources (if different from sources_used) */}
              {selectedFeedback.sources && selectedFeedback.sources.length > 0 && (
                <div>
                  <span className="font-medium text-card-foreground font-medium">Available Sources:</span>
                  <div className="mt-1 space-y-2">
                    {selectedFeedback.sources.map((source, idx) => (
                      <div key={idx} className="p-3 border rounded-lg bg-accent">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="font-medium text-card-foreground">{source.title}</span>
                          <span className="px-2 py-1 bg-muted text-muted-foreground rounded text-xs font-medium">
                            {source.type}
                          </span>
                        </div>
                        <div className="text-muted-foreground text-sm">{source.content.substring(0, 200)}...</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Create FAQ Dialog */}
      <Dialog open={showCreateFAQ} onOpenChange={setShowCreateFAQ}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Create FAQ from Feedback</DialogTitle>
            <DialogDescription>
              Transform this negative feedback into a helpful FAQ entry
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleCreateFAQ}>
            <div className="space-y-4">
              <div>
                <Label>Question</Label>
                <Input
                  value={faqForm.suggested_question}
                  onChange={(e) => setFaqForm({...faqForm, suggested_question: e.target.value})}
                  required
                />
              </div>
              <div>
                <Label>Answer</Label>
                <Textarea
                  rows={6}
                  placeholder="Provide an improved, accurate answer..."
                  value={faqForm.suggested_answer}
                  onChange={(e) => setFaqForm({...faqForm, suggested_answer: e.target.value})}
                  required
                />
              </div>
              <div>
                <Label>Category</Label>
                <Select
                  value={isCustomCategory ? 'custom' : faqForm.category}
                  onValueChange={(value) => {
                    if (value === 'custom') {
                      setIsCustomCategory(true);
                      setFaqForm({...faqForm, category: customCategory});
                    } else {
                      setIsCustomCategory(false);
                      setFaqForm({...faqForm, category: value});
                    }
                  }}
                  required
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a category" />
                  </SelectTrigger>
                  <SelectContent>
                    {predefinedCategories.map((cat) => (
                      <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                    ))}
                    <SelectItem value="custom">+ Add Custom Category</SelectItem>
                  </SelectContent>
                </Select>
                {isCustomCategory && (
                  <Input
                    className="mt-2"
                    placeholder="Enter custom category..."
                    value={customCategory}
                    onChange={(e) => {
                      setCustomCategory(e.target.value);
                      setFaqForm({...faqForm, category: e.target.value});
                    }}
                    required
                  />
                )}
              </div>
              {faqForm.additional_notes && (
                <div>
                  <Label>User Feedback</Label>
                  <div className="mt-1 p-3 bg-red-50 rounded border border-red-200 text-red-900 text-sm">
                    {faqForm.additional_notes}
                  </div>
                </div>
              )}
              {selectedFeedbackForFAQ?.conversation_history && selectedFeedbackForFAQ.conversation_history.length > 1 && (
                <ConversationHistory messages={selectedFeedbackForFAQ.conversation_history} />
              )}
            </div>
            <DialogFooter className="mt-6">
              <Button type="button" variant="outline" onClick={() => {
                setShowCreateFAQ(false);
                setIsCustomCategory(false);
                setCustomCategory('');
              }}>
                Cancel
              </Button>
              <Button type="submit" disabled={isSubmittingFAQ}>
                {isSubmittingFAQ && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create FAQ
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={showDeleteConfirm} onOpenChange={setShowDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Feedback</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this feedback entry? This action cannot be undone.
              {feedbackToDelete && (
                <div className="mt-4 p-3 bg-accent rounded border border-border">
                  <p className="text-sm font-medium text-card-foreground mb-1">Question:</p>
                  <p className="text-sm text-muted-foreground">{feedbackToDelete.question.substring(0, 100)}{feedbackToDelete.question.length > 100 ? '...' : ''}</p>
                </div>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => {
              setShowDeleteConfirm(false);
              setFeedbackToDelete(null);
            }}>
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteFeedback}
              disabled={isDeleting}
              className="bg-red-600 hover:bg-red-700 focus:ring-red-600 text-white"
            >
              {isDeleting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
