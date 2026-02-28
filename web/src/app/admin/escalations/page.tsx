"use client"

import { useState, useEffect, useCallback, useMemo, useRef, useTransition } from 'react'
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import {
  RotateCcw,
  Search,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  X,
  Clock,
  BadgeCheck,
  AlertTriangle,
  Users,
  Eye,
  Info,
  ChevronDown,
} from 'lucide-react'
import { makeAuthenticatedRequest } from '@/lib/auth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useAdminPollingQuery } from '@/hooks/useAdminPollingQuery'
import { useHotkeys } from "react-hotkeys-hook"
import { AdminQueueShell } from "@/components/admin/queue/AdminQueueShell"
import { QueuePageHeader } from "@/components/admin/queue/QueuePageHeader"
import { QueueTabs } from "@/components/admin/queue/QueueTabs"
import { QueueCommandBar } from "@/components/admin/queue/QueueCommandBar"
import { EscalationReviewPanel } from './EscalationReviewPanel'
import { normalizeRoutingReasonSourceCount } from "@/lib/escalation-routing"

// --- Types ---

export interface EscalationItem {
  id: number
  message_id: string
  channel: string
  user_id: string
  username?: string | null
  channel_metadata?: Record<string, unknown> | null
  question_original?: string | null
  question: string
  ai_draft_answer_original?: string | null
  ai_draft_answer: string
  user_language?: string | null
  translation_applied?: boolean
  confidence_score: number
  routing_action: string
  routing_reason?: string | null
  priority: 'high' | 'normal'
  status: 'pending' | 'in_review' | 'responded' | 'closed'
  staff_id?: string
  staff_answer?: string
  sources?: Array<{
    document_id?: string
    title?: string
    url?: string | null
    relevance_score?: number
    category?: string | null
    content?: string | null
    protocol?: string | null
    section?: string | null
  }>
  created_at: string
  claimed_at?: string | null
  responded_at?: string | null
  closed_at?: string | null
}

interface EscalationListResponse {
  escalations: EscalationItem[]
  total: number
  limit: number
  offset: number
}

interface EscalationCounts {
  pending: number
  in_review: number
  responded: number
  closed: number
  total: number
}

// --- Helpers ---

function formatTimeAgo(timestamp: string): string {
  const now = new Date()
  const then = new Date(timestamp)
  const diffMs = now.getTime() - then.getTime()
  const diffMins = Math.floor(diffMs / 60000)
  const diffHours = Math.floor(diffMins / 60)
  const diffDays = Math.floor(diffHours / 24)

  if (diffMins < 1) return 'just now'
  if (diffMins < 60) return `${diffMins}m ago`
  if (diffHours < 24) return `${diffHours}h ago`
  return `${diffDays}d ago`
}

function getChannelBadge(channel: string): { label: string; className: string } {
  const badges: Record<string, { label: string; className: string }> = {
    'web': { label: 'Web', className: 'bg-blue-500/15 text-blue-400 border border-blue-500/25' },
    'matrix': { label: 'Matrix', className: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25' },
    'bisq2': { label: 'Bisq2', className: 'bg-orange-500/15 text-orange-400 border border-orange-500/25' },
  }
  return badges[channel] || { label: channel, className: 'bg-muted text-muted-foreground border border-border' }
}

function getStatusBadge(status: string): { label: string; className: string } {
  const badges: Record<string, { label: string; className: string }> = {
    'pending': { label: 'Pending', className: 'bg-yellow-500/15 text-yellow-400' },
    'in_review': { label: 'In Review', className: 'bg-blue-500/15 text-blue-400' },
    'responded': { label: 'Responded', className: 'bg-emerald-500/15 text-emerald-400' },
    'closed': { label: 'Closed', className: 'bg-muted text-muted-foreground' },
  }
  return badges[status] || { label: status, className: 'bg-muted text-muted-foreground' }
}

function getPriorityBadge(priority: string): { label: string; className: string; icon: typeof AlertTriangle | null } {
  const badges: Record<string, { label: string; className: string; icon: typeof AlertTriangle | null }> = {
    'high': { label: 'High', className: 'bg-orange-500/15 text-orange-400', icon: AlertTriangle },
    'normal': { label: 'Normal', className: 'bg-muted text-muted-foreground', icon: null },
  }
  return badges[priority] || { label: priority, className: 'bg-muted text-muted-foreground', icon: null }
}

function humanizeEnumValue(value: string): string {
  const cleaned = (value || "")
    .trim()
    .replace(/[-_]+/g, " ")
    .toLowerCase()
  if (!cleaned) return ""
  return cleaned.replace(/\b\w/g, (c) => c.toUpperCase())
}

function getPrimaryQuestion(escalation: EscalationItem): string {
  const canonical = escalation.question?.trim()
  if (canonical) return canonical
  return escalation.question_original?.trim() || "Question unavailable."
}

const PAGE_SIZE = 20

// --- Component ---

function getEscalationAgeBadge(
  createdAt: string,
  status: EscalationItem['status']
): { label: string; className: string } | null {
  if (status !== 'pending' && status !== 'in_review') return null

  const created = new Date(createdAt).getTime()
  if (!Number.isFinite(created)) return null

  const ageHours = (Date.now() - created) / (1000 * 60 * 60)
  if (ageHours >= 12) {
    return {
      label: `${Math.floor(ageHours)}h waiting`,
      className: 'bg-red-500/15 text-red-400 border border-red-500/30',
    }
  }
  if (ageHours >= 4) {
    return {
      label: `${Math.floor(ageHours)}h waiting`,
      className: 'bg-orange-500/15 text-orange-400 border border-orange-500/30',
    }
  }
  if (ageHours >= 1) {
    return {
      label: `${Math.floor(ageHours)}h waiting`,
      className: 'bg-blue-500/15 text-blue-400 border border-blue-500/30',
    }
  }

  const mins = Math.max(1, Math.floor(ageHours * 60))
  return {
    label: `${mins}m waiting`,
    className: 'bg-muted text-muted-foreground border border-border',
  }
}

export default function EscalationsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [, startUrlTransition] = useTransition()

  // Queue state
  const [isManualRefresh, setIsManualRefresh] = useState(false)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null)

  // Filter state
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'in_review' | 'responded' | 'closed'>('all')
  const [filters, setFilters] = useState({
    channel: 'all',
    priority: 'all',
    search_text: '',
    page: 1,
  })
  const [initializedFromUrl, setInitializedFromUrl] = useState(false)
  const [dismissedError, setDismissedError] = useState<string | null>(null)

  // Review panel
  const [selectedEscalation, setSelectedEscalation] = useState<EscalationItem | null>(null)
  const [showReviewPanel, setShowReviewPanel] = useState(false)
  const [selectedEscalationIndex, setSelectedEscalationIndex] = useState<number>(-1)
  const searchInputRef = useRef<HTMLInputElement>(null)

  const debouncedSearchText = useDebouncedValue(filters.search_text, 300)

  // Computed
  const activeFilterCount = useMemo(() => {
    return [
      filters.search_text,
      filters.channel !== 'all',
      filters.priority !== 'all',
    ].filter(Boolean).length
  }, [filters])

  const hasActiveFilters = activeFilterCount > 0
  const shortcutHints = useMemo(
    () => [
      { keyCombo: '/', label: 'Search' },
      { keyCombo: 'J / K', label: 'Navigate cases' },
      { keyCombo: 'O', label: 'Open selected case' },
      { keyCombo: 'E', label: 'Open pending in review panel' },
      { keyCombo: 'R', label: 'Refresh queue' },
    ],
    [],
  )
  const activeFilterPills = useMemo(() => {
    const pills: string[] = []
    if (filters.search_text.trim()) pills.push(`Search: ${filters.search_text.trim()}`)
    if (filters.channel !== 'all') pills.push(`Channel: ${getChannelBadge(filters.channel).label}`)
    if (filters.priority !== 'all') pills.push(`Priority: ${humanizeEnumValue(filters.priority)}`)
    return pills
  }, [filters.search_text, filters.channel, filters.priority])

  const fetchEscalations = useCallback(async (): Promise<EscalationListResponse> => {
    const params = new URLSearchParams()

    if (activeTab !== 'all') {
      params.append('status', activeTab)
    }
    if (filters.channel !== 'all') {
      params.append('channel', filters.channel)
    }
    if (filters.priority !== 'all') {
      params.append('priority', filters.priority)
    }
    if (debouncedSearchText) {
      params.append('search', debouncedSearchText)
    }
    params.append('limit', PAGE_SIZE.toString())
    params.append('offset', ((filters.page - 1) * PAGE_SIZE).toString())

    const response = await makeAuthenticatedRequest(`/admin/escalations?${params}`)
    if (!response.ok) {
      throw new Error(`Failed to fetch escalations. Status: ${response.status}`)
    }
    return response.json()
  }, [activeTab, filters.channel, filters.priority, filters.page, debouncedSearchText])

  const fetchCounts = useCallback(async (): Promise<EscalationCounts> => {
    const response = await makeAuthenticatedRequest('/admin/escalations/counts')
    if (!response.ok) {
      throw new Error(`Failed to fetch escalation counts. Status: ${response.status}`)
    }
    return response.json()
  }, [])

  const escalationListQuery = useAdminPollingQuery<EscalationListResponse, readonly unknown[]>({
    queryKey: [
      'admin',
      'escalations',
      {
        status: activeTab,
        channel: filters.channel,
        priority: filters.priority,
        search: debouncedSearchText,
        page: filters.page,
      },
    ] as const,
    queryFn: fetchEscalations,
    enabled: initializedFromUrl,
    placeholderData: (previousData) => previousData,
  })

  const escalationCountsQuery = useAdminPollingQuery<EscalationCounts, readonly unknown[]>({
    queryKey: ['admin', 'escalations', 'counts'] as const,
    queryFn: fetchCounts,
    enabled: initializedFromUrl,
  })

  const escalations = escalationListQuery.data?.escalations ?? []
  const totalCount = escalationListQuery.data?.total ?? 0
  const counts = escalationCountsQuery.data ?? null
  const totalPages = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))
  const isLoading = !initializedFromUrl || escalationListQuery.isLoading || escalationCountsQuery.isLoading
  const isRefreshing = isManualRefresh || escalationListQuery.isFetching || escalationCountsQuery.isFetching
  const error = escalationListQuery.error?.message || escalationCountsQuery.error?.message || null
  const visibleError = error && error !== dismissedError ? error : null
  const statusTabs = [
    { key: 'all' as const, label: 'All Cases', count: counts?.total ?? 0, icon: Users },
    { key: 'pending' as const, label: 'Pending', count: counts?.pending ?? 0, icon: AlertCircle },
    { key: 'in_review' as const, label: 'In Review', count: counts?.in_review ?? 0, icon: Eye },
    { key: 'responded' as const, label: 'Responded', count: counts?.responded ?? 0, icon: BadgeCheck },
    { key: 'closed' as const, label: 'Closed', count: counts?.closed ?? 0, icon: Clock },
  ]

  const refreshData = useCallback(async () => {
    setDismissedError(null)
    setIsManualRefresh(true)
    try {
      await Promise.all([escalationListQuery.refetch(), escalationCountsQuery.refetch()])
    } finally {
      setIsManualRefresh(false)
    }
  }, [escalationListQuery, escalationCountsQuery])

  // Initialize tab/filters from URL once.
  useEffect(() => {
    if (initializedFromUrl) return

    const statusParam = searchParams.get("status")
    const channelParam = searchParams.get("channel")
    const priorityParam = searchParams.get("priority")
    const searchParam = searchParams.get("search")
    const pageParam = searchParams.get("page")

    const status: 'all' | 'pending' | 'in_review' | 'responded' | 'closed' =
      (statusParam === "pending" || statusParam === "in_review" || statusParam === "responded" || statusParam === "closed") ? statusParam : "all"
    const channel: 'all' | 'web' | 'matrix' | 'bisq2' =
      (channelParam === "web" || channelParam === "matrix" || channelParam === "bisq2") ? channelParam : "all"
    const priority: 'all' | 'high' | 'normal' =
      (priorityParam === "high" || priorityParam === "normal") ? priorityParam : "all"
    const page = Math.max(1, Number(pageParam || "1") || 1)

    setActiveTab(status)
    setFilters(prev => ({
      ...prev,
      channel,
      priority,
      search_text: searchParam ? String(searchParam) : "",
      page,
    }))
    setInitializedFromUrl(true)
  }, [initializedFromUrl, searchParams])

  useEffect(() => {
    const updatedAt = Math.max(
      escalationListQuery.dataUpdatedAt || 0,
      escalationCountsQuery.dataUpdatedAt || 0,
    )
    if (updatedAt > 0) {
      setLastUpdatedAt(new Date(updatedAt))
    }
  }, [escalationListQuery.dataUpdatedAt, escalationCountsQuery.dataUpdatedAt])

  useEffect(() => {
    if (!initializedFromUrl || !escalationListQuery.data) return
    if (filters.page > totalPages) {
      setFilters((prev) => ({ ...prev, page: totalPages }))
    }
  }, [initializedFromUrl, escalationListQuery.data, filters.page, totalPages])

  // Keep URL in sync with filters/tabs/pagination (deep-linkable state).
  useEffect(() => {
    if (!initializedFromUrl) return

    const params = new URLSearchParams()
    if (activeTab !== "all") params.set("status", activeTab)
    if (filters.channel !== "all") params.set("channel", filters.channel)
    if (filters.priority !== "all") params.set("priority", filters.priority)
    if (debouncedSearchText.trim()) params.set("search", debouncedSearchText.trim())
    if (filters.page > 1) params.set("page", String(filters.page))

    const qs = params.toString()
    startUrlTransition(() => {
      router.replace(qs ? `?${qs}` : "/admin/escalations", { scroll: false })
    })
  }, [initializedFromUrl, router, activeTab, filters.channel, filters.priority, debouncedSearchText, filters.page, startUrlTransition])

  // --- Handlers ---

  const handleFilterChange = (key: string, value: string | number) => {
    setFilters(prev => ({
      ...prev,
      [key]: value,
      page: key === 'page' ? (value as number) : 1,
    }))
    if (key !== "page") {
      setSelectedEscalationIndex(-1)
    }
  }

  const resetFilters = () => {
    setFilters({
      channel: 'all',
      priority: 'all',
      search_text: '',
      page: 1,
    })
    setSelectedEscalationIndex(-1)
  }

  const handleTabChange = (tab: 'all' | 'pending' | 'in_review' | 'responded' | 'closed') => {
    setActiveTab(tab)
    setFilters(prev => ({ ...prev, page: 1 }))
    setSelectedEscalationIndex(-1)
  }

  const openReviewPanel = (escalation: EscalationItem) => {
    setSelectedEscalation(escalation)
    setShowReviewPanel(true)
  }

  const handleReviewOpenChange = (open: boolean) => {
    setShowReviewPanel(open)
    if (!open) {
      setSelectedEscalation(null)
    }
  }

  const formatAbsoluteTime = (timestamp: string): string => {
    try {
      return new Intl.DateTimeFormat('en-US', {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      }).format(new Date(timestamp))
    } catch {
      return timestamp
    }
  }

  const handleEscalationUpdated = () => {
    void refreshData()
  }

  useEffect(() => {
    if (escalations.length === 0) {
      setSelectedEscalationIndex(-1)
      return
    }
    if (selectedEscalationIndex >= escalations.length) {
      setSelectedEscalationIndex(escalations.length - 1)
    }
  }, [escalations.length, selectedEscalationIndex])

  useHotkeys(
    "/",
    (event) => {
      event.preventDefault()
      searchInputRef.current?.focus()
    },
    { enableOnFormTags: false },
    [],
  )

  useHotkeys(
    "j",
    (event) => {
      event.preventDefault()
      if (!escalations.length || showReviewPanel) return
      setSelectedEscalationIndex((prev) => {
        if (prev < 0) return 0
        return Math.min(prev + 1, escalations.length - 1)
      })
    },
    { enableOnFormTags: false },
    [escalations, showReviewPanel],
  )

  useHotkeys(
    "k",
    (event) => {
      event.preventDefault()
      if (!escalations.length || showReviewPanel) return
      setSelectedEscalationIndex((prev) => Math.max(prev - 1, 0))
    },
    { enableOnFormTags: false },
    [escalations, showReviewPanel],
  )

  useHotkeys(
    "o",
    (event) => {
      event.preventDefault()
      if (showReviewPanel) return
      const selected = selectedEscalationIndex >= 0 ? escalations[selectedEscalationIndex] : escalations[0]
      if (!selected) return
      openReviewPanel(selected)
    },
    { enableOnFormTags: false },
    [showReviewPanel, selectedEscalationIndex, escalations],
  )

  useHotkeys(
    "e",
    (event) => {
      event.preventDefault()
      if (showReviewPanel) return
      const selected = selectedEscalationIndex >= 0 ? escalations[selectedEscalationIndex] : escalations[0]
      if (!selected) return
      openReviewPanel(selected)
    },
    { enableOnFormTags: false },
    [showReviewPanel, selectedEscalationIndex, escalations],
  )

  useHotkeys(
    "r",
    (event) => {
      event.preventDefault()
      void refreshData()
    },
    { enableOnFormTags: false },
    [refreshData],
  )

  // --- Render ---

  return (
    <TooltipProvider>
      <AdminQueueShell showVectorStoreBanner shortcutHints={shortcutHints}>
      <QueuePageHeader
        title="Escalation Queue"
        description="Review, respond, and close escalated support cases across channels."
        lastUpdatedLabel={lastUpdatedAt ? `Updated ${formatTimeAgo(lastUpdatedAt.toISOString())}` : null}
        isRefreshing={isRefreshing}
        onRefresh={() => { void refreshData() }}
        rightSlot={(
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" className="text-xs text-muted-foreground hover:text-foreground">
                <Info className="h-3.5 w-3.5 mr-1.5" />
                Case definitions
                <ChevronDown className="h-3.5 w-3.5 ml-1" />
              </Button>
            </PopoverTrigger>
            <PopoverContent
              align="end"
              sideOffset={8}
              className="w-[min(420px,calc(100vw-2rem))] rounded-lg border border-border/60 bg-card/95 p-3 text-xs text-muted-foreground shadow-lg backdrop-blur supports-[backdrop-filter]:bg-card/80"
            >
              <p className="mb-2">
                <span className="font-medium text-foreground">Pending:</span> waiting for staff triage or response.
              </p>
              <p className="mb-2">
                <span className="font-medium text-foreground">In Review:</span> actively handled by support staff.
              </p>
              <p>
                <span className="font-medium text-foreground">Responded/Closed:</span> delivered response or finalized case.
              </p>
            </PopoverContent>
          </Popover>
        )}
      />

      <QueueTabs
        tabs={statusTabs}
        activeTab={activeTab}
        onTabChange={handleTabChange}
        gridClassName="grid-cols-2 xl:grid-cols-5"
      />

      {visibleError && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg" role="alert">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{visibleError}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setDismissedError(visibleError)}
            className="ml-auto text-red-400/60 hover:text-red-400 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      <QueueCommandBar activeFilterPills={activeFilterPills}>
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative flex-1 min-w-[240px]">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              ref={searchInputRef}
              placeholder="Search questions, users, and escalation context..."
              value={filters.search_text}
              onChange={(e) => handleFilterChange('search_text', e.target.value)}
              className="pl-9 pr-8"
              autoComplete="off"
            />
            {filters.search_text && (
              <button
                type="button"
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

          <Select value={filters.priority} onValueChange={(value) => handleFilterChange('priority', value)}>
            <SelectTrigger className="w-[130px]">
              <SelectValue placeholder="Priority" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Priorities</SelectItem>
              <SelectItem value="high">High</SelectItem>
              <SelectItem value="normal">Normal</SelectItem>
            </SelectContent>
          </Select>

          <Button
            onClick={resetFilters}
            variant="outline"
            size="sm"
            className="border-border"
            disabled={!hasActiveFilters}
          >
            <RotateCcw className="mr-2 h-4 w-4" />
            Reset filters
            {hasActiveFilters && (
              <Badge variant="secondary" className="ml-2 h-5 min-w-5 px-1.5 text-[10px] tabular-nums">
                {activeFilterCount}
              </Badge>
            )}
          </Button>
        </div>
      </QueueCommandBar>

      {/* Escalation List */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base">Escalation Queue</CardTitle>
              <CardDescription className="mt-0.5">
                {activeTab === 'all' && 'All escalated questions'}
                {activeTab === 'pending' && 'Awaiting staff review'}
                {activeTab === 'in_review' && 'Currently being reviewed'}
                {activeTab === 'responded' && 'Staff response provided'}
                {activeTab === 'closed' && 'Resolved and archived'}
                <span className="ml-1 tabular-nums">
                  · {totalCount} {totalCount === 1 ? 'item' : 'items'}
                </span>
              </CardDescription>
            </div>
            {totalPages > 1 && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <span className="tabular-nums">Page {filters.page} of {totalPages}</span>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          {isLoading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="border border-border rounded-lg p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <Skeleton className="h-4 w-4 rounded-full" />
                    <Skeleton className="h-3 w-28" />
                    <Skeleton className="h-4 w-14 rounded-full" />
                  </div>
                  <Skeleton className="h-3 w-3/4 mb-2" />
                  <Skeleton className="h-3 w-1/2" />
                </div>
              ))}
            </div>
          ) : escalations.length === 0 ? (
            <div className="text-center py-16">
              <div className="inline-flex items-center justify-center w-14 h-14 rounded-full bg-muted mb-4">
                <Users className="h-6 w-6 text-muted-foreground" />
              </div>
              <h3 className="text-base font-semibold mb-1">No escalations found</h3>
              <p className="text-sm text-muted-foreground mb-4 max-w-sm mx-auto">
                {hasActiveFilters
                  ? 'No escalations match your current filters. Try adjusting or resetting them.'
                  : activeTab === 'pending'
                    ? 'No pending escalations. The queue is clear.'
                    : activeTab === 'in_review'
                      ? 'No escalations currently in review.'
                      : activeTab === 'responded'
                        ? 'No responded escalations to display.'
                        : activeTab === 'closed'
                          ? 'No closed escalations to display.'
                        : 'No escalations have been created yet.'}
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
              {escalations.map((escalation, index) => {
                const channelBadge = getChannelBadge(escalation.channel)
                const statusBadge = getStatusBadge(escalation.status)
                const priorityBadge = getPriorityBadge(escalation.priority)
                const ageBadge = getEscalationAgeBadge(escalation.created_at, escalation.status)
                const isKeyboardSelected = index === selectedEscalationIndex
                const caseTags = [
                  { label: statusBadge.label, className: statusBadge.className },
                  { label: `Priority: ${priorityBadge.label}`, className: priorityBadge.className },
                  ...(ageBadge ? [{ label: ageBadge.label, className: ageBadge.className }] : []),
                  ...(typeof escalation.confidence_score === "number"
                    ? [{
                      label: `${(escalation.confidence_score * 100).toFixed(0)}% confidence`,
                      className: escalation.confidence_score < 0.3
                        ? "bg-red-500/15 text-red-400"
                        : escalation.confidence_score < 0.7
                          ? "bg-yellow-500/15 text-yellow-400"
                          : "bg-emerald-500/15 text-emerald-400",
                    }]
                    : []),
                  ...(escalation.staff_id
                    ? [{ label: `Owner: ${escalation.staff_id}`, className: "bg-primary/15 text-primary border border-primary/25" }]
                    : []),
                ]
                const primaryTags = caseTags.slice(0, 2)
                const overflowTags = caseTags.slice(2)
                const rawRouting = normalizeRoutingReasonSourceCount(
                  String(escalation.routing_reason || escalation.routing_action || "").trim(),
                  escalation.sources?.length,
                )
                const shouldShowRouting = Boolean(rawRouting) && rawRouting.toLowerCase() !== "needs_human"
                const routingLabel = (!/\s/.test(rawRouting) || /[_-]/.test(rawRouting))
                  ? humanizeEnumValue(rawRouting)
                  : rawRouting

                return (
                  <div
                    key={String(escalation.id)}
                    className={`group touch-manipulation relative border rounded-lg transition-colors hover:bg-accent/30 cursor-pointer ${
                      escalation.priority === 'high'
                          ? 'border-l-2 border-l-orange-500/50 border-t border-r border-b border-border'
                          : 'border border-border'
                    } text-left w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                      isKeyboardSelected ? 'ring-1 ring-primary/60 bg-accent/30' : ''
                    }`}
                    onClick={() => {
                      setSelectedEscalationIndex(index)
                      openReviewPanel(escalation)
                    }}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelectedEscalationIndex(index)
                        openReviewPanel(escalation)
                      }
                    }}
                    onMouseEnter={() => setSelectedEscalationIndex(index)}
                  >
                    <div className="p-4">
                      <div className="flex items-start gap-3">
                        <div className="flex-1 min-w-0 space-y-1.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <Tooltip>
                              <TooltipTrigger asChild>
                                <span className="text-xs text-muted-foreground tabular-nums">
                                  {formatTimeAgo(escalation.created_at)}
                                </span>
                              </TooltipTrigger>
                              <TooltipContent>
                                {formatAbsoluteTime(escalation.created_at)}
                              </TooltipContent>
                            </Tooltip>
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${channelBadge.className}`}>
                              {channelBadge.label}
                            </span>
                            {primaryTags.map((tag) => (
                              <span key={tag.label} className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${tag.className}`}>
                                {tag.label}
                              </span>
                            ))}
                            {escalation.user_language && escalation.user_language !== "en" && (
                              <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-slate-500/15 text-slate-300 border border-slate-500/25">
                                User: {escalation.user_language.toUpperCase()}
                              </span>
                            )}
                            {overflowTags.length > 0 && (
                              <DropdownMenu>
                                <DropdownMenuTrigger asChild>
                                  <Button
                                    variant="ghost"
                                    size="sm"
                                    className="h-5 px-1.5 text-[10px] text-muted-foreground"
                                    onClick={(event) => event.stopPropagation()}
                                  >
                                    +{overflowTags.length} more
                                  </Button>
                                </DropdownMenuTrigger>
                                <DropdownMenuContent align="start" onClick={(event) => event.stopPropagation()}>
                                  {overflowTags.map((tag) => (
                                    <div key={tag.label} className="px-2 py-1.5 text-xs text-muted-foreground">
                                      {tag.label}
                                    </div>
                                  ))}
                                </DropdownMenuContent>
                              </DropdownMenu>
                            )}
                          </div>

                          <p className="text-sm leading-relaxed line-clamp-2">
                            {getPrimaryQuestion(escalation)}
                          </p>

                          {escalation.question_original && escalation.question_original.trim() && escalation.question_original.trim() !== getPrimaryQuestion(escalation) && (
                            <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                              Original: {escalation.question_original.trim()}
                            </p>
                          )}

                          {shouldShowRouting && (
                            <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                              Escalated: {routingLabel}
                            </p>
                          )}
                        </div>

                      </div>
                    </div>
                  </div>
                )
              })}

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between pt-4 border-t border-border mt-2">
                  <p className="text-xs text-muted-foreground tabular-nums">
                    {((filters.page - 1) * PAGE_SIZE) + 1}–{Math.min(filters.page * PAGE_SIZE, totalCount)} of {totalCount}
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
                    {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                      const pageNum = Math.max(1, Math.min(totalPages - 4, filters.page - 2)) + i
                      if (pageNum > totalPages) return null
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
                      )
                    })}
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={() => handleFilterChange('page', Math.min(totalPages, filters.page + 1))}
                      disabled={filters.page >= totalPages}
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

      {/* Review Panel */}
      {selectedEscalation && (
        <EscalationReviewPanel
          key={selectedEscalation.id}
          escalation={selectedEscalation}
          open={showReviewPanel}
          onOpenChange={handleReviewOpenChange}
          onUpdated={handleEscalationUpdated}
        />
      )}
      </AdminQueueShell>
    </TooltipProvider>
  )
}
