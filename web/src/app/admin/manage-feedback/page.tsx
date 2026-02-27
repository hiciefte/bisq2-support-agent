"use client"

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogClose } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { DatePicker } from "@/components/ui/date-picker";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import {
  Loader2,
  MessageCircle,
  ThumbsDown,
  ThumbsUp,
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
  Clock,
  ChevronDown,
  User,
  ArrowUpRight,
  Link2,
  MoreHorizontal,
  SlidersHorizontal,
  Info,
} from 'lucide-react';
import { format } from 'date-fns';
import { makeAuthenticatedRequest } from '@/lib/auth';
import { ConversationHistory } from '@/components/admin/ConversationHistory';
import { ConversationMessage } from '@/types/feedback';
import { useFeedbackDeletion } from '@/hooks/useFeedbackDeletion';
import { useAdminPollingQuery } from '@/hooks/useAdminPollingQuery';
import { useHotkeys } from "react-hotkeys-hook";
import { AdminQueueShell } from "@/components/admin/queue/AdminQueueShell";
import { QueuePageHeader } from "@/components/admin/queue/QueuePageHeader";
import { QueueTabs } from "@/components/admin/queue/QueueTabs";
import { QueueCommandBar } from "@/components/admin/queue/QueueCommandBar";
import { MarkdownContent } from "@/components/chat/components/markdown-content";
import { SourceBadges } from "@/components/chat/components/source-badges";
import type { Source } from "@/components/chat/types/chat.types";
import { stripGeneratedAnswerFooter } from "@/lib/answer-format";

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
  needs_faq?: boolean;
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

interface ConversationOutcome {
  message_id: string;
  signal?: {
    coverage_state: 'not_linked' | 'linked_escalation' | 'auto_closed';
    linked_escalation_id?: number | null;
  } | null;
  escalation?: {
    id: number;
    status: string;
    priority: string;
  } | null;
  recommended_action: 'none' | 'review_case' | 'promote_case' | 'await_feedback';
}

function normalizeReactionToken(value?: string | null): string {
  return (value || "")
    .trim()
    .toLowerCase()
    .replace(/[:_\-\s]/g, "");
}

function getReactionDisplayLabel(reactionEmoji?: string | null): string {
  const token = normalizeReactionToken(reactionEmoji);
  const tokenToEmoji: Record<string, string> = {
    "thumbsup": "👍",
    "+1": "👍",
    "like": "👍",
    "thumbsdown": "👎",
    "-1": "👎",
    "dislike": "👎",
    "heart": "❤️",
    "happy": "😊",
    "party": "🎉",
    "laugh": "😂",
  };

  if (tokenToEmoji[token]) return tokenToEmoji[token];

  const raw = (reactionEmoji || "").trim();
  return raw || "Reaction";
}

function isCanonicalThumbReaction(
  reactionEmoji: string | undefined,
  isPositive: boolean,
  isNegative: boolean,
): boolean {
  const token = normalizeReactionToken(reactionEmoji);
  if (!token) return false;

  const thumbsUpTokens = new Set(["👍", "+1", "thumbsup", "like"]);
  const thumbsDownTokens = new Set(["👎", "-1", "thumbsdown", "dislike"]);

  if (isPositive) return thumbsUpTokens.has(token);
  if (isNegative) return thumbsDownTokens.has(token);
  return thumbsUpTokens.has(token) || thumbsDownTokens.has(token);
}

function shouldShowReactionTag(feedback: FeedbackItem): boolean {
  if (feedback.feedback_method !== "reaction") return false;
  return !isCanonicalThumbReaction(
    feedback.reaction_emoji,
    feedback.is_positive,
    feedback.is_negative,
  );
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
  const [isManualRefresh, setIsManualRefresh] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [dismissedError, setDismissedError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

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
      filters.page,
      filters.page_size,
      filters.sort_by,
    ],
  );

  // UI state
  const [activeTab, setActiveTab] = useState<'all' | 'negative'>('all');
  const [showFilters, setShowFilters] = useState(false);
  const [selectedFeedback, setSelectedFeedback] = useState<FeedbackItem | null>(null);
  const [selectedSignalIndex, setSelectedSignalIndex] = useState<number>(-1);
  const [showFeedbackDetail, setShowFeedbackDetail] = useState(false);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [conversationOutcome, setConversationOutcome] = useState<ConversationOutcome | null>(null);
  const [isLoadingOutcome, setIsLoadingOutcome] = useState(false);
  const [isPromotingCase, setIsPromotingCase] = useState(false);
  const searchInputRef = useRef<HTMLInputElement>(null);

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
    ].filter(Boolean).length;
  }, [filters]);

  const hasActiveFilters = activeFilterCount > 0;
  const fetchFeedbackList = useCallback(async (): Promise<FeedbackListResponse> => {
    const adjustedFilters = { ...stableFilters };
    if (activeTab === 'negative') {
      adjustedFilters.rating = 'negative';
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
    if (!response.ok) {
      throw new Error(`Failed to fetch feedback. Status: ${response.status}`);
    }
    return response.json();
  }, [stableFilters, activeTab]);

  const fetchStats = useCallback(async (): Promise<FeedbackStats> => {
    const response = await makeAuthenticatedRequest('/admin/feedback/stats');
    if (!response.ok) {
      throw new Error(`Failed to fetch stats. Status: ${response.status}`);
    }
    return response.json();
  }, []);

  const feedbackQuery = useAdminPollingQuery<FeedbackListResponse, readonly unknown[]>({
    queryKey: [
      'admin',
      'quality-signals',
      {
        tab: activeTab,
        filters: stableFilters,
      },
    ] as const,
    queryFn: fetchFeedbackList,
    placeholderData: (previousData) => previousData,
  });

  const statsQuery = useAdminPollingQuery<FeedbackStats, readonly unknown[]>({
    queryKey: ['admin', 'quality-signals', 'stats'] as const,
    queryFn: fetchStats,
  });

  const feedbackData = feedbackQuery.data ?? null;
  const stats = statsQuery.data ?? null;
  const isLoading = feedbackQuery.isLoading || statsQuery.isLoading;
  const isRefreshing = isManualRefresh || feedbackQuery.isFetching || statsQuery.isFetching;
  const error = actionError || feedbackQuery.error?.message || statsQuery.error?.message || null;
  const visibleError = error && error !== dismissedError ? error : null;

  const refreshData = useCallback(async () => {
    setDismissedError(null);
    setActionError(null);
    setIsManualRefresh(true);
    try {
      await Promise.all([
        feedbackQuery.refetch(),
        statsQuery.refetch(),
      ]);
    } finally {
      setIsManualRefresh(false);
    }
  }, [feedbackQuery, statsQuery]);

  useEffect(() => {
    const updatedAt = Math.max(
      feedbackQuery.dataUpdatedAt || 0,
      statsQuery.dataUpdatedAt || 0,
    );
    if (updatedAt > 0) {
      setLastUpdatedAt(new Date(updatedAt));
    }
  }, [feedbackQuery.dataUpdatedAt, statsQuery.dataUpdatedAt]);

  useEffect(() => {
    if (!feedbackData) return;
    if (feedbackData.total_pages > 0 && stableFilters.page > feedbackData.total_pages) {
      setFilters((prev) => (
        prev.page > feedbackData.total_pages
          ? { ...prev, page: feedbackData.total_pages }
          : prev
      ));
      return;
    }
    if (feedbackData.total_pages === 0 && stableFilters.page !== 1) {
      setFilters((prev) => (prev.page !== 1 ? { ...prev, page: 1 } : prev));
    }
  }, [feedbackData, stableFilters.page]);

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
    if (key !== "page") {
      setSelectedSignalIndex(-1);
    }
  };

  const handlePageChange = (page: number) => {
    setFilters((prev) => ({
      ...prev,
      page,
    }));
  };

  const handleTabChange = (tab: 'all' | 'negative') => {
    setActiveTab(tab);
    setFilters(prev => ({ ...prev, page: 1 }));
    setSelectedSignalIndex(-1);
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
      page: 1,
      page_size: 25,
      sort_by: 'newest'
    });
    setSelectedSignalIndex(-1);
  };

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
    await refreshData();
    setDismissedError(null);
  });

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

  const fetchConversationOutcome = useCallback(async (messageId: string) => {
    setIsLoadingOutcome(true);
    try {
      const response = await makeAuthenticatedRequest(`/admin/conversations/${encodeURIComponent(messageId)}/outcome`);
      if (response.ok) {
        const payload: ConversationOutcome = await response.json();
        setConversationOutcome(payload);
        return;
      }
    } catch (error) {
      console.error('Error fetching conversation outcome:', error);
    } finally {
      setIsLoadingOutcome(false);
    }
    setConversationOutcome(null);
  }, []);

  const handlePromoteSignalToEscalation = useCallback(async () => {
    if (!selectedFeedback) return;
    setIsPromotingCase(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/signals/${encodeURIComponent(selectedFeedback.message_id)}/promote-case`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            priority: 'normal',
            reason: 'promoted_from_quality_signal',
          }),
        }
      );

      if (!response.ok) {
        const payload = await response.json().catch(() => ({ detail: 'Failed to promote signal to escalation.' }));
        setActionError(payload.detail || 'Failed to promote signal to escalation.');
        return;
      }

      await fetchConversationOutcome(selectedFeedback.message_id);
      await refreshData();
      setActionError(null);
    } catch (error) {
      console.error('Error promoting signal to escalation:', error);
      setActionError('Failed to promote signal to escalation.');
    } finally {
      setIsPromotingCase(false);
    }
  }, [fetchConversationOutcome, refreshData, selectedFeedback]);

  const closeFeedbackDetailDialog = () => {
    setShowFeedbackDetail(false);
    setSelectedFeedback(null);
    setIsDetailLoading(false);
    setConversationOutcome(null);
    setIsLoadingOutcome(false);
  };

  const openFeedbackDetail = (feedback: FeedbackItem) => {
    setSelectedFeedback(feedback);
    setShowFeedbackDetail(true);
    setIsDetailLoading(true);

    if (feedback.is_negative) {
      void fetchConversationOutcome(feedback.message_id);
    } else {
      setConversationOutcome(null);
      setIsLoadingOutcome(false);
    }

    void fetchFullFeedbackDetails(feedback)
      .then((fullFeedback) => {
        setSelectedFeedback((current) => (current ? { ...current, ...fullFeedback } : fullFeedback));
      })
      .finally(() => {
        setIsDetailLoading(false);
      });
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

  const getSignalTags = (feedback: FeedbackItem) => {
    const tags: { label: string; className: string }[] = [];

    if (shouldShowReactionTag(feedback)) {
      tags.push({
        label: getReactionDisplayLabel(feedback.reaction_emoji),
        className: "bg-purple-500/15 text-purple-400 border border-purple-500/20",
      });
    }
    if (feedback.has_no_source_response) {
      tags.push({
        label: "No source",
        className: "bg-orange-500/15 text-orange-400 border border-orange-500/20",
      });
    }
    if (feedback.needs_faq) {
      tags.push({
        label: "Coverage gap",
        className: "bg-amber-500/15 text-amber-400 border border-amber-500/20",
      });
    }
    if (feedback.is_processed && feedback.faq_id) {
      tags.push({
        label: "FAQ linked",
        className: "bg-primary/15 text-primary border border-primary/25",
      });
    }
    for (const issue of feedback.issues || []) {
      tags.push({
        label: issue.replace('_', ' '),
        className: getIssueColor(issue),
      });
    }

    return tags;
  };

  const activeFilterPills = useMemo(() => {
    const pills: string[] = [];
    if (filters.search_text.trim()) pills.push(`Search: ${filters.search_text.trim()}`);
    if (filters.channel !== "all") pills.push(`Channel: ${filters.channel}`);
    if (filters.feedback_method !== "all") pills.push(`Method: ${filters.feedback_method}`);
    if (filters.date_from) pills.push(`From: ${format(filters.date_from, "yyyy-MM-dd")}`);
    if (filters.date_to) pills.push(`To: ${format(filters.date_to, "yyyy-MM-dd")}`);
    return pills;
  }, [filters.channel, filters.date_from, filters.date_to, filters.feedback_method, filters.search_text]);
  const shortcutHints = useMemo(
    () => [
      { keyCombo: "/", label: "Search" },
      { keyCombo: "J / K", label: "Navigate signals" },
      { keyCombo: "O", label: "Open selected signal" },
      { keyCombo: "E", label: "Open selected negative signal" },
      { keyCombo: "R", label: "Refresh queue" },
    ],
    [],
  );

  const statusTabs = [
    {
      key: "all" as const,
      label: "All",
      count: stats?.total_feedback ?? 0,
      icon: MessageCircle,
    },
    {
      key: "negative" as const,
      label: "Negative",
      count: stats?.negative_count ?? 0,
      icon: ThumbsDown,
    },
  ];

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

  const selectedAnswerBody = useMemo(
    () => stripGeneratedAnswerFooter(selectedFeedback?.answer),
    [selectedFeedback?.answer],
  );
  const shouldShowCaseCoverage = useMemo(() => {
    if (!selectedFeedback?.is_negative) return false;
    if (isLoadingOutcome) return true;
    if (!conversationOutcome) return false;

    const hasEscalationLink = Boolean(conversationOutcome.escalation?.id);
    const hasActionableState = conversationOutcome.recommended_action !== "none";
    return hasEscalationLink || hasActionableState;
  }, [selectedFeedback?.is_negative, isLoadingOutcome, conversationOutcome]);

  const feedbackItems = feedbackData?.feedback_items ?? [];

  useEffect(() => {
    if (feedbackItems.length === 0) {
      setSelectedSignalIndex(-1);
      return;
    }
    if (selectedSignalIndex >= feedbackItems.length) {
      setSelectedSignalIndex(feedbackItems.length - 1);
    }
  }, [feedbackItems.length, selectedSignalIndex]);

  useHotkeys(
    "/",
    (event) => {
      event.preventDefault();
      searchInputRef.current?.focus();
    },
    { enableOnFormTags: false },
    [],
  );

  useHotkeys(
    "j",
    (event) => {
      event.preventDefault();
      if (!feedbackItems.length || showFeedbackDetail) return;
      setSelectedSignalIndex((prev) => {
        if (prev < 0) return 0;
        return Math.min(prev + 1, feedbackItems.length - 1);
      });
    },
    { enableOnFormTags: false },
    [feedbackItems, showFeedbackDetail],
  );

  useHotkeys(
    "k",
    (event) => {
      event.preventDefault();
      if (!feedbackItems.length || showFeedbackDetail) return;
      setSelectedSignalIndex((prev) => Math.max(prev - 1, 0));
    },
    { enableOnFormTags: false },
    [feedbackItems, showFeedbackDetail],
  );

  useHotkeys(
    "o",
    (event) => {
      event.preventDefault();
      if (showFeedbackDetail) return;
      const selected = selectedSignalIndex >= 0 ? feedbackItems[selectedSignalIndex] : feedbackItems[0];
      if (!selected) return;
      void openFeedbackDetail(selected);
    },
    { enableOnFormTags: false },
    [showFeedbackDetail, selectedSignalIndex, feedbackItems, openFeedbackDetail],
  );

  useHotkeys(
    "r",
    (event) => {
      event.preventDefault();
      void refreshData();
    },
    { enableOnFormTags: false },
    [refreshData],
  );

  useHotkeys(
    "e",
    (event) => {
      event.preventDefault();
      if (showFeedbackDetail) return;
      const selected = selectedSignalIndex >= 0 ? feedbackItems[selectedSignalIndex] : feedbackItems[0];
      if (!selected?.is_negative) return;
      setSelectedFeedback(selected);
      void fetchConversationOutcome(selected.message_id);
      setShowFeedbackDetail(true);
    },
    { enableOnFormTags: false },
    [showFeedbackDetail, selectedSignalIndex, feedbackItems, fetchConversationOutcome],
  );

  // Authentication is handled by SecureAuth wrapper in layout

  return (
    <AdminQueueShell shortcutHints={shortcutHints}>
      <QueuePageHeader
        title="Quality Signals"
        description="Review user feedback signals, prioritize risks, and promote unresolved cases to Escalations."
        lastUpdatedLabel={lastUpdatedAt ? `Updated ${formatDate(lastUpdatedAt.toISOString())}` : null}
        isRefreshing={isRefreshing}
        onRefresh={() => { void refreshData(); }}
        rightSlot={(
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="hidden md:inline-flex text-xs text-muted-foreground">
              Coverage gaps: {(stats?.needs_faq_count ?? 0).toLocaleString()}
            </Badge>
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground">
                  <Info className="h-3.5 w-3.5 mr-1.5" />
                  Signal definitions
                  <ChevronDown className="h-3.5 w-3.5 ml-1" />
                </Button>
              </PopoverTrigger>
              <PopoverContent
                align="end"
                sideOffset={8}
                className="w-[min(420px,calc(100vw-2rem))] rounded-lg border border-border/60 bg-card/95 p-3 text-xs text-muted-foreground shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/80"
              >
                <p className="mb-2">
                  <span className="font-medium text-foreground">Negative:</span> user-reported quality issue on an answer.
                </p>
                <p>
                  <span className="font-medium text-foreground">Coverage gap:</span> a negative signal where documentation coverage appears insufficient and should be handled in Escalations.
                </p>
              </PopoverContent>
            </Popover>
          </div>
        )}
      />

      <QueueTabs
        tabs={statusTabs}
        activeTab={activeTab}
        onTabChange={handleTabChange}
        gridClassName="grid-cols-2"
      />

      {visibleError && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg" role="alert">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{visibleError}</span>
          <button onClick={() => setDismissedError(visibleError)} className="ml-auto text-red-400/60 hover:text-red-400 transition-colors">
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <QueueCommandBar
        activeFilterPills={activeFilterPills}
        advancedContent={(
          <div className={cn("grid transition-all duration-200 ease-out", showFilters ? "grid-rows-[1fr] opacity-100 mt-3" : "grid-rows-[0fr] opacity-0")}>
            <div className="overflow-hidden">
              <div className="rounded-lg border border-border/60 bg-card/40 p-3">
                <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Date From</Label>
                    <DatePicker
                      value={filters.date_from}
                      onChange={(date) => handleFilterChange('date_from', date)}
                      placeholder="Start date"
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label className="text-xs text-muted-foreground">Date To</Label>
                    <DatePicker
                      value={filters.date_to}
                      onChange={(date) => handleFilterChange('date_to', date)}
                      placeholder="End date"
                    />
                  </div>
                  <div className="flex items-end">
                    <Button onClick={resetFilters} variant="ghost" size="sm" className="text-muted-foreground hover:text-foreground">
                      <RotateCcw className="mr-1.5 h-3.5 w-3.5" />
                      Reset filters
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              ref={searchInputRef}
              placeholder="Search questions and answers..."
              value={filters.search_text}
              onChange={(e) => handleFilterChange('search_text', e.target.value)}
              className="pl-9 pr-8"
            />
            {filters.search_text && (
              <button
                onClick={() => handleFilterChange('search_text', '')}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                aria-label="Clear search"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>
          <Select value={filters.channel} onValueChange={(value) => handleFilterChange('channel', value)}>
            <SelectTrigger className="w-[130px]">
              <SelectValue placeholder="Channel" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Channels</SelectItem>
              <SelectItem value="web">Web</SelectItem>
              <SelectItem value="matrix">Matrix</SelectItem>
              <SelectItem value="bisq2">Bisq2</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filters.feedback_method} onValueChange={(value) => handleFilterChange('feedback_method', value)}>
            <SelectTrigger className="w-[130px]">
              <SelectValue placeholder="Method" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Methods</SelectItem>
              <SelectItem value="web_dialog">Web Dialog</SelectItem>
              <SelectItem value="reaction">Reaction</SelectItem>
            </SelectContent>
          </Select>
          <Button
            onClick={() => setShowFilters((prev) => !prev)}
            variant="outline"
            size="sm"
            className={cn("border-border", showFilters && "bg-accent border-primary")}
          >
            <SlidersHorizontal className="mr-2 h-4 w-4" />
            Advanced
            {hasActiveFilters && (
              <Badge variant="secondary" className="ml-2 h-5 min-w-5 px-1.5 text-[10px] tabular-nums">
                {activeFilterCount}
              </Badge>
            )}
          </Button>
          <Button
            onClick={exportFeedback}
            variant="outline"
            size="sm"
            className="border-border"
            disabled={!feedbackData || feedbackData.feedback_items.length === 0}
          >
            <Download className="mr-2 h-4 w-4" />
            Export
          </Button>
        </div>
      </QueueCommandBar>

      {/* Signal List */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">
                Signal List
              </CardTitle>
              <CardDescription className="mt-0.5">
                {activeTab === 'all' && 'All user quality signals'}
                {activeTab === 'negative' && 'Negative user signals requiring quality review.'}
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
              <h3 className="text-base font-semibold mb-1">No signals found</h3>
              <p className="text-sm text-muted-foreground mb-4 max-w-sm mx-auto">
                {hasActiveFilters
                  ? 'No signals match your current filters. Try adjusting or resetting them.'
                  : activeTab === 'negative'
                    ? 'No negative signals recorded. That is a good sign.'
                    : 'No signals have been submitted yet.'}
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
              {feedbackData.feedback_items.map((feedback, index) => {
                const channelBadge = getChannelBadge(feedback.channel);
                const signalTags = getSignalTags(feedback);
                const primaryTags = signalTags.slice(0, 1);
                const overflowTags = signalTags.slice(1);
                const isKeyboardSelected = index === selectedSignalIndex;

                return (
                  <div
                    key={feedback.message_id}
                    className={`relative border rounded-lg transition-colors hover:bg-accent/20 cursor-pointer ${
                      feedback.is_positive
                        ? 'border-l-2 border-l-primary/50 border-t border-r border-b border-border'
                        : 'border-l-2 border-l-red-500/50 border-t border-r border-b border-border'
                    } ${isKeyboardSelected ? 'ring-1 ring-primary/60 bg-accent/20' : ''}`}
                    onClick={() => {
                      setSelectedSignalIndex(index);
                      void openFeedbackDetail(feedback);
                    }}
                    role="button"
                    tabIndex={0}
                    onMouseEnter={() => setSelectedSignalIndex(index)}
                    onKeyDown={(e) => { if (e.key === 'Enter') void openFeedbackDetail(feedback); }}
                  >
                    <div className="p-4">
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0 space-y-2">
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
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${channelBadge.className}`}>
                              {channelBadge.label}
                            </span>

                            {primaryTags.map((tag) => (
                              <span key={tag.label} className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${tag.className}`}>
                                {tag.label}
                              </span>
                            ))}

                            {overflowTags.length > 0 && (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-5 px-1.5 text-[10px] text-muted-foreground"
                                    onClick={(e) => e.stopPropagation()}
                                  >
                                    +{overflowTags.length} more
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent
                                  align="start"
                                  onClick={(e) => e.stopPropagation()}
                                  className="min-w-[180px]"
                                >
                                  {overflowTags.map((tag) => (
                                    <div key={tag.label} className="px-2 py-1.5 text-xs text-muted-foreground">
                                      {tag.label}
                                    </div>
                                  ))}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            )}
                          </div>

                          <p className="text-sm leading-relaxed line-clamp-2 font-medium">
                            {feedback.question}
                          </p>

                          {feedback.explanation && (
                            <p className="text-xs text-red-400/80 line-clamp-1">
                              &ldquo;{feedback.explanation}&rdquo;
                            </p>
                          )}
                        </div>

                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground hover:text-foreground shrink-0"
                              aria-label="Signal actions"
                              onClick={(e) => e.stopPropagation()}
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
                            <DropdownMenuItem onSelect={(e) => { e.preventDefault(); void openFeedbackDetail(feedback); }}>
                              <Eye className="h-3.5 w-3.5 mr-2" />
                              View details
                            </DropdownMenuItem>
                            <DropdownMenuItem
                              className="text-red-400 focus:text-red-300"
                              onSelect={(e) => { e.preventDefault(); openDeleteConfirmation(feedback); }}
                            >
                              <Trash2 className="h-3.5 w-3.5 mr-2" />
                              Delete signal
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                    </div>
                  </div>
                );
              })}

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
                Signal Review
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
                Review full signal context and decide the next action.
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
                  {shouldShowReactionTag(selectedFeedback) && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-purple-500/15 text-purple-400 border border-purple-500/20">
                      {getReactionDisplayLabel(selectedFeedback.reaction_emoji)}
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
                  {selectedFeedback.is_negative && conversationOutcome?.signal?.coverage_state === 'linked_escalation' && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-500/15 text-blue-400 border border-blue-500/20">
                      Covered by Escalation
                    </span>
                  )}
                  {selectedFeedback.is_negative && conversationOutcome?.signal?.coverage_state === 'not_linked' && (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20">
                      Not Linked to Escalation
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
                  {isDetailLoading && (
                    <div className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Loading full signal context...
                    </div>
                  )}

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
                      <MarkdownContent content={selectedAnswerBody} className="text-sm" />
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

                  {shouldShowCaseCoverage && (
                    <Card>
                      <CardHeader className="pb-3">
                        <div className="flex items-center gap-2">
                          <Link2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                          <CardTitle className="text-sm">Case Coverage</CardTitle>
                        </div>
                        <CardDescription>Signal-to-escalation relationship for this conversation.</CardDescription>
                      </CardHeader>
                      <CardContent className="pt-0 space-y-3">
                        {isLoadingOutcome ? (
                          <div className="inline-flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="h-4 w-4 animate-spin" />
                            Loading coverage status...
                          </div>
                        ) : (
                          <>
                            <div className="text-sm text-muted-foreground">
                              {conversationOutcome?.recommended_action === 'promote_case' && 'Negative asker signal is not covered yet.'}
                              {conversationOutcome?.recommended_action === 'review_case' && 'Escalation is open and waiting for review.'}
                              {conversationOutcome?.recommended_action === 'await_feedback' && 'Escalation response was sent. Waiting for feedback.'}
                            </div>

                            <div className="flex flex-wrap items-center gap-2">
                              {conversationOutcome?.escalation?.id && (
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  onClick={() => window.open(`/admin/escalations?search=${encodeURIComponent(selectedFeedback.message_id)}`, "_blank", "noopener,noreferrer")}
                                >
                                  <ArrowUpRight className="h-3.5 w-3.5 mr-1.5" />
                                  Open Escalation
                                </Button>
                              )}

                              {conversationOutcome?.recommended_action === 'promote_case' && (
                                <Button
                                  type="button"
                                  size="sm"
                                  onClick={handlePromoteSignalToEscalation}
                                  disabled={isPromotingCase}
                                >
                                  {isPromotingCase && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                  Promote to Escalation
                                </Button>
                              )}
                            </div>
                          </>
                        )}
                      </CardContent>
                    </Card>
                  )}

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
    </AdminQueueShell>
  );
}
