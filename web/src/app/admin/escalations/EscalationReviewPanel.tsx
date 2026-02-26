"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Input } from "@/components/ui/input"
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogClose } from "@/components/ui/dialog"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { cn } from "@/lib/utils"
import {
  Loader2,
  X,
  Send,
  XCircle,
  Bot,
  MessageSquare,
  AlertCircle,
  AlertTriangle,
  ShieldCheck,
  ChevronDown,
  Pencil,
  Check,
  Clock,
} from 'lucide-react'
import { toast } from 'sonner'
import { makeAuthenticatedRequest } from '@/lib/auth'
import type { EscalationItem } from './page'
import { MarkdownContent } from "@/components/chat/components/markdown-content"
import { SourceBadges } from "@/components/chat/components/source-badges"
import { ConfidenceBadge } from "@/components/chat/components/confidence-badge"
import type { Source } from "@/components/chat/types/chat.types"
import { normalizeRoutingReasonSourceCount } from "@/lib/escalation-routing"
import {
  FAQ_CATEGORIES,
  FAQ_PROTOCOL_OPTIONS,
  inferFaqMetadata,
  type FAQProtocol,
} from "@/lib/faq-metadata"
import { SimilarFaqsPanel, type SimilarFAQItem } from "@/components/admin/SimilarFaqsPanel"

interface EscalationReviewPanelProps {
  escalation: EscalationItem
  open: boolean
  onOpenChange: (open: boolean) => void
  onUpdated: () => void
}

function formatTimestamp(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
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

function getChannelBadge(channel: string): { label: string; className: string } {
  const badges: Record<string, { label: string; className: string }> = {
    'web': { label: 'Web', className: 'bg-blue-500/15 text-blue-400 border border-blue-500/25' },
    'matrix': { label: 'Matrix', className: 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/25' },
    'bisq2': { label: 'Bisq2', className: 'bg-orange-500/15 text-orange-400 border border-orange-500/25' },
  }
  return badges[channel] || { label: channel, className: 'bg-muted text-muted-foreground border border-border' }
}

function humanizeEnumValue(value: string): string {
  const cleaned = (value || "")
    .trim()
    .replace(/[-_]+/g, " ")
    .toLowerCase()
  if (!cleaned) return ""
  return cleaned.replace(/\b\w/g, (c) => c.toUpperCase())
}

function normalizeAnswerForComparison(value: string): string {
  return (value || "")
    .replace(/\s+/g, " ")
    .trim()
}

function isMeaningfullyEditedAnswer(staffAnswer: string, aiDraftAnswer: string): boolean {
  const normalizedStaff = normalizeAnswerForComparison(staffAnswer)
  const normalizedDraft = normalizeAnswerForComparison(aiDraftAnswer)
  if (!normalizedStaff) return false
  if (!normalizedDraft) return true
  return normalizedStaff !== normalizedDraft
}

export function EscalationReviewPanel({
  escalation,
  open,
  onOpenChange,
  onUpdated,
}: EscalationReviewPanelProps) {
  const scrollAreaRef = useRef<HTMLDivElement | null>(null)
  const aiDraftRef = useRef<string>("")
  const suggestedTextareaRef = useRef<HTMLTextAreaElement | null>(null)

  const [phase, setPhase] = useState<'review' | 'faq'>('review')

  const [staffAnswer, setStaffAnswer] = useState(escalation.ai_draft_answer || '')
  const [isResponding, setIsResponding] = useState(false)
  const [isClosing, setIsClosing] = useState(false)
  const [isEditingSuggestedAnswer, setIsEditingSuggestedAnswer] = useState(false)

  const [faqQuestion, setFaqQuestion] = useState(escalation.question)
  const [faqAnswer, setFaqAnswer] = useState(escalation.staff_answer || escalation.ai_draft_answer || '')
  const [faqCategory, setFaqCategory] = useState('General')
  const [faqProtocol, setFaqProtocol] = useState<FAQProtocol>('all')
  const [isSubmittingFaq, setIsSubmittingFaq] = useState(false)
  const [similarFaqs, setSimilarFaqs] = useState<SimilarFAQItem[]>([])
  const [isCheckingSimilarFaqs, setIsCheckingSimilarFaqs] = useState(false)
  const [requiresForceOverride, setRequiresForceOverride] = useState(false)

  // Reset form when escalation changes
  useEffect(() => {
    aiDraftRef.current = escalation.ai_draft_answer || ""
    setStaffAnswer(escalation.staff_answer || escalation.ai_draft_answer || '')
    const hasExistingStaffResponse = Boolean((escalation.staff_answer || "").trim())
    const hasMeaningfulEdit = isMeaningfullyEditedAnswer(
      escalation.staff_answer || "",
      escalation.ai_draft_answer || "",
    )
    const shouldStartInFaq = hasExistingStaffResponse && (
      hasMeaningfulEdit &&
      (escalation.status === "responded" || escalation.status === "closed")
    )
    setPhase(shouldStartInFaq ? "faq" : "review")
    setIsEditingSuggestedAnswer(false)
    setFaqQuestion(escalation.question)
    setFaqAnswer(escalation.staff_answer || escalation.ai_draft_answer || '')
    setSimilarFaqs([])
    setRequiresForceOverride(false)
    const inferred = inferFaqMetadata({
      question: escalation.question,
      answer: escalation.staff_answer || escalation.ai_draft_answer,
    })
    setFaqCategory(inferred.category)
    setFaqProtocol(inferred.protocol)
  }, [escalation])

  useEffect(() => {
    if (!isEditingSuggestedAnswer) return
    requestAnimationFrame(() => {
      if (!suggestedTextareaRef.current) return
      suggestedTextareaRef.current.focus()
      suggestedTextareaRef.current.style.height = "auto"
      suggestedTextareaRef.current.style.height = `${suggestedTextareaRef.current.scrollHeight}px`
    })
  }, [isEditingSuggestedAnswer])

  const scrollToTop = () => {
    requestAnimationFrame(() => {
      scrollAreaRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    })
  }

  const handleRespond = async () => {
    if (!staffAnswer.trim()) {
      toast.error('Please enter a response before sending')
      return
    }

    setIsResponding(true)
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/escalations/${escalation.id}/respond`,
        {
          method: 'POST',
          body: JSON.stringify({
            staff_answer: staffAnswer.trim(),
          }),
        }
      )

      if (response.ok) {
        const trimmedAnswer = staffAnswer.trim()
        const unchangedFromAiDraft = !isMeaningfullyEditedAnswer(
          trimmedAnswer,
          aiDraftRef.current,
        )

        if (unchangedFromAiDraft) {
          try {
            const closeResponse = await makeAuthenticatedRequest(
              `/admin/escalations/${escalation.id}/close`,
              { method: 'POST' },
            )
            if (closeResponse.ok) {
              toast.success('Response sent and escalation resolved')
              onUpdated()
              onOpenChange(false)
              return
            }

            const closeError = await closeResponse
              .json()
              .catch(() => ({ detail: 'Response sent, but auto-resolve failed. Please close manually.' }))
            toast.error(closeError.detail || 'Response sent, but auto-resolve failed. Please close manually.')
            onUpdated()
            return
          } catch {
            toast.error('Response sent, but auto-resolve failed. Please close manually.')
            onUpdated()
            return
          }
        }

        toast.success('Response sent successfully')
        onUpdated()
        setPhase('faq')
        setFaqAnswer(trimmedAnswer)
        const inferred = inferFaqMetadata({
          question: faqQuestion || escalation.question,
          answer: trimmedAnswer || escalation.staff_answer || escalation.ai_draft_answer,
        })
        setFaqCategory(inferred.category)
        setFaqProtocol(inferred.protocol)
        scrollToTop()
      } else {
        const data = await response.json().catch(() => ({ detail: 'Failed to send response' }))
        toast.error(data.detail || 'Failed to send response')
      }
    } catch {
      toast.error('An error occurred while sending the response')
    } finally {
      setIsResponding(false)
    }
  }

  const handleClose = async () => {
    setIsClosing(true)
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/escalations/${escalation.id}/close`,
        {
          method: 'POST',
        }
      )

      if (response.ok) {
        toast.success('Escalation closed')
        onUpdated()
        onOpenChange(false)
      } else {
        const data = await response.json().catch(() => ({ detail: 'Failed to close escalation' }))
        toast.error(data.detail || 'Failed to close escalation')
      }
    } catch {
      toast.error('An error occurred while closing the escalation')
    } finally {
      setIsClosing(false)
    }
  }

  const handleComplete = async () => {
    await createFaq(false)
  }

  const createFaq = async (force: boolean) => {
    if (!faqQuestion.trim() || !faqAnswer.trim()) {
      toast.error('Question and answer are required')
      return
    }

    setIsSubmittingFaq(true)
    try {
      const body: Record<string, unknown> = {
        question: faqQuestion.trim(),
        answer: faqAnswer.trim(),
        category: faqCategory,
        protocol: faqProtocol,
      }
      if (force) {
        body.force = true
      }

      const response = await makeAuthenticatedRequest(
        `/admin/escalations/${escalation.id}/generate-faq`,
        {
          method: 'POST',
          body: JSON.stringify(body),
        }
      )

      if (response.ok) {
        toast.success('FAQ created')
        setSimilarFaqs([])
        setRequiresForceOverride(false)
        onUpdated()
        onOpenChange(false)
      } else if (response.status === 409) {
        const data = await response.json().catch(() => ({ detail: null }))
        const detail = data?.detail
        const matches = Array.isArray(detail?.similar_faqs) ? detail.similar_faqs : []
        setSimilarFaqs(matches)
        setRequiresForceOverride(true)
        toast.error(
          (typeof detail?.message === "string" && detail.message.trim())
            ? detail.message
            : "Similar FAQ already exists. Review matches or create anyway."
        )
      } else {
        const data = await response.json().catch(() => ({ detail: 'Failed to create FAQ' }))
        toast.error(data.detail || 'Failed to create FAQ')
      }
    } catch {
      toast.error('An error occurred while creating the FAQ')
    } finally {
      setIsSubmittingFaq(false)
    }
  }

  const checkSimilarFaqs = useCallback(async (question: string) => {
    const trimmed = question.trim()
    if (trimmed.length < 5) {
      setSimilarFaqs([])
      setRequiresForceOverride(false)
      return
    }

    setIsCheckingSimilarFaqs(true)
    try {
      const response = await makeAuthenticatedRequest('/admin/faqs/check-similar', {
        method: 'POST',
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: trimmed,
          threshold: 0.85,
          limit: 5,
          exclude_id: null,
        }),
      })
      if (!response.ok) {
        return
      }
      const data = await response.json()
      const matches = Array.isArray(data?.similar_faqs) ? data.similar_faqs : []
      setSimilarFaqs(matches)
      setRequiresForceOverride(matches.length > 0)
    } catch {
      // graceful degradation: FAQ creation still has server-side duplicate guard
    } finally {
      setIsCheckingSimilarFaqs(false)
    }
  }, [])

  useEffect(() => {
    if (phase !== "faq") return
    const timeoutId = setTimeout(() => {
      void checkSimilarFaqs(faqQuestion)
    }, 350)
    return () => clearTimeout(timeoutId)
  }, [phase, faqQuestion, checkSimilarFaqs])

  const handleViewSimilarFaq = useCallback((faq: SimilarFAQItem) => {
    import("@/lib/utils").then(({ generateFaqSlug }) => {
      const slug = generateFaqSlug(faq.question, faq.id)
      window.open(`/faq/${slug}`, "_blank", "noopener,noreferrer")
    })
  }, [])

  const statusBadge = getStatusBadge(escalation.status)
  const channelBadge = getChannelBadge(escalation.channel)
  const canRespond = escalation.status === 'pending' || escalation.status === 'in_review'
  const canClose = escalation.status !== 'closed'
  const isActionInProgress = isResponding || isClosing || isSubmittingFaq

  const routingAction = (escalation.routing_action || "").trim()
  const routingReason = normalizeRoutingReasonSourceCount(
    (escalation.routing_reason || "").trim(),
    escalation.sources?.length,
  )
  const routingActionLower = routingAction.toLowerCase()
  const routingReasonLower = routingReason.toLowerCase()

  // Hide generic "needs_human" routing noise unless there's an actual explanation.
  const hasMeaningfulRouting =
    Boolean(routingReason && routingReasonLower !== "needs_human") ||
    Boolean(routingAction && routingActionLower !== "needs_human")

  const routingSummary = useMemo(() => {
    if (!hasMeaningfulRouting) return null

    const actionLabel = routingAction ? humanizeEnumValue(routingAction) : "Escalated"
    if (!routingReason) return { title: actionLabel, detail: "" }

    // If the "reason" is actually just a code, humanize it. Otherwise keep as-is.
    const looksLikeCode = !/\s/.test(routingReason) || /[_-]/.test(routingReason)
    const reasonLabel = looksLikeCode ? humanizeEnumValue(routingReason) : routingReason

    // Avoid duplicate text when reason == action (common in older payloads).
    if (routingActionLower && routingReasonLower === routingActionLower) {
      return { title: actionLabel, detail: "" }
    }

    return { title: actionLabel, detail: reasonLabel }
  }, [hasMeaningfulRouting, routingAction, routingReason, routingActionLower, routingReasonLower])

  const chatSources: Source[] = useMemo(() => {
    const raw = escalation.sources || []
    return raw
      .map((s) => {
        const category = (s.category || "").toLowerCase()
        const inferredType: "wiki" | "faq" =
          category === "faq" ? "faq" :
          category === "wiki" ? "wiki" :
          (s.url && String(s.url).startsWith("/faq/")) ? "faq" :
          "wiki"

        const content = (s.content || "").trim() || "No preview available."

        return {
          title: (s.title || "Source").trim(),
          type: inferredType,
          content,
          protocol: (s.protocol as Source["protocol"]) || undefined,
          url: s.url || undefined,
          section: s.section || undefined,
          similarity_score: typeof s.relevance_score === "number" ? s.relevance_score : undefined,
        } satisfies Source
      })
      .filter(Boolean) as Source[]
  }, [escalation.sources])

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
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
                {phase === 'review' ? 'Escalation Review' : 'Create FAQ'}
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusBadge.className}`}>
                  {statusBadge.label}
                </span>
              </DialogTitle>
              <DialogDescription>
                {phase === 'review'
                  ? 'Review and respond to the escalated support question.'
                  : 'Create an FAQ draft from the resolved escalation. You can edit everything before publishing.'}
              </DialogDescription>

              <div className="mt-3 flex flex-wrap items-center gap-2">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${channelBadge.className}`}>
                  {channelBadge.label}
                </span>
                <Badge variant="outline" className="text-[10px] font-medium text-muted-foreground">
                  Priority: <span className="text-foreground/90">{escalation.priority}</span>
                </Badge>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      aria-label={`Created ${formatTimestamp(escalation.created_at)}`}
                    >
                      <Clock className="h-3.5 w-3.5" aria-hidden="true" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="bottom">
                    <p className="text-xs tabular-nums">Created {formatTimestamp(escalation.created_at)}</p>
                  </TooltipContent>
                </Tooltip>
                {escalation.staff_id && (
                  <Badge variant="secondary" className="text-[10px] font-medium">
                    Claimed by {escalation.staff_id}
                  </Badge>
                )}

                {routingSummary && (
                  routingSummary.detail ? (
                    <Popover>
                      <PopoverTrigger asChild>
                        <Button
                          type="button"
                          variant="secondary"
                          size="sm"
                          className="h-7 px-2 text-[10px] font-medium"
                        >
                          <AlertCircle className="h-3.5 w-3.5 mr-1 text-muted-foreground" aria-hidden="true" />
                          Escalated: {routingSummary.title}
                          <ChevronDown className="h-3 w-3 ml-1 text-muted-foreground" aria-hidden="true" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent className="w-[min(420px,calc(100vw-2rem))] p-0" align="start" sideOffset={8}>
                        <div className="px-3 py-2 border-b border-border">
                          <p className="text-sm font-medium">Why it escalated</p>
                        </div>
                        <div className="p-3 text-sm text-muted-foreground leading-relaxed">
                          {routingSummary.detail}
                        </div>
                      </PopoverContent>
                    </Popover>
                  ) : (
                    <Badge variant="secondary" className="text-[10px] font-medium">
                      <AlertCircle className="h-3.5 w-3.5 mr-1 text-muted-foreground" aria-hidden="true" />
                      Escalated: {routingSummary.title}
                    </Badge>
                  )
                )}

                <Popover>
                  <PopoverTrigger asChild>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-[10px] text-muted-foreground hover:text-foreground"
                    >
                      Details
                      <ChevronDown className="h-3 w-3" aria-hidden="true" />
                    </Button>
                  </PopoverTrigger>
                  <PopoverContent className="w-[min(420px,calc(100vw-2rem))] p-0" align="end" sideOffset={8}>
                    <div className="px-3 py-2 border-b border-border">
                      <p className="text-sm font-medium">Escalation details</p>
                    </div>
                    <div className="p-3 space-y-2 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-muted-foreground">Created</span>
                        <span className="tabular-nums text-foreground/90">{formatTimestamp(escalation.created_at)}</span>
                      </div>
                      {escalation.responded_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Responded</span>
                          <span className="tabular-nums text-foreground/90">{formatTimestamp(escalation.responded_at)}</span>
                        </div>
                      )}
                      {escalation.closed_at && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Closed</span>
                          <span className="tabular-nums text-foreground/90">{formatTimestamp(escalation.closed_at)}</span>
                        </div>
                      )}
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-muted-foreground">Escalation ID</span>
                        <span className="font-mono text-[11px] text-foreground/90">{escalation.id}</span>
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-muted-foreground">Message ID</span>
                        <span className="font-mono text-[11px] text-foreground/90 truncate max-w-[240px]" title={escalation.message_id}>
                          {escalation.message_id}
                        </span>
                      </div>
                      {(routingAction || routingReason) && (
                        <>
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-muted-foreground">Routing action</span>
                            <span className="text-foreground/90">{routingAction ? humanizeEnumValue(routingAction) : "N/A"}</span>
                          </div>
                          <div className="flex items-center justify-between gap-3">
                            <span className="text-muted-foreground">Routing reason</span>
                            <span className="text-foreground/90 truncate max-w-[240px]" title={routingReason || undefined}>
                              {routingReason ? routingReason : "N/A"}
                            </span>
                          </div>
                        </>
                      )}
                      {typeof escalation.confidence_score === "number" && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Confidence</span>
                          <span className="tabular-nums text-foreground/90">{Math.round(escalation.confidence_score * 100)}%</span>
                        </div>
                      )}
                      {chatSources.length > 0 && (
                        <div className="flex items-center justify-between gap-3">
                          <span className="text-muted-foreground">Sources</span>
                          <span className="tabular-nums text-foreground/90">{chatSources.length}</span>
                        </div>
                      )}
                    </div>
                  </PopoverContent>
                </Popover>
              </div>
            </DialogHeader>
          </div>

          <div ref={scrollAreaRef} className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-6 pb-6">
            <div className="space-y-5 pt-1">
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center gap-2">
                    <MessageSquare className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    <CardTitle className="text-sm">Question</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="pt-0">
                  <MarkdownContent content={escalation.question} className="text-sm" />
                </CardContent>
              </Card>

              {phase === 'review' && canRespond && (
                <div>
                  <div className="flex items-center gap-2 mb-2">
                    <Bot className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    <span className="font-medium text-sm">
                      Suggested Answer
                      {isEditingSuggestedAnswer && (
                        <span className="text-muted-foreground ml-1">(Editing)</span>
                      )}
                    </span>
                    {typeof escalation.confidence_score === "number" && (
                      <span className="text-xs text-muted-foreground tabular-nums">
                        {Math.round(escalation.confidence_score * 100)}% confidence
                      </span>
                    )}
                    <div className="ml-auto flex items-center gap-2">
                      {aiDraftRef.current && staffAnswer.trim() !== aiDraftRef.current.trim() && (
                        <Button
                          type="button"
                          variant="link"
                          size="sm"
                          className="h-7 px-0 text-xs text-muted-foreground hover:text-foreground"
                          onClick={() => setStaffAnswer(aiDraftRef.current)}
                          disabled={isActionInProgress}
                        >
                          Reset to AI draft
                        </Button>
                      )}
                      {isEditingSuggestedAnswer ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-7 px-2 text-xs"
                          onClick={() => setIsEditingSuggestedAnswer(false)}
                          disabled={isActionInProgress}
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
                          onClick={() => setIsEditingSuggestedAnswer(true)}
                          disabled={isActionInProgress}
                        >
                          <Pencil className="h-3.5 w-3.5 mr-1" aria-hidden="true" />
                          Edit
                        </Button>
                      )}
                    </div>
                  </div>
                  <div
                    className={cn(
                      "p-4 rounded-lg border min-h-[140px] transition-all",
                      isEditingSuggestedAnswer
                        ? "bg-background border-primary ring-1 ring-primary"
                        : "bg-muted/30 border-border"
                    )}
                  >
                    {isEditingSuggestedAnswer ? (
                      <>
                        <Label htmlFor="escalation-staff-answer" className="sr-only">Suggested answer (editable)</Label>
                        <Textarea
                          ref={suggestedTextareaRef}
                          id="escalation-staff-answer"
                          name="staff_answer"
                          rows={10}
                          placeholder="Edit the AI draft or write your own response…"
                          value={staffAnswer}
                          onChange={(e) => {
                            setStaffAnswer(e.target.value)
                            e.target.style.height = "auto"
                            e.target.style.height = `${e.target.scrollHeight}px`
                          }}
                          autoComplete="off"
                          onKeyDown={(e) => {
                            if (e.key === "Escape") {
                              e.preventDefault()
                              setIsEditingSuggestedAnswer(false)
                              return
                            }
                            if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                              e.preventDefault()
                              handleRespond()
                            }
                          }}
                          className="min-h-[140px] resize-none border-0 p-0 focus-visible:ring-0 bg-transparent"
                        />
                      </>
                    ) : (
                      <div className="text-sm">
                        {staffAnswer.trim() ? (
                          <MarkdownContent content={staffAnswer} className="text-sm" />
                        ) : (
                          <p className="text-muted-foreground">No suggested answer available.</p>
                        )}
                      </div>
                    )}

                    {(chatSources.length > 0 || typeof escalation.confidence_score === "number" || isEditingSuggestedAnswer) && (
                      <div className="mt-3 pt-3 border-t border-border/50 flex flex-wrap items-center gap-3">
                        {chatSources.length > 0 && <SourceBadges sources={chatSources} />}
                        {typeof escalation.confidence_score === "number" && (
                          <ConfidenceBadge confidence={escalation.confidence_score} />
                        )}
                        {isEditingSuggestedAnswer && (
                          <span className="text-[11px] text-muted-foreground">
                            Tip: Press Cmd/Ctrl+Enter to send. Escape to preview.
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {escalation.staff_answer && (escalation.status === 'responded' || escalation.status === 'closed') && (
                <Card>
                  <CardHeader className="pb-3">
                    <CardTitle className="text-sm">Staff response</CardTitle>
                  </CardHeader>
                  <CardContent className="pt-0">
                    <MarkdownContent content={escalation.staff_answer} className="text-sm" />
                    {escalation.responded_at && (
                      <p className="text-xs text-muted-foreground mt-2">
                        Responded: <span className="tabular-nums">{formatTimestamp(escalation.responded_at)}</span>
                      </p>
                    )}
                  </CardContent>
                </Card>
              )}

              {phase === 'faq' && (
                <div className="rounded-lg border border-border bg-card p-4 space-y-4">
                  <div
                    className="text-sm p-3 bg-emerald-500/10 rounded-lg border-l-2 border-emerald-500/40 text-emerald-400 leading-relaxed"
                    aria-live="polite"
                  >
                    FAQ draft is ready to edit. Adjust question, answer, and metadata, then publish.
                  </div>

                  <div className="rounded-lg border border-border/80 bg-muted/20 p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant={faqQuestion.trim() ? "secondary" : "outline"} className="gap-1">
                        {faqQuestion.trim() ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                        Question
                      </Badge>
                      <Badge variant={faqAnswer.trim() ? "secondary" : "outline"} className="gap-1">
                        {faqAnswer.trim() ? <Check className="h-3 w-3" /> : <X className="h-3 w-3" />}
                        Answer
                      </Badge>
                      <Badge
                        variant="secondary"
                        className={cn(
                          "gap-1",
                          requiresForceOverride
                            ? "bg-amber-500/15 text-amber-300 border border-amber-500/30"
                            : undefined
                        )}
                      >
                        {requiresForceOverride ? <AlertTriangle className="h-3 w-3" /> : <ShieldCheck className="h-3 w-3" />}
                        {requiresForceOverride ? "Potential duplicate" : "No close duplicate"}
                      </Badge>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      Publishing is blocked only when exact duplicate guard triggers server-side. Similarity check helps you avoid near-duplicates early.
                    </p>
                  </div>

                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="escalation-faq-question" className="text-xs text-muted-foreground uppercase tracking-wider">Question</Label>
                      <Input
                        id="escalation-faq-question"
                        name="faq_question"
                        value={faqQuestion}
                        onChange={(e) => {
                          setFaqQuestion(e.target.value)
                          setRequiresForceOverride(false)
                        }}
                        onBlur={() => {
                          void checkSimilarFaqs(faqQuestion)
                        }}
                        placeholder="FAQ question"
                        autoComplete="off"
                      />
                      {isCheckingSimilarFaqs && (
                        <p className="text-xs text-muted-foreground flex items-center gap-1" aria-live="polite">
                          <Loader2 className="h-3 w-3 animate-spin" />
                          Checking similar FAQs...
                        </p>
                      )}
                    </div>

                    <SimilarFaqsPanel
                      similarFaqs={similarFaqs}
                      isLoading={isCheckingSimilarFaqs}
                      onViewFaq={handleViewSimilarFaq}
                    />

                    {requiresForceOverride && similarFaqs.length > 0 && (
                      <div className="rounded-lg border border-amber-500/30 bg-amber-500/10 p-3">
                        <p className="text-sm text-amber-200">
                          Similar FAQ content detected. Refine the question/answer to keep the knowledge base clean, or use <span className="font-semibold">Create FAQ Anyway</span> to override.
                        </p>
                      </div>
                    )}

                    <div className="space-y-1.5">
                      <Label htmlFor="escalation-faq-answer" className="text-xs text-muted-foreground uppercase tracking-wider">Answer</Label>
                      <Textarea
                        id="escalation-faq-answer"
                        name="faq_answer"
                        rows={8}
                        value={faqAnswer}
                        onChange={(e) => setFaqAnswer(e.target.value)}
                        placeholder="FAQ answer"
                        className="resize-y"
                        autoComplete="off"
                      />
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                      <div className="space-y-1.5">
                        <Label htmlFor="escalation-faq-category" className="text-xs text-muted-foreground uppercase tracking-wider">Category</Label>
                        <Select value={faqCategory} onValueChange={setFaqCategory}>
                          <SelectTrigger id="escalation-faq-category">
                            <SelectValue placeholder="Select category" />
                          </SelectTrigger>
                          <SelectContent>
                            {FAQ_CATEGORIES.map((cat) => (
                              <SelectItem key={cat} value={cat}>{cat}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>

                      <div className="space-y-1.5">
                        <Label htmlFor="escalation-faq-protocol" className="text-xs text-muted-foreground uppercase tracking-wider">Protocol</Label>
                        <Select value={faqProtocol} onValueChange={(value) => setFaqProtocol(value as FAQProtocol)}>
                          <SelectTrigger id="escalation-faq-protocol">
                            <SelectValue placeholder="Select protocol" />
                          </SelectTrigger>
                          <SelectContent>
                            {FAQ_PROTOCOL_OPTIONS.map((opt) => (
                              <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-border bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60 px-6 py-4">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                {phase === 'review' && canRespond && (
                  <Button
                    onClick={handleRespond}
                    size="sm"
                    disabled={isActionInProgress || !staffAnswer.trim()}
                  >
                    {isResponding ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <Send className="mr-2 h-4 w-4" />
                    )}
                    Send Response
                  </Button>
                )}

                {phase === 'faq' && (
                  <div className="flex items-center gap-2">
                    <Button
                      onClick={handleComplete}
                      size="sm"
                      disabled={isActionInProgress || !faqQuestion.trim() || !faqAnswer.trim() || requiresForceOverride}
                      title={requiresForceOverride ? "Resolve duplicate risk or use Create FAQ Anyway" : undefined}
                    >
                      {isSubmittingFaq ? (
                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      ) : null}
                      Create FAQ & Close
                    </Button>
                    {requiresForceOverride && (
                      <Button
                        onClick={() => void createFaq(true)}
                        size="sm"
                        variant="secondary"
                        disabled={isActionInProgress || !faqQuestion.trim() || !faqAnswer.trim()}
                      >
                        Create FAQ Anyway
                      </Button>
                    )}
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2">
                {phase === 'review' && canClose && (
                  <Button
                    onClick={handleClose}
                    variant="outline"
                    size="sm"
                    disabled={isActionInProgress}
                    className="text-muted-foreground hover:text-foreground"
                    title="Dismiss this escalation without sending a reply to the user"
                  >
                    {isClosing ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <XCircle className="mr-2 h-4 w-4" />
                    )}
                    Dismiss (No Reply)
                  </Button>
                )}

                {phase === 'faq' && (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="text-muted-foreground hover:text-foreground"
                    onClick={() => onOpenChange(false)}
                    disabled={isActionInProgress}
                  >
                    Close Without FAQ
                  </Button>
                )}
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
