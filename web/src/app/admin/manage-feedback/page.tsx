"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogClose } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DatePicker } from "@/components/ui/date-picker";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
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
  AlertCircle,
  Bot,
  Check,
  Clock,
  Pencil,
  ChevronDown,
  User
} from 'lucide-react';
import { format } from 'date-fns';
import { makeAuthenticatedRequest } from '@/lib/auth';
import { ConversationHistory } from '@/components/admin/ConversationHistory';
import { ConversationMessage } from '@/types/feedback';
import { useFeedbackDeletion } from '@/hooks/useFeedbackDeletion';
import { MarkdownContent } from "@/components/chat/components/markdown-content";
import { SourceBadges } from "@/components/chat/components/source-badges";
import type { Source } from "@/components/chat/types/chat.types";
import {
  FAQ_CATEGORIES,
  FAQ_PROTOCOL_OPTIONS,
  inferFaqMetadata,
  type FAQProtocol,
} from "@/lib/faq-metadata";

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
  sources?: FeedbackSource[];
  sources_used?: FeedbackSource[];
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

interface FeedbackSource {
  title: string;
  type: string;
  content: string;
  url?: string | null;
  section?: string | null;
  similarity_score?: number;
  relevance_score?: number;
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

interface EscalationMetrics {
  total_routing_decisions: number;
  auto_send_count: number;
  queue_medium_count: number;
  needs_human_count: number;
  escalation_rate: number;
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
  const [escalationMetrics, setEscalationMetrics] = useState<EscalationMetrics | null>(null);
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

  // Stable filter payload for API calls; search_text only updates after debounce.
  const stableFilters = useMemo(
    () => ({
      rating: filters.rating,
      date_from: filters.date_from,
      date_to: filters.date_to,
      channel: filters.channel,
      feedback_method: filters.feedback_method,
      issues: filters.issues,
      source_types: filters.source_types,
      search_text: debouncedSearchText,
      needs_faq: filters.needs_faq,
      page: filters.page,
      page_size: filters.page_size,
      sort_by: filters.sort_by,
    }),
    [
      debouncedSearchText,
      filters.rating,
      filters.date_from,
      filters.date_to,
      filters.channel,
      filters.feedback_method,
      filters.issues,
      filters.source_types,
      filters.needs_faq,
      filters.page,
      filters.page_size,
      filters.sort_by,
    ],
  );

  // UI state
  const [activeTab, setActiveTab] = useState<'all' | 'negative' | 'needs_faq'>('needs_faq');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [showFeedbackDetail, setShowFeedbackDetail] = useState(false);
  const [detailPhase, setDetailPhase] = useState<"review" | "faq">("review");

  // FAQ creation state
  const [faqForm, setFaqForm] = useState({
    message_id: '',
    suggested_question: '',
    suggested_answer: '',
    category: '',
    protocol: 'all' as FAQProtocol,
    additional_notes: ''
  });
  const [isSubmittingFAQ, setIsSubmittingFAQ] = useState(false);
  const [customCategory, setCustomCategory] = useState('');
  const [isCustomCategory, setIsCustomCategory] = useState(false);
  const [isEditingFaqAnswer, setIsEditingFaqAnswer] = useState(false);
  const faqAnswerTextareaRef = useRef<HTMLTextAreaElement | null>(null);

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

  useEffect(() => {
    if (!isEditingFaqAnswer) return;
    requestAnimationFrame(() => {
      if (!faqAnswerTextareaRef.current) return;
      faqAnswerTextareaRef.current.focus();
      faqAnswerTextareaRef.current.style.height = "auto";
      faqAnswerTextareaRef.current.style.height = `${faqAnswerTextareaRef.current.scrollHeight}px`;
    });
  }, [isEditingFaqAnswer, showFeedbackDetail, detailPhase]);

  const fetchFeedbackList = useCallback(async () => {
    // Adjust filters based on active tab, using debounced search text
    const adjustedFilters = { ...stableFilters };
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

      if (data.total_pages > 0 && stableFilters.page > data.total_pages) {
        setFilters(prev => (
          prev.page > data.total_pages
            ? { ...prev, page: data.total_pages }
            : prev
        ));
        return;
      }

      if (data.total_pages === 0 && stableFilters.page !== 1) {
        setFilters(prev => (prev.page !== 1 ? { ...prev, page: 1 } : prev));
        return;
      }

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
  }, [stableFilters, activeTab]);

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

  const fetchEscalationMetrics = useCallback(async () => {
    try {
      const response = await makeAuthenticatedRequest('/admin/dashboard/overview?period=30d');
      if (response.ok) {
        const data = await response.json();
        if (data.escalation_metrics) {
          setEscalationMetrics(data.escalation_metrics);
        }
      }
    } catch {
      // Non-critical: escalation metrics are supplementary
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
        fetchStats(),
        fetchEscalationMetrics()
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
  }, [fetchFeedbackList, fetchStats, fetchEscalationMetrics]);

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
    setFilters((prev) => {
      const nextFilters = {
        ...prev,
        [key]: value,
      };

      if (key !== "page") {
        nextFilters.page = 1;
      }

      return nextFilters;
    });
  };

  const handlePageChange = (page: number) => {
    setFilters((prev) => ({
      ...prev,
      page,
    }));
  };

  const handleTabChange = (tab: 'all' | 'negative' | 'needs_faq') => {
    setActiveTab(tab);
    setFilters(prev => ({ ...prev, page: 1 }));
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

  const initializeFaqDraft = (feedback: FeedbackItem) => {
    const inferred = inferFaqMetadata({
      question: feedback.question,
      answer: feedback.answer,
    });
    setFaqForm({
      message_id: feedback.message_id,
      suggested_question: feedback.question,
      suggested_answer: feedback.answer || '',
      category: inferred.category,
      protocol: inferred.protocol,
      additional_notes: feedback.explanation || '',
    });
    setIsCustomCategory(false);
    setCustomCategory('');
    setIsEditingFaqAnswer(true);
  };

  const closeFeedbackDetailDialog = () => {
    setShowFeedbackDetail(false);
    setDetailPhase("review");
    setSelectedFeedback(null);
    setIsEditingFaqAnswer(false);
  };

  const openFeedbackDetail = async (feedback: FeedbackItem) => {
    const fullFeedback = await fetchFullFeedbackDetails(feedback);
    setSelectedFeedback(fullFeedback);
    initializeFaqDraft(fullFeedback);
    setDetailPhase("review");
    setShowFeedbackDetail(true);
  };

  const openCreateFAQ = async (feedback: FeedbackItem) => {
    const fullFeedback = await fetchFullFeedbackDetails(feedback);
    setSelectedFeedback(fullFeedback);
    initializeFaqDraft(fullFeedback);
    setDetailPhase("faq");
    setShowFeedbackDetail(true);
  };

  const handleCreateFAQ = async () => {
    if (
      !faqForm.suggested_question.trim() ||
      !faqForm.suggested_answer.trim() ||
      !faqForm.category.trim()
    ) {
      setError("Question, answer, category, and protocol are required to publish FAQ.");
      return;
    }
    const normalized = inferFaqMetadata({
      question: faqForm.suggested_question,
      answer: faqForm.suggested_answer,
      category: faqForm.category,
      protocol: faqForm.protocol,
    });
    setIsSubmittingFAQ(true);
    try {
      const response = await makeAuthenticatedRequest('/admin/feedback/create-faq', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ...faqForm,
          category: normalized.category,
          protocol: normalized.protocol,
        }),
      });

      if (response.ok) {
        closeFeedbackDetailDialog();
        setFaqForm({
          message_id: '',
          suggested_question: '',
          suggested_answer: '',
          category: '',
          protocol: 'all',
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

  const handleFeedbackDetailOpenChange = (open: boolean) => {
    if (!open) {
      closeFeedbackDetailDialog();
      return;
    }
    setShowFeedbackDetail(true);
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

  const toChatSource = useCallback((source: FeedbackSource): Source => ({
    title: source.title || "Untitled source",
    type: (source.type || "").toLowerCase() === "wiki" ? "wiki" : "faq",
    content: source.content || "",
    url: source.url || undefined,
    section: source.section || undefined,
    similarity_score: typeof source.similarity_score === "number"
      ? source.similarity_score
      : typeof source.relevance_score === "number"
        ? source.relevance_score
        : undefined,
  }), []);

  const selectedSourcesUsed = useMemo(
    () => (selectedFeedback?.sources_used || []).map(toChatSource),
    [selectedFeedback, toChatSource],
  );

  const selectedSourcesAvailable = useMemo(
    () => (selectedFeedback?.sources || []).map(toChatSource),
    [selectedFeedback, toChatSource],
  );

  const faqDraftSource = useMemo(() => {
    const sources = selectedFeedback?.sources_used || selectedFeedback?.sources || [];
    if (sources.length === 0) return [] as Source[];
    return sources.map(toChatSource);
  }, [selectedFeedback, toChatSource]);

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

        {/* Escalation Rate Card */}
        {escalationMetrics && escalationMetrics.total_routing_decisions > 0 && (
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Escalation Rate</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="flex items-center justify-between mb-3">
                <div className={cn(
                  "text-3xl font-semibold tracking-tight tabular-nums",
                  escalationMetrics.escalation_rate >= 5 && escalationMetrics.escalation_rate <= 15
                    ? "text-emerald-400"
                    : "text-amber-400"
                )}>
                  {escalationMetrics.escalation_rate.toFixed(1)}%
                </div>
                <span className={cn(
                  "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium",
                  escalationMetrics.escalation_rate >= 5 && escalationMetrics.escalation_rate <= 15
                    ? "bg-emerald-500/15 text-emerald-400 border border-emerald-500/25"
                    : "bg-amber-500/15 text-amber-400 border border-amber-500/25"
                )}>
                  {escalationMetrics.escalation_rate >= 5 && escalationMetrics.escalation_rate <= 15
                    ? "On target (5-15%)"
                    : escalationMetrics.escalation_rate < 5
                      ? "Below target"
                      : "Above target"}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-xs">
                <div className="space-y-1">
                  <p className="text-muted-foreground">Auto-send</p>
                  <p className="font-medium tabular-nums">{escalationMetrics.auto_send_count.toLocaleString()}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Queued</p>
                  <p className="font-medium tabular-nums">{escalationMetrics.queue_medium_count.toLocaleString()}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-muted-foreground">Needs human</p>
                  <p className="font-medium tabular-nums">{escalationMetrics.needs_human_count.toLocaleString()}</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

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

        {/* Status Picker */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {([
            {
              key: "all" as const,
              label: "All Feedback",
              description: "Every rating and channel",
              count: stats?.total_feedback ?? 0,
              icon: MessageCircle,
            },
            {
              key: "negative" as const,
              label: "Negative",
              description: "Needs review and improvement",
              count: stats?.negative_count ?? 0,
              icon: ThumbsDown,
            },
            {
              key: "needs_faq" as const,
              label: "Needs FAQ",
              description: "High-value knowledge gaps",
              count: stats?.needs_faq_count ?? 0,
              icon: PlusCircle,
            },
          ]).map((item) => {
            const isSelected = activeTab === item.key;
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                type="button"
                onClick={() => handleTabChange(item.key)}
                className={`touch-manipulation text-left rounded-lg border border-border bg-card p-4 transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                  isSelected ? "ring-2 ring-primary ring-offset-2" : ""
                }`}
                aria-pressed={isSelected}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="p-2 rounded-lg bg-muted">
                      <Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
                    </div>
                    <div className="min-w-0">
                      <p className="font-medium truncate">{item.label}</p>
                      <p className="text-xs text-muted-foreground truncate">{item.description}</p>
                    </div>
                  </div>
                  <span
                    className={`text-lg font-bold tabular-nums ${item.count > 0 ? "text-foreground" : "text-muted-foreground"}`}
                    aria-label={`${item.label} count ${item.count}`}
                  >
                    {item.count}
                  </span>
                </div>
              </button>
            );
          })}
        </div>

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
                    · {feedbackData.total_count} {feedbackData.total_count === 1 ? 'item' : 'items'}
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
                          <time
                            suppressHydrationWarning
                            dateTime={feedback.timestamp}
                            className="text-xs text-muted-foreground tabular-nums"
                          >
                            {formatDate(feedback.timestamp)}
                          </time>
                          {(() => {
                            const badge = getChannelBadge(feedback.channel);
                            return (
                              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${badge.className}`}>
                                {badge.label}
                              </span>
                            );
                          })()}
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
                    {((filters.page - 1) * filters.page_size) + 1}-{Math.min(filters.page * filters.page_size, feedbackData.total_count)} of {feedbackData.total_count}
                  </p>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handlePageChange(Math.max(1, filters.page - 1))}
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
                          onClick={() => handlePageChange(pageNum)}
                        >
                          {pageNum}
                        </Button>
                      );
                    })}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handlePageChange(Math.min(feedbackData.total_pages, filters.page + 1))}
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
      <Dialog open={showFeedbackDetail} onOpenChange={handleFeedbackDetailOpenChange}>
        <DialogContent showClose={false} className="max-w-4xl max-h-[85vh] p-0 overflow-hidden flex flex-col">
          <div className="relative px-6 pt-6">
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
                {detailPhase === "review" ? "Feedback Review" : "Create FAQ"}
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
                {detailPhase === "review"
                  ? "Review full feedback context and decide the next action."
                  : "Draft and publish an FAQ from this feedback record."}
              </DialogDescription>
              {selectedFeedback && (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {(() => {
                    const badge = getChannelBadge(selectedFeedback.channel);
                    return (
                      <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${badge.className}`}>
                        {badge.label}
                      </span>
                    );
                  })()}
                  <span
                    className="inline-flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground"
                    title={`Created ${formatDate(selectedFeedback.timestamp)}`}
                    aria-label={`Created ${formatDate(selectedFeedback.timestamp)}`}
                  >
                    <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                  </span>
                  {selectedFeedback.feedback_method === 'reaction' && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/15 text-purple-400 border border-purple-500/20">
                      {selectedFeedback.reaction_emoji || 'Reaction'}
                    </span>
                  )}
                  {selectedFeedback.has_no_source_response && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-orange-500/15 text-orange-400 border border-orange-500/20">
                      No source in answer
                    </span>
                  )}
                  {selectedFeedback.issues?.map((issue, idx) => (
                    <span key={`${issue}-${idx}`} className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${getIssueColor(issue)}`}>
                      {issue.replace('_', ' ')}
                    </span>
                  ))}
                  {selectedFeedback.is_processed && selectedFeedback.faq_id && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/15 text-primary border border-primary/25">
                      FAQ Created
                    </span>
                  )}
                </div>
              )}
            </DialogHeader>
          </div>

          {selectedFeedback && (
            <>
              <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-6 pb-6">
                <div className="space-y-5 pt-1">
                  <Card>
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <User className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                        <CardTitle className="text-sm">Question</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0">
                      <MarkdownContent content={selectedFeedback.question} className="text-sm" />
                    </CardContent>
                  </Card>

                  <Card>
                    <CardHeader className="pb-3">
                      <div className="flex items-center gap-2">
                        <Bot className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                        <CardTitle className="text-sm">Answer</CardTitle>
                      </div>
                    </CardHeader>
                    <CardContent className="pt-0 space-y-3">
                      <MarkdownContent content={selectedFeedback.answer} className="text-sm" />
                      {selectedFeedback.metadata?.response_time && (
                        <div className="pt-3 border-t border-border/50 text-xs text-muted-foreground">
                          <span className="inline-flex items-center gap-1.5 tabular-nums">
                            <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                            {selectedFeedback.metadata.response_time.toFixed(2)}s response
                          </span>
                        </div>
                      )}
                      {(selectedSourcesUsed.length > 0 || selectedSourcesAvailable.length > 0) && (
                        <div className="pt-3 border-t border-border/50 space-y-3">
                          {selectedSourcesUsed.length > 0 && (
                            <div className="space-y-2">
                              <p className="text-xs text-muted-foreground">Sources used</p>
                              <SourceBadges sources={selectedSourcesUsed} />
                              <Collapsible>
                                <CollapsibleTrigger asChild>
                                  <Button type="button" variant="ghost" size="sm" className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground">
                                    Preview excerpts
                                    <ChevronDown className="h-3.5 w-3.5 ml-1" />
                                  </Button>
                                </CollapsibleTrigger>
                                <CollapsibleContent className="space-y-2 pt-2">
                                  {selectedFeedback.sources_used?.slice(0, 3).map((source, idx) => (
                                    <div key={`${source.title}-${idx}`} className="p-3 rounded-lg border border-border bg-accent/40">
                                      <p className="text-sm font-medium text-card-foreground">{source.title}</p>
                                      <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
                                        {source.content.substring(0, 320)}{source.content.length > 320 ? '...' : ''}
                                      </p>
                                    </div>
                                  ))}
                                </CollapsibleContent>
                              </Collapsible>
                            </div>
                          )}
                          {selectedSourcesAvailable.length > 0 && (
                            <div className={cn("space-y-2", selectedSourcesUsed.length > 0 && "pt-3 border-t border-border/50")}>
                              <p className="text-xs text-muted-foreground">Available retrieval context</p>
                              <SourceBadges sources={selectedSourcesAvailable} />
                            </div>
                          )}
                        </div>
                      )}
                    </CardContent>
                  </Card>

                  {selectedFeedback.explanation && (
                    <Card>
                      <CardHeader className="pb-3">
                        <div className="flex items-center gap-2">
                          <MessageCircle className="h-4 w-4 text-red-300" aria-hidden="true" />
                          <CardTitle className="text-sm">User Feedback</CardTitle>
                        </div>
                        <CardDescription>Submitted by the user about the answer above.</CardDescription>
                      </CardHeader>
                      <CardContent className="pt-0">
                        <div className="text-sm p-3 bg-red-500/10 rounded-lg border-l-2 border-red-500/40 text-red-300 leading-relaxed">
                          {selectedFeedback.explanation}
                        </div>
                      </CardContent>
                    </Card>
                  )}

                  {selectedFeedback.conversation_history && selectedFeedback.conversation_history.length > 1 && (
                    <ConversationHistory messages={selectedFeedback.conversation_history} />
                  )}

                  {detailPhase === "faq" && selectedFeedback.is_negative && !selectedFeedback.is_processed && (
                    <div className="rounded-lg border border-border bg-card p-4 space-y-4">
                      <div className="text-sm p-3 bg-emerald-500/10 rounded-lg border-l-2 border-emerald-500/40 text-emerald-400 leading-relaxed">
                        Edit the FAQ draft and publish when ready.
                      </div>

                      <div className="space-y-1.5">
                        <Label htmlFor="feedback-faq-question" className="text-xs text-muted-foreground uppercase tracking-wider">Question</Label>
                        <Input
                          id="feedback-faq-question"
                          value={faqForm.suggested_question}
                          onChange={(e) => setFaqForm({ ...faqForm, suggested_question: e.target.value })}
                        />
                      </div>

                      <div className="space-y-2">
                        <div className="flex items-center gap-2">
                          <Bot className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                          <span className="font-medium text-sm">
                            Suggested Answer
                            {isEditingFaqAnswer && (
                              <span className="ml-1 text-muted-foreground">(Editing)</span>
                            )}
                          </span>
                          <div className="ml-auto flex items-center gap-2">
                            {selectedFeedback.answer && faqForm.suggested_answer.trim() !== selectedFeedback.answer.trim() && (
                              <Button
                                type="button"
                                variant="link"
                                size="sm"
                                className="h-7 px-0 text-xs text-muted-foreground hover:text-foreground"
                                onClick={() => setFaqForm({ ...faqForm, suggested_answer: selectedFeedback.answer || '' })}
                              >
                                Reset to original answer
                              </Button>
                            )}
                            {isEditingFaqAnswer ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                onClick={() => setIsEditingFaqAnswer(false)}
                              >
                                <Check className="h-3.5 w-3.5 mr-1" aria-hidden="true" />
                                Preview
                              </Button>
                            ) : (
                              <Button
                                type="button"
                                variant="ghost"
                                size="sm"
                                className="h-7 px-2 text-xs"
                                onClick={() => setIsEditingFaqAnswer(true)}
                              >
                                <Pencil className="h-3.5 w-3.5 mr-1" aria-hidden="true" />
                                Edit
                              </Button>
                            )}
                          </div>
                        </div>

                        <div
                          className={cn(
                            "p-4 rounded-lg border min-h-[160px] transition-all",
                            isEditingFaqAnswer
                              ? "bg-background border-primary ring-1 ring-primary"
                              : "bg-muted/30 border-border"
                          )}
                        >
                          {isEditingFaqAnswer ? (
                            <Textarea
                              ref={faqAnswerTextareaRef}
                              rows={10}
                              placeholder="Provide an improved, accurate answer..."
                              value={faqForm.suggested_answer}
                              onChange={(e) => {
                                setFaqForm({ ...faqForm, suggested_answer: e.target.value });
                                e.target.style.height = "auto";
                                e.target.style.height = `${e.target.scrollHeight}px`;
                              }}
                              onKeyDown={(e) => {
                                if (e.key === "Escape") {
                                  e.preventDefault();
                                  setIsEditingFaqAnswer(false);
                                }
                              }}
                              className="min-h-[150px] resize-none border-0 p-0 focus-visible:ring-0 bg-transparent"
                            />
                          ) : (
                            <div className="text-sm">
                              {faqForm.suggested_answer.trim() ? (
                                <MarkdownContent content={faqForm.suggested_answer} className="text-sm" />
                              ) : (
                                <p className="text-muted-foreground">No answer drafted yet.</p>
                              )}
                            </div>
                          )}
                          {(faqDraftSource.length > 0 || isEditingFaqAnswer) && (
                            <div className="mt-3 pt-3 border-t border-border/50 flex flex-wrap items-center gap-3">
                              {faqDraftSource.length > 0 && <SourceBadges sources={faqDraftSource} />}
                              {isEditingFaqAnswer && (
                                <span className="text-[11px] text-muted-foreground">
                                  Tip: press Escape to switch back to preview.
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>

                      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div className="space-y-1.5">
                          <Label htmlFor="feedback-faq-category" className="text-xs text-muted-foreground uppercase tracking-wider">Category</Label>
                          <Select
                            value={isCustomCategory ? 'custom' : faqForm.category}
                            onValueChange={(value) => {
                              if (value === 'custom') {
                                setIsCustomCategory(true);
                                setFaqForm({ ...faqForm, category: customCategory });
                              } else {
                                setIsCustomCategory(false);
                                setFaqForm({ ...faqForm, category: value });
                              }
                            }}
                          >
                            <SelectTrigger id="feedback-faq-category">
                              <SelectValue placeholder="Select a category" />
                            </SelectTrigger>
                            <SelectContent>
                              {FAQ_CATEGORIES.map((cat) => (
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
                                setFaqForm({ ...faqForm, category: e.target.value });
                              }}
                            />
                          )}
                        </div>
                        <div className="space-y-1.5">
                          <Label htmlFor="feedback-faq-protocol" className="text-xs text-muted-foreground uppercase tracking-wider">Protocol</Label>
                          <Select
                            value={faqForm.protocol}
                            onValueChange={(value) => setFaqForm({ ...faqForm, protocol: value as FAQProtocol })}
                          >
                            <SelectTrigger id="feedback-faq-protocol">
                              <SelectValue placeholder="Select protocol" />
                            </SelectTrigger>
                            <SelectContent>
                              {FAQ_PROTOCOL_OPTIONS.map((option) => (
                                <SelectItem key={option.value} value={option.value}>
                                  {option.label}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="border-t border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-6 py-4">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    {detailPhase === "review" && selectedFeedback.is_negative && !selectedFeedback.is_processed && (
                      <Button
                        size="sm"
                        onClick={() => {
                          setDetailPhase("faq");
                          setIsEditingFaqAnswer(true);
                        }}
                      >
                        <PlusCircle className="h-3.5 w-3.5 mr-1.5" />
                        Create FAQ Draft
                      </Button>
                    )}
                    {detailPhase === "faq" && selectedFeedback.is_negative && !selectedFeedback.is_processed && (
                      <Button
                        size="sm"
                        onClick={handleCreateFAQ}
                        disabled={
                          isSubmittingFAQ ||
                          !faqForm.suggested_question.trim() ||
                          !faqForm.suggested_answer.trim() ||
                          !faqForm.category.trim()
                        }
                      >
                        {isSubmittingFAQ && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                        Publish FAQ
                      </Button>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {detailPhase === "faq" && selectedFeedback.is_negative && !selectedFeedback.is_processed && (
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          setDetailPhase("review");
                          setIsEditingFaqAnswer(false);
                        }}
                        disabled={isSubmittingFAQ}
                      >
                        Back to Review
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </>
          )}
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
