"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useRouter, useSearchParams } from "next/navigation"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import { Skeleton } from "@/components/ui/skeleton"
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip"
import {
  Filter,
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
  Loader2,
} from 'lucide-react'
import { makeAuthenticatedRequest } from '@/lib/auth'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { EscalationReviewPanel } from './EscalationReviewPanel'

// --- Types ---

export interface EscalationItem {
  id: number
  message_id: string
  channel: string
  user_id: string
  username?: string | null
  channel_metadata?: Record<string, unknown> | null
  question: string
  ai_draft_answer: string
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

const PAGE_SIZE = 20

// --- Component ---

export default function EscalationsPage() {
  const router = useRouter()
  const searchParams = useSearchParams()

  // Data state
  const [escalations, setEscalations] = useState<EscalationItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [counts, setCounts] = useState<EscalationCounts | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null)

  // Filter state
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'in_review' | 'responded'>('all')
  const [filters, setFilters] = useState({
    channel: 'all',
    priority: 'all',
    search_text: '',
    page: 1,
  })
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [initializedFromUrl, setInitializedFromUrl] = useState(false)

  // Review panel
  const [selectedEscalation, setSelectedEscalation] = useState<EscalationItem | null>(null)
  const [showReviewPanel, setShowReviewPanel] = useState(false)

  const debouncedSearchText = useDebouncedValue(filters.search_text, 300)

  // Refs for smart refresh
  const previousDataHashRef = useRef<string>('')

  // Computed
  const activeFilterCount = useMemo(() => {
    return [
      filters.search_text,
      filters.channel !== 'all',
      filters.priority !== 'all',
    ].filter(Boolean).length
  }, [filters])

  const hasActiveFilters = activeFilterCount > 0
  const totalPages = Math.ceil(totalCount / PAGE_SIZE)

  // --- Data Fetching ---

  const fetchEscalations = useCallback(async () => {
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

    if (response.ok) {
      const data: EscalationListResponse = await response.json()
      const dataHash = JSON.stringify(data)

      if (dataHash !== previousDataHashRef.current) {
        previousDataHashRef.current = dataHash
        setEscalations(data.escalations)
        setTotalCount(data.total)
      }
    } else {
      throw new Error(`Failed to fetch escalations. Status: ${response.status}`)
    }
  }, [activeTab, filters.channel, filters.priority, filters.page, debouncedSearchText])

  const fetchCounts = useCallback(async () => {
    const response = await makeAuthenticatedRequest('/admin/escalations/counts')

    if (response.ok) {
      const data: EscalationCounts = await response.json()
      setCounts(data)
    }
  }, [])

  const fetchData = useCallback(async (isBackgroundRefresh = false) => {
    if (!isBackgroundRefresh) {
      setIsLoading(true)
    } else {
      setIsRefreshing(true)
    }

    try {
      await Promise.all([fetchEscalations(), fetchCounts()])
      setError(null)
      setLastUpdatedAt(new Date())
    } catch (err) {
      console.error('Error fetching escalation data:', err)
      if (!isBackgroundRefresh) {
        setError('Failed to fetch escalation data')
      }
    } finally {
      if (!isBackgroundRefresh) {
        setIsLoading(false)
      } else {
        setIsRefreshing(false)
      }
    }
  }, [fetchEscalations, fetchCounts])

  // Initialize tab/filters from URL once.
  useEffect(() => {
    if (initializedFromUrl) return

    const statusParam = searchParams.get("status")
    const channelParam = searchParams.get("channel")
    const priorityParam = searchParams.get("priority")
    const searchParam = searchParams.get("search")
    const pageParam = searchParams.get("page")

    const status: 'all' | 'pending' | 'in_review' | 'responded' =
      (statusParam === "pending" || statusParam === "in_review" || statusParam === "responded") ? statusParam : "all"
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
    if (!initializedFromUrl) return
    fetchData()
  }, [initializedFromUrl, fetchData])

  // Auto-refresh every 30 seconds
  useEffect(() => {
    if (!initializedFromUrl) return
    const intervalId = setInterval(() => {
      fetchData(true)
    }, 30000)
    return () => clearInterval(intervalId)
  }, [initializedFromUrl, fetchData])

  // Keep URL in sync with filters/tabs/pagination (deep-linkable state).
  useEffect(() => {
    if (!initializedFromUrl) return

    const params = new URLSearchParams()
    if (activeTab !== "all") params.set("status", activeTab)
    if (filters.channel !== "all") params.set("channel", filters.channel)
    if (filters.priority !== "all") params.set("priority", filters.priority)
    if (filters.search_text.trim()) params.set("search", filters.search_text.trim())
    if (filters.page > 1) params.set("page", String(filters.page))

    const qs = params.toString()
    router.replace(qs ? `?${qs}` : "/admin/escalations", { scroll: false })
  }, [initializedFromUrl, router, activeTab, filters.channel, filters.priority, filters.search_text, filters.page])

  // --- Handlers ---

  const handleFilterChange = (key: string, value: string | number) => {
    setFilters(prev => ({
      ...prev,
      [key]: value,
      page: key === 'page' ? (value as number) : 1,
    }))
  }

  const resetFilters = () => {
    setFilters({
      channel: 'all',
      priority: 'all',
      search_text: '',
      page: 1,
    })
  }

  const handleTabChange = (tab: 'all' | 'pending' | 'in_review' | 'responded') => {
    setActiveTab(tab)
    setFilters(prev => ({ ...prev, page: 1 }))
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
    fetchData()
  }

  // --- Render ---

  return (
    <TooltipProvider>
      <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Escalation Queue</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Review and respond to escalated support questions
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastUpdatedAt && (
            <div className="hidden sm:flex items-center gap-2 text-xs text-muted-foreground">
              {isRefreshing && <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />}
              <span className="tabular-nums">Updated {formatTimeAgo(lastUpdatedAt.toISOString())}</span>
            </div>
          )}
          <Button
            onClick={() => setFiltersOpen(true)}
            variant="outline"
            size="sm"
            className="border-border hover:border-primary"
            aria-haspopup="dialog"
            aria-expanded={filtersOpen}
            >
            <Filter className="mr-2 h-4 w-4" />
            Filters
            {hasActiveFilters && (
              <Badge variant="secondary" className="ml-2 h-5 w-5 p-0 flex items-center justify-center text-xs rounded-full">
                {activeFilterCount}
              </Badge>
            )}
          </Button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg" role="alert">
          <AlertCircle className="h-4 w-4 shrink-0" />
          <span className="text-sm">{error}</span>
          <button
            type="button"
            aria-label="Dismiss error"
            onClick={() => setError(null)}
            className="ml-auto text-red-400/60 hover:text-red-400 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Status Picker (harmonized "queue cards" style like Training) */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {([
          { key: 'all' as const, label: 'All', description: 'Everything in the queue', count: counts?.total, icon: Users },
          { key: 'pending' as const, label: 'Pending', description: 'Awaiting staff review', count: counts?.pending, icon: AlertCircle },
          { key: 'in_review' as const, label: 'In Review', description: 'Currently being reviewed', count: counts?.in_review, icon: Eye },
          { key: 'responded' as const, label: 'Responded', description: 'Staff response provided', count: counts?.responded, icon: BadgeCheck },
        ]).map((item) => {
          const isSelected = activeTab === item.key
          const Icon = item.icon
          const count = item.count ?? 0
          return (
            <button
              key={item.key}
              type="button"
              onClick={() => handleTabChange(item.key)}
              className={`touch-manipulation text-left rounded-lg border border-border bg-card p-4 transition-colors hover:bg-accent/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 ${
                isSelected ? 'ring-2 ring-primary ring-offset-2' : ''
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
                  className={`text-lg font-bold tabular-nums ${count > 0 ? 'text-foreground' : 'text-muted-foreground'}`}
                  aria-label={`${item.label} count ${count}`}
                >
                  {count}
                </span>
              </div>
            </button>
          )
        })}
      </div>

      {/* Filters Sheet */}
      <Sheet open={filtersOpen} onOpenChange={setFiltersOpen}>
        <SheetContent side="right" className="w-full sm:max-w-md flex flex-col overscroll-contain">
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Refine the escalation queue.</SheetDescription>
          </SheetHeader>

          <div className="mt-6 flex-1 space-y-4 overflow-y-auto overscroll-contain pr-1">
            <div className="space-y-1.5">
              <Label htmlFor="escalations-filter-search" className="text-xs text-muted-foreground">Search</Label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  id="escalations-filter-search"
                  name="search"
                  placeholder="Search questions…"
                  value={filters.search_text}
                  onChange={(e) => handleFilterChange('search_text', e.target.value)}
                  className="pl-9"
                  autoComplete="off"
                />
                {filters.search_text && (
                  <button
                    type="button"
                    aria-label="Clear search"
                    onClick={() => handleFilterChange('search_text', '')}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="escalations-filter-channel" className="text-xs text-muted-foreground">Channel</Label>
              <Select
                value={filters.channel}
                onValueChange={(value) => handleFilterChange('channel', value)}
              >
                <SelectTrigger id="escalations-filter-channel">
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
              <Label htmlFor="escalations-filter-priority" className="text-xs text-muted-foreground">Priority</Label>
              <Select
                value={filters.priority}
                onValueChange={(value) => handleFilterChange('priority', value)}
              >
                <SelectTrigger id="escalations-filter-priority">
                  <SelectValue placeholder="All priorities" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Priorities</SelectItem>
                  <SelectItem value="high">High</SelectItem>
                  <SelectItem value="normal">Normal</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          <SheetFooter className="mt-6 gap-2 sm:gap-2">
            {hasActiveFilters && (
              <Button onClick={resetFilters} variant="outline" size="sm" className="sm:mr-auto">
                <RotateCcw className="mr-2 h-4 w-4" />
                Reset filters
              </Button>
            )}
            <SheetClose asChild>
              <Button variant="default" size="sm">Done</Button>
            </SheetClose>
          </SheetFooter>
        </SheetContent>
      </Sheet>

      {/* Active filters */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-2">
          {filters.search_text && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              onClick={() => handleFilterChange('search_text', '')}
              aria-label="Clear search filter"
            >
              Search: <span className="text-foreground/90 inline-block max-w-[220px] truncate align-bottom">{filters.search_text}</span>
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
          {filters.channel !== 'all' && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              onClick={() => handleFilterChange('channel', 'all')}
              aria-label="Clear channel filter"
            >
              Channel: <span className="text-foreground/90">{filters.channel}</span>
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
          {filters.priority !== 'all' && (
            <button
              type="button"
              className="inline-flex items-center gap-1 rounded-full border border-border bg-card px-2 py-1 text-xs text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
              onClick={() => handleFilterChange('priority', 'all')}
              aria-label="Clear priority filter"
            >
              Priority: <span className="text-foreground/90">{filters.priority}</span>
              <X className="h-3 w-3" aria-hidden="true" />
            </button>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 px-2 text-xs text-muted-foreground hover:text-foreground"
            onClick={resetFilters}
          >
            Clear all
          </Button>
        </div>
      )}

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
              {escalations.map((escalation) => {
                const channelBadge = getChannelBadge(escalation.channel)
                const statusBadge = getStatusBadge(escalation.status)
                const priorityBadge = getPriorityBadge(escalation.priority)
                const PriorityIcon = priorityBadge.icon

                return (
                  <button
                    key={String(escalation.id)}
                    type="button"
                    className={`group touch-manipulation relative border rounded-lg transition-colors hover:bg-accent/30 cursor-pointer ${
                      escalation.priority === 'high'
                          ? 'border-l-2 border-l-orange-500/50 border-t border-r border-b border-border'
                          : 'border border-border'
                    } text-left w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2`}
                    onClick={() => openReviewPanel(escalation)}
                  >
                    <div className="p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0 space-y-1.5">
                          {/* Meta row */}
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
                            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${priorityBadge.className}`}>
                              {PriorityIcon && <PriorityIcon className="h-2.5 w-2.5" />}
                              {priorityBadge.label}
                            </span>
                            <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${statusBadge.className}`}>
                              {statusBadge.label}
                            </span>
                            {typeof escalation.confidence_score === "number" && (
                              <span
                                className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${
                                  escalation.confidence_score < 0.3
                                    ? "bg-red-500/15 text-red-400"
                                    : escalation.confidence_score < 0.7
                                      ? "bg-yellow-500/15 text-yellow-400"
                                      : "bg-emerald-500/15 text-emerald-400"
                                }`}
                                aria-label={`AI confidence ${(escalation.confidence_score * 100).toFixed(0)} percent`}
                              >
                                {(escalation.confidence_score * 100).toFixed(0)}%
                              </span>
                            )}
                            {escalation.staff_id && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-primary/15 text-primary border border-primary/25">
                                <Users className="h-2.5 w-2.5" />
                                {escalation.staff_id}
                              </span>
                            )}
                          </div>

                          {/* Question preview */}
                          <p className="text-sm leading-relaxed line-clamp-2">
                            {escalation.question}
                          </p>

                          {/* Reason */}
                          {(() => {
                            const rawRouting = String(escalation.routing_reason || escalation.routing_action || "").trim()
                            const shouldShow = Boolean(rawRouting) && rawRouting.toLowerCase() !== "needs_human"
                            if (!shouldShow) return null
                            const routingLabel = (!/\s/.test(rawRouting) || /[_-]/.test(rawRouting))
                              ? humanizeEnumValue(rawRouting)
                              : rawRouting
                            return (
                              <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                                Escalated: {routingLabel}
                              </p>
                            )
                          })()}
                        </div>

                        <div className="ml-3 opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity duration-150 shrink-0 text-muted-foreground">
                          <Eye className="h-4 w-4" aria-hidden="true" />
                        </div>
                      </div>
                    </div>
                  </button>
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
      </div>
    </TooltipProvider>
  )
}
