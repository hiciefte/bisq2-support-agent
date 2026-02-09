"use client"

import { useState, useEffect, useCallback, useRef, useMemo, FormEvent } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogClose } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DatePicker } from "@/components/ui/date-picker";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import {
  Loader2,
  MessageCircle,
  ThumbsDown,
  ThumbsUp,
  Filter,
  PlusCircle,
  Eye,
  RotateCcw,
  Download,
  X,
  Trash2,
  Search,
  ChevronLeft,
  ChevronRight,
  AlertCircle
} from 'lucide-react';
import { format } from 'date-fns';
import { makeAuthenticatedRequest } from '@/lib/auth';
import { ConversationHistory } from '@/components/admin/ConversationHistory';
import { ConversationMessage } from '@/types/feedback';
import { useFeedbackDeletion } from '@/hooks/useFeedbackDeletion';

interface FeedbackItem {
  message_id: string;
  question: string;
  answer: string;
  rating: number;
  timestamp: string;
  channel?: string;
  feedback_method?: string;
  reaction_emoji?: string;
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
  // Index signature for compatibility with useFeedbackDeletion hook
  [key: string]: unknown;
}

interface FeedbackListResponse {
  feedback_items: FeedbackItem[];
  total_count: number;
  page: number;
  page_size: number;
  total_pages: number;
  filters_applied: Record<string, string | number | boolean | string[]>;
}

interface ChannelMethodStats {
  total: number;
  positive: number;
  negative: number;
}

interface FeedbackStats {
  total_feedback: number;
  positive_count: number;
  negative_count: number;
  helpful_rate: number;
  common_issues: Record<string, number>;
  recent_negative_count: number;
  needs_faq_count: number;
  source_effectiveness: Record<string, { count: number; helpful_rate: number }>;
  feedback_by_month: Record<string, number>;
  feedback_by_channel?: Record<string, ChannelMethodStats>;
  feedback_by_method?: Record<string, ChannelMethodStats>;
}

// Custom hook for debounced values
function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value);
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handler);
  }, [value, delay]);
  return debouncedValue;
}

export default function ManageFeedbackPage() {
  // Authentication state - handled by SecureAuth wrapper at layout level

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
    channel: 'all',
    feedback_method: 'all',
    issues: [] as string[],
    source_types: [] as string[],
    search_text: '',
    needs_faq: false,
    page: 1,
    page_size: 25,
    sort_by: 'newest'
  });

  // Debounce search text to avoid excessive API calls
  const debouncedSearchText = useDebounce(filters.search_text, 300);

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

  // Delete feedback hook
  const {
    showDeleteConfirm,
    feedbackToDelete,
    isDeleting,
    error: deleteError,
    openDeleteConfirmation,
    closeDeleteConfirmation,
    handleDelete,
  } = useFeedbackDeletion(async () => {
    await fetchData();
    setError(null);
  });

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

  // Compute active filter count and boolean
  const activeFilterCount = useMemo(() => {
    return [
      filters.search_text,
      filters.rating !== 'all',
      filters.date_from,
      filters.date_to,
      filters.channel !== 'all',
      filters.feedback_method !== 'all',
      filters.issues.length > 0,
      filters.source_types.length > 0,
      filters.needs_faq
    ].filter(Boolean).length;
  }, [filters]);

  const hasActiveFilters = activeFilterCount > 0;

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
    // Adjust filters based on active tab, using debounced search text
    const adjustedFilters = { ...filters, search_text: debouncedSearchText };
    if (activeTab === 'negative') {
      adjustedFilters.rating = 'negative';
    } else if (activeTab === 'needs_faq') {
      adjustedFilters.needs_faq = true;
    }

    const params = new URLSearchParams();
    Object.entries(adjustedFilters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '' && value !== 'all' &&
          !(Array.isArray(value) && value.length === 0) && value !== false) {
        if (Array.isArray(value)) {
          params.append(key, value.join(','));
        } else if (value instanceof Date) {
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
  }, [filters, activeTab, debouncedSearchText]);

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

  // Note: Login/logout handlers are managed by SecureAuth wrapper at layout level

  const handleFilterChange = (key: string, value: string | number | boolean | Date | undefined | string[]) => {
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
      channel: 'all',
      feedback_method: 'all',
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
    } catch {
      const errorText = 'An unexpected error occurred while creating the FAQ.';
      setError(errorText);
    } finally {
      setIsSubmittingFAQ(false);
    }
  };


  const exportFeedback = async () => {
    if (!feedbackData || feedbackData.feedback_items.length === 0) return;

    // Helper function to escape CSV values properly
    const escapeCSV = (value: string | number | boolean | null | undefined): string => {
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
    const colors: Record<string, string> = {
      'inaccurate': 'bg-red-500/15 text-red-400 border border-red-500/20',
      'too_technical': 'bg-yellow-500/15 text-yellow-400 border border-yellow-500/20',
      'too_verbose': 'bg-blue-500/15 text-blue-400 border border-blue-500/20',
      'confusing': 'bg-purple-500/15 text-purple-400 border border-purple-500/20',
      'not_helpful': 'bg-muted text-muted-foreground border border-border'
    };
    return colors[issue] || 'bg-muted text-muted-foreground border border-border';
  };

  const getChannelBadge = (channel?: string) => {
    const badges: Record<string, { label: string; className: string }> = {
      'web': { label: 'Web', className: 'bg-blue-500/15 text-blue-400 border border-blue-500/25' },
      'matrix': { label: 'Matrix', className: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25' },
      'bisq2': { label: 'Bisq2', className: 'bg-orange-500/15 text-orange-400 border border-orange-500/25' },
    };
    return badges[channel || 'web'] || { label: channel || 'web', className: 'bg-muted text-muted-foreground border border-border' };
  };

  // Authentication is handled by SecureAuth wrapper in layout

  return (
    <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Feedback Management</h1>
            <p className="text-sm text-muted-foreground mt-1">Monitor and analyze user feedback for the support assistant</p>
          </div>
          <div className="flex gap-2">
              <Button onClick={() => setShowFilters(!showFilters)} variant="outline" size="sm" className={`border-border transition-colors ${showFilters ? 'bg-accent border-primary' : 'hover:border-primary'}`}>
                <Filter className="mr-2 h-4 w-4" />
                Filters
                {hasActiveFilters && (
                  <Badge variant="secondary" className="ml-2 h-5 w-5 p-0 flex items-center justify-center text-xs rounded-full">
                    {activeFilterCount}
                  </Badge>
                )}
              </Button>
              <Button onClick={exportFeedback} variant="outline" size="sm" className="border-border hover:border-primary" disabled={!feedbackData || feedbackData.feedback_items.length === 0}>
                <Download className="mr-2 h-4 w-4" />
                Export
              </Button>
            </div>
        </div>

        {/* Error Display */}
        {error && (
          <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg" role="alert">
            <AlertCircle className="h-4 w-4 shrink-0" />
            <span className="text-sm">{error}</span>
            <button onClick={() => setError(null)} className="ml-auto text-red-400/60 hover:text-red-400 transition-colors">
              <X className="h-4 w-4" />
            </button>
          </div>
        )}


        {/* Tabs */}
        <div className="bg-card rounded-lg border border-border">
          <div className="flex space-x-1 px-4 pt-3 pb-0">
            {([
              { key: 'all' as const, label: 'All Feedback', count: stats?.total_feedback },
              { key: 'negative' as const, label: 'Negative Only', count: stats?.negative_count },
              { key: 'needs_faq' as const, label: 'Needs FAQ', count: stats?.needs_faq_count },
            ]).map(tab => (
              <button
                key={tab.key}
                className={`px-4 py-2.5 font-medium text-sm rounded-t-lg transition-all relative ${
                  activeTab === tab.key
                    ? 'text-primary'
                    : 'text-muted-foreground hover:text-card-foreground'
                }`}
                onClick={() => setActiveTab(tab.key)}
              >
                <span className="flex items-center gap-2">
                  {tab.label}
                  {tab.count !== undefined && tab.count > 0 && (
                    <span className={`text-xs px-1.5 py-0.5 rounded-full ${
                      activeTab === tab.key
                        ? 'bg-primary/15 text-primary'
                        : 'bg-muted text-muted-foreground'
                    }`}>
                      {tab.count}
                    </span>
                  )}
                </span>
                {activeTab === tab.key && (
                  <span className="absolute bottom-0 left-2 right-2 h-0.5 bg-primary rounded-full" />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* Channel Breakdown Stats */}
        {stats && stats.feedback_by_channel && Object.keys(stats.feedback_by_channel).length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-muted-foreground">Feedback by Channel</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {Object.entries(stats.feedback_by_channel).map(([channel, data]) => {
                    const badge = getChannelBadge(channel);
                    const rateNum = data.total > 0 ? (data.positive / data.total) * 100 : 0;
                    const rate = rateNum.toFixed(0);
                    return (
                      <div key={channel} className="space-y-1.5">
                        <div className="flex items-center justify-between text-sm">
                          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${badge.className}`}>
                            {badge.label}
                          </span>
                          <div className="flex items-center gap-3 text-xs">
                            <span className="text-muted-foreground">{data.total}</span>
                            <span className="text-emerald-400 inline-flex items-center gap-0.5"><ThumbsUp className="h-3 w-3" />{data.positive}</span>
                            <span className="text-red-400 inline-flex items-center gap-0.5"><ThumbsDown className="h-3 w-3" />{data.negative}</span>
                            <span className="font-semibold text-card-foreground tabular-nums">{rate}%</span>
                          </div>
                        </div>
                        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary/60 rounded-full transition-all duration-500"
                            style={{ width: `${rateNum}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-medium text-muted-foreground">Feedback by Method</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3">
                  {stats.feedback_by_method && Object.entries(stats.feedback_by_method).map(([method, data]) => {
                    const label = method === 'web_dialog' ? 'Web Dialog' : method === 'reaction' ? 'Reaction' : method;
                    const rateNum = data.total > 0 ? (data.positive / data.total) * 100 : 0;
                    const rate = rateNum.toFixed(0);
                    return (
                      <div key={method} className="space-y-1.5">
                        <div className="flex items-center justify-between text-sm">
                          <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-muted text-muted-foreground border border-border">
                            {label}
                          </span>
                          <div className="flex items-center gap-3 text-xs">
                            <span className="text-muted-foreground">{data.total}</span>
                            <span className="text-emerald-400 inline-flex items-center gap-0.5"><ThumbsUp className="h-3 w-3" />{data.positive}</span>
                            <span className="text-red-400 inline-flex items-center gap-0.5"><ThumbsDown className="h-3 w-3" />{data.negative}</span>
                            <span className="font-semibold text-card-foreground tabular-nums">{rate}%</span>
                          </div>
                        </div>
                        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                          <div
                            className="h-full bg-primary/60 rounded-full transition-all duration-500"
                            style={{ width: `${rateNum}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>
          </div>
        )}

        {/* Filters Panel */}
      <div className={`grid transition-all duration-300 ease-in-out ${showFilters ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}>
        <div className="overflow-hidden">
          <Card className="border-primary/20">
            <CardContent className="pt-5 pb-4 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                <div className="space-y-1.5 lg:col-span-2">
                  <Label className="text-xs text-muted-foreground">Search</Label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search questions, answers, feedback text..."
                      value={filters.search_text}
                      onChange={(e) => handleFilterChange('search_text', e.target.value)}
                      className="pl-9"
                    />
                    {filters.search_text && (
                      <button
                        onClick={() => handleFilterChange('search_text', '')}
                        className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Channel</Label>
                  <Select
                    value={filters.channel}
                    onValueChange={(value) => handleFilterChange('channel', value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="All channels" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Channels</SelectItem>
                      <SelectItem value="web">Web</SelectItem>
                      <SelectItem value="matrix">Matrix</SelectItem>
                      <SelectItem value="bisq2">Bisq2</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Feedback Method</Label>
                  <Select
                    value={filters.feedback_method}
                    onValueChange={(value) => handleFilterChange('feedback_method', value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="All methods" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Methods</SelectItem>
                      <SelectItem value="web_dialog">Web Dialog</SelectItem>
                      <SelectItem value="reaction">Reaction</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Date From</Label>
                  <DatePicker
                    value={filters.date_from}
                    onChange={(date) => handleFilterChange('date_from', date)}
                    placeholder="Select start date"
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs text-muted-foreground">Date To</Label>
                  <DatePicker
                    value={filters.date_to}
                    onChange={(date) => handleFilterChange('date_to', date)}
                    placeholder="Select end date"
                  />
                </div>
              </div>
              {hasActiveFilters && (
                <div className="flex items-center pt-1">
                  <Button onClick={resetFilters} variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground h-7 text-xs">
                    <RotateCcw className="mr-1.5 h-3 w-3" />
                    Reset all filters
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Feedback List */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">
                Feedback List
              </CardTitle>
              <CardDescription className="mt-0.5">
                {activeTab === 'all' && 'All user feedback'}
                {activeTab === 'negative' && 'Negative feedback requiring attention'}
                {activeTab === 'needs_faq' && 'Feedback that would benefit from FAQ creation'}
                {feedbackData && (
                  <span className="ml-1 tabular-nums">
                    -- {feedbackData.total_count} {feedbackData.total_count === 1 ? 'item' : 'items'}
                  </span>
                )}
              </CardDescription>
            </div>
            {/* Top pagination for quick navigation */}
            {feedbackData && feedbackData.total_pages > 1 && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <span className="tabular-nums">Page {filters.page} of {feedbackData.total_pages}</span>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {isLoading ? (
            /* Skeleton loading state */
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="border border-border rounded-lg p-4 animate-pulse">
                  <div className="flex items-center gap-2 mb-3">
                    <div className="h-4 w-4 bg-muted rounded-full" />
                    <div className="h-3 w-32 bg-muted rounded" />
                    <div className="h-4 w-12 bg-muted rounded-full" />
                  </div>
                  <div className="h-3 w-3/4 bg-muted rounded mb-2" />
                  <div className="h-3 w-1/2 bg-muted rounded" />
                </div>
              ))}
            </div>
          ) : !feedbackData || feedbackData.feedback_items.length === 0 ? (
            /* Enhanced empty state */
            <div className="text-center py-16">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-muted mb-4">
                <MessageCircle className="h-6 w-6 text-muted-foreground" />
              </div>
              <h3 className="text-base font-semibold mb-1">No feedback found</h3>
              <p className="text-sm text-muted-foreground mb-4 max-w-sm mx-auto">
                {hasActiveFilters
                  ? 'No feedback matches your current filters. Try adjusting or resetting them.'
                  : activeTab === 'negative'
                    ? 'No negative feedback recorded. That is a good sign.'
                    : activeTab === 'needs_faq'
                      ? 'No feedback currently needs FAQ creation.'
                      : 'No feedback has been submitted yet.'}
              </p>
              {hasActiveFilters && (
                <Button onClick={resetFilters} variant="outline" size="sm">
                  <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                  Reset filters
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              {feedbackData.feedback_items.map((feedback) => (
                <div
                  key={feedback.message_id}
                  className={`group relative border rounded-lg transition-colors hover:bg-accent/30 cursor-pointer ${
                    feedback.is_positive
                      ? 'border-l-2 border-l-primary/50 border-t border-r border-b border-border'
                      : 'border-l-2 border-l-red-500/50 border-t border-r border-b border-border'
                  }`}
                  onClick={() => openFeedbackDetail(feedback)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') openFeedbackDetail(feedback); }}
                >
                  <div className="p-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1 min-w-0 space-y-1.5">
                        {/* Meta row */}
                        <div className="flex items-center gap-2 flex-wrap">
                          {feedback.is_positive ? (
                            <ThumbsUp className="h-3.5 w-3.5 text-primary shrink-0" />
                          ) : (
                            <ThumbsDown className="h-3.5 w-3.5 text-red-400 shrink-0" />
                          )}
                          <span className="text-xs text-muted-foreground tabular-nums">
                            {formatDate(feedback.timestamp)}
                          </span>
                          {(() => {
                            const badge = getChannelBadge(feedback.channel);
                            return (
                              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${badge.className}`}>
                                {badge.label}
                              </span>
                            );
                          })()}
                          {feedback.feedback_method === 'reaction' && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/15 text-purple-400 border border-purple-500/20">
                              {feedback.reaction_emoji || 'Reaction'}
                            </span>
                          )}
                          {feedback.has_no_source_response && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-500/15 text-orange-400 border border-orange-500/20">
                              No Source
                            </span>
                          )}
                        </div>

                        {/* Question text */}
                        <p className="text-sm leading-relaxed line-clamp-2">{feedback.question}</p>

                        {/* User feedback text (if negative) */}
                        {feedback.explanation && (
                          <p className="text-xs text-red-400/80 line-clamp-1 mt-0.5">
                            &ldquo;{feedback.explanation}&rdquo;
                          </p>
                        )}

                        {/* Issue badges and action buttons row */}
                        <div className="flex items-center gap-2 flex-wrap pt-0.5">
                          {feedback.issues && feedback.issues.length > 0 && (
                            feedback.issues.map((issue, idx) => (
                              <span key={idx} className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${getIssueColor(issue)}`}>
                                {issue.replace('_', ' ')}
                              </span>
                            ))
                          )}

                          {feedback.is_processed && feedback.faq_id && (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/15 text-primary border border-primary/25">
                              FAQ Created
                            </span>
                          )}

                          {feedback.is_negative && !feedback.is_processed && (
                            <Button
                              onClick={(e) => { e.stopPropagation(); openCreateFAQ(feedback); }}
                              size="sm"
                              variant="ghost"
                              className="h-6 px-2 text-xs text-muted-foreground hover:text-foreground"
                            >
                              <PlusCircle className="h-3 w-3 mr-1" />
                              Create FAQ
                            </Button>
                          )}
                        </div>
                      </div>

                      {/* Action buttons - visible on hover only */}
                      <div className="flex items-center gap-0.5 ml-3 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-150 shrink-0">
                        <Button
                          onClick={(e) => { e.stopPropagation(); openFeedbackDetail(feedback); }}
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-foreground"
                          aria-label="View feedback details"
                        >
                          <Eye className="h-3.5 w-3.5" />
                        </Button>
                        <Button
                          onClick={(e) => { e.stopPropagation(); openDeleteConfirmation(feedback); }}
                          variant="ghost"
                          size="icon"
                          className="h-8 w-8 text-muted-foreground hover:text-red-400"
                          aria-label="Delete feedback"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}

              {/* Pagination */}
              {feedbackData && feedbackData.total_pages > 1 && (
                <div className="flex items-center justify-between pt-4 border-t border-border mt-2">
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {((filters.page - 1) * filters.page_size) + 1}--{Math.min(filters.page * filters.page_size, feedbackData.total_count)} of {feedbackData.total_count}
                  </p>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleFilterChange('page', Math.max(1, filters.page - 1))}
                      disabled={filters.page <= 1}
                      aria-label="Previous page"
                    >
                      <ChevronLeft className="h-4 w-4" />
                    </Button>
                    {Array.from({ length: Math.min(5, feedbackData.total_pages) }, (_, i) => {
                      const pageNum = Math.max(1, Math.min(feedbackData.total_pages - 4, filters.page - 2)) + i;
                      if (pageNum > feedbackData.total_pages) return null;
                      return (
                        <Button
                          key={pageNum}
                          variant={pageNum === filters.page ? "default" : "ghost"}
                          size="icon"
                          className={`h-8 w-8 text-xs ${pageNum === filters.page ? '' : 'text-muted-foreground'}`}
                          onClick={() => handleFilterChange('page', pageNum)}
                        >
                          {pageNum}
                        </Button>
                      );
                    })}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleFilterChange('page', Math.min(feedbackData.total_pages, filters.page + 1))}
                      disabled={filters.page >= feedbackData.total_pages}
                      aria-label="Next page"
                    >
                      <ChevronRight className="h-4 w-4" />
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
        <DialogContent className="max-w-4xl max-h-[85vh] overflow-y-auto [&>button]:hidden">
          <DialogHeader className="relative pb-3">
            <DialogClose asChild>
              <Button
                variant="ghost"
                size="sm"
                className="absolute right-0 top-0 h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
                aria-label="Close dialog"
              >
                <X className="h-4 w-4" />
              </Button>
            </DialogClose>
            <DialogTitle className="flex items-center gap-2">
              Feedback Details
              {selectedFeedback && (
                selectedFeedback.is_positive ? (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-primary/15 text-primary">
                    <ThumbsUp className="h-3 w-3" /> Positive
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-red-500/15 text-red-400">
                    <ThumbsDown className="h-3 w-3" /> Negative
                  </span>
                )
              )}
            </DialogTitle>
            <DialogDescription>
              Full feedback record and response context
            </DialogDescription>
          </DialogHeader>
          {selectedFeedback && (
            <div className="space-y-5">
              {/* Metadata bar */}
              <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground pb-3 border-b border-border">
                <span className="tabular-nums">{formatDate(selectedFeedback.timestamp)}</span>
                <span className="text-border">|</span>
                {(() => {
                  const badge = getChannelBadge(selectedFeedback.channel);
                  return (
                    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${badge.className}`}>
                      {badge.label}
                    </span>
                  );
                })()}
                {selectedFeedback.feedback_method === 'reaction' && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/15 text-purple-400 border border-purple-500/20">
                    {selectedFeedback.reaction_emoji || 'Reaction'}
                  </span>
                )}
                {selectedFeedback.has_no_source_response && (
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-500/15 text-orange-400 border border-orange-500/20">
                    No Source
                  </span>
                )}
                {selectedFeedback.metadata?.response_time && (
                  <>
                    <span className="text-border">|</span>
                    <span className="tabular-nums">{selectedFeedback.metadata.response_time.toFixed(2)}s response</span>
                  </>
                )}
                <span className="text-border">|</span>
                <span className="font-mono text-[10px] text-muted-foreground/60 truncate max-w-[200px]" title={selectedFeedback.message_id}>
                  {selectedFeedback.message_id}
                </span>
              </div>

              {/* Question & Answer */}
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Question</span>
                <p className="text-sm p-3 bg-accent rounded-lg text-card-foreground leading-relaxed">{selectedFeedback.question}</p>
              </div>

              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Answer</span>
                <div className="text-sm p-3 bg-accent rounded-lg text-card-foreground leading-relaxed whitespace-pre-wrap">{selectedFeedback.answer}</div>
              </div>

              {/* User Feedback */}
              {selectedFeedback.explanation && (
                <div className="space-y-1">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">User Feedback</span>
                  <p className="text-sm p-3 bg-red-500/10 rounded-lg border-l-2 border-red-500/40 text-red-400 leading-relaxed">{selectedFeedback.explanation}</p>
                </div>
              )}

              {/* Conversation History */}
              {selectedFeedback.conversation_history && selectedFeedback.conversation_history.length > 1 && (
                <ConversationHistory messages={selectedFeedback.conversation_history} />
              )}

              {/* Issues */}
              {selectedFeedback.issues && selectedFeedback.issues.length > 0 && (
                <div className="space-y-2">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Issues Identified</span>
                  <div className="flex flex-wrap gap-1.5">
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
                <div className="space-y-2">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Sources Used</span>
                  <div className="space-y-2">
                    {selectedFeedback.sources_used.map((source, idx) => (
                      <div key={idx} className="p-3 border border-border rounded-lg bg-accent/50">
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="font-medium text-sm text-card-foreground">{source.title}</span>
                          <span className="px-2 py-0.5 bg-blue-500/15 text-blue-400 border border-blue-500/20 rounded text-[10px] font-medium">
                            {source.type}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">{source.content.substring(0, 300)}{source.content.length > 300 ? '...' : ''}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Available Sources (if different from sources_used) */}
              {selectedFeedback.sources && selectedFeedback.sources.length > 0 && (
                <div className="space-y-2">
                  <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Available Sources</span>
                  <div className="space-y-2">
                    {selectedFeedback.sources.map((source, idx) => (
                      <div key={idx} className="p-3 border border-border rounded-lg bg-accent/30">
                        <div className="flex items-center gap-2 mb-1.5">
                          <span className="font-medium text-sm text-card-foreground">{source.title}</span>
                          <span className="px-2 py-0.5 bg-muted text-muted-foreground border border-border rounded text-[10px] font-medium">
                            {source.type}
                          </span>
                        </div>
                        <p className="text-xs text-muted-foreground leading-relaxed">{source.content.substring(0, 200)}{source.content.length > 200 ? '...' : ''}</p>
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
                  <div className="mt-1 p-3 bg-red-500/10 rounded-lg border border-red-500/20 text-red-400 text-sm leading-relaxed">
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
      <AlertDialog open={showDeleteConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Feedback</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this feedback entry? This action cannot be undone.
              {feedbackToDelete && (
                <div className="mt-4 p-3 bg-accent rounded border border-border">
                  <p className="text-sm font-medium text-card-foreground mb-1">Message ID: {feedbackToDelete.message_id}</p>
                  <p className="text-sm font-medium text-card-foreground mb-1">Question:</p>
                  <p className="text-sm text-muted-foreground">{feedbackToDelete.question.substring(0, 100)}{feedbackToDelete.question.length > 100 ? '...' : ''}</p>
                </div>
              )}
              {deleteError && (
                <div className="mt-4 p-3 bg-red-500/10 rounded border border-red-500/50">
                  <p className="text-sm text-red-600">{deleteError}</p>
                </div>
              )}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel
              onClick={closeDeleteConfirmation}
              disabled={isDeleting}
            >
              Cancel
            </AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDelete}
              disabled={isDeleting}
              className="bg-red-600 hover:bg-red-700 focus:ring-red-600 text-white"
              aria-label="Confirm delete feedback"
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
