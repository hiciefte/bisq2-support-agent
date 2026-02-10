"use client"

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Label } from "@/components/ui/label"
import {
  Filter,
  RotateCcw,
  Search,
  ChevronLeft,
  ChevronRight,
  AlertCircle,
  X,
  Clock,
  AlertTriangle,
  Users,
  Eye,
} from 'lucide-react'
import { makeAuthenticatedRequest } from '@/lib/auth'
import { EscalationReviewPanel } from './EscalationReviewPanel'

// --- Types ---

export interface EscalationItem {
  id: string
  message_id: string
  channel: string
  question: string
  ai_answer: string
  ai_confidence: number
  reason: string
  priority: 'urgent' | 'high' | 'normal'
  status: 'pending' | 'in_review' | 'responded' | 'closed'
  staff_id?: string
  staff_answer?: string
  sources?: Array<{ title: string; type: string; content: string }>
  created_at: string
  updated_at: string
  responded_at?: string
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

function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState<T>(value)
  useEffect(() => {
    const handler = setTimeout(() => setDebouncedValue(value), delay)
    return () => clearTimeout(handler)
  }, [value, delay])
  return debouncedValue
}

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
    'urgent': { label: 'Urgent', className: 'bg-red-500/15 text-red-400', icon: AlertTriangle },
    'high': { label: 'High', className: 'bg-orange-500/15 text-orange-400', icon: AlertTriangle },
    'normal': { label: 'Normal', className: 'bg-muted text-muted-foreground', icon: null },
  }
  return badges[priority] || { label: priority, className: 'bg-muted text-muted-foreground', icon: null }
}

const PAGE_SIZE = 20

// --- Component ---

export default function EscalationsPage() {
  // Data state
  const [escalations, setEscalations] = useState<EscalationItem[]>([])
  const [totalCount, setTotalCount] = useState(0)
  const [counts, setCounts] = useState<EscalationCounts | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Filter state
  const [activeTab, setActiveTab] = useState<'all' | 'pending' | 'in_review' | 'responded'>('all')
  const [filters, setFilters] = useState({
    channel: 'all',
    priority: 'all',
    search_text: '',
    page: 1,
  })
  const [showFilters, setShowFilters] = useState(false)

  // Review panel
  const [selectedEscalation, setSelectedEscalation] = useState<EscalationItem | null>(null)
  const [showReviewPanel, setShowReviewPanel] = useState(false)

  const debouncedSearchText = useDebounce(filters.search_text, 300)

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
    }

    try {
      await Promise.all([fetchEscalations(), fetchCounts()])
      setError(null)
    } catch (err) {
      console.error('Error fetching escalation data:', err)
      if (!isBackgroundRefresh) {
        setError('Failed to fetch escalation data')
      }
    } finally {
      if (!isBackgroundRefresh) {
        setIsLoading(false)
      }
    }
  }, [fetchEscalations, fetchCounts])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  // Auto-refresh every 30 seconds
  useEffect(() => {
    const intervalId = setInterval(() => {
      fetchData(true)
    }, 30000)
    return () => clearInterval(intervalId)
  }, [fetchData])

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

  const handleEscalationUpdated = () => {
    fetchData()
  }

  // --- Render ---

  return (
    <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Escalation Queue</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Review and respond to escalated support questions
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => setShowFilters(!showFilters)}
            variant="outline"
            size="sm"
            className={`border-border transition-colors ${showFilters ? 'bg-accent border-primary' : 'hover:border-primary'}`}
          >
            <Filter className="mr-2 h-4 w-4" />
            Filters
            {hasActiveFilters && (
              <Badge variant="secondary" className="ml-2 h-5 w-5 p-0 flex items-center justify-center text-xs rounded-full">
                {activeFilterCount}
              </Badge>
            )}
          </Button>
          <Button
            onClick={() => fetchData()}
            variant="outline"
            size="sm"
            className="border-border hover:border-primary"
          >
            <RotateCcw className="mr-2 h-4 w-4" />
            Refresh
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
            { key: 'all' as const, label: 'All', count: counts?.total },
            { key: 'pending' as const, label: 'Pending', count: counts?.pending },
            { key: 'in_review' as const, label: 'In Review', count: counts?.in_review },
            { key: 'responded' as const, label: 'Responded', count: counts?.responded },
          ]).map(tab => (
            <button
              key={tab.key}
              className={`px-4 py-2.5 font-medium text-sm rounded-t-lg transition-all relative ${
                activeTab === tab.key
                  ? 'text-primary'
                  : 'text-muted-foreground hover:text-card-foreground'
              }`}
              onClick={() => handleTabChange(tab.key)}
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

      {/* Filters Panel */}
      <div className={`grid transition-all duration-300 ease-in-out ${showFilters ? 'grid-rows-[1fr] opacity-100' : 'grid-rows-[0fr] opacity-0'}`}>
        <div className="overflow-hidden">
          <Card className="border-primary/20">
            <CardContent className="pt-5 pb-4 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="space-y-1.5 md:col-span-1">
                  <Label className="text-xs text-muted-foreground">Search</Label>
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                      placeholder="Search questions..."
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
                  <Label className="text-xs text-muted-foreground">Priority</Label>
                  <Select
                    value={filters.priority}
                    onValueChange={(value) => handleFilterChange('priority', value)}
                  >
                    <SelectTrigger>
                      <SelectValue placeholder="All priorities" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Priorities</SelectItem>
                      <SelectItem value="urgent">Urgent</SelectItem>
                      <SelectItem value="high">High</SelectItem>
                      <SelectItem value="normal">Normal</SelectItem>
                    </SelectContent>
                  </Select>
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
                  -- {totalCount} {totalCount === 1 ? 'item' : 'items'}
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
                  <div
                    key={escalation.id}
                    className={`group relative border rounded-lg transition-colors hover:bg-accent/30 cursor-pointer ${
                      escalation.priority === 'urgent'
                        ? 'border-l-2 border-l-red-500/50 border-t border-r border-b border-border'
                        : escalation.priority === 'high'
                          ? 'border-l-2 border-l-orange-500/50 border-t border-r border-b border-border'
                          : 'border border-border'
                    }`}
                    onClick={() => openReviewPanel(escalation)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => { if (e.key === 'Enter') openReviewPanel(escalation) }}
                  >
                    <div className="p-4">
                      <div className="flex items-start justify-between">
                        <div className="flex-1 min-w-0 space-y-1.5">
                          {/* Meta row */}
                          <div className="flex items-center gap-2 flex-wrap">
                            <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                            <span className="text-xs text-muted-foreground tabular-nums">
                              {formatTimeAgo(escalation.created_at)}
                            </span>
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
                          {escalation.reason && (
                            <p className="text-xs text-muted-foreground line-clamp-1 mt-0.5">
                              Reason: {escalation.reason}
                            </p>
                          )}
                        </div>

                        {/* Action button - visible on hover */}
                        <div className="flex items-center gap-0.5 ml-3 opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity duration-150 shrink-0">
                          <Button
                            onClick={(e) => { e.stopPropagation(); openReviewPanel(escalation) }}
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-foreground"
                            aria-label="Review escalation"
                          >
                            <Eye className="h-3.5 w-3.5" />
                          </Button>
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
                    {((filters.page - 1) * PAGE_SIZE) + 1}--{Math.min(filters.page * PAGE_SIZE, totalCount)} of {totalCount}
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
          escalation={selectedEscalation}
          open={showReviewPanel}
          onOpenChange={setShowReviewPanel}
          onUpdated={handleEscalationUpdated}
        />
      )}
    </div>
  )
}
