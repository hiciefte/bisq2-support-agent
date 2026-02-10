"use client"

import { useState, useEffect } from 'react'
import { Button } from "@/components/ui/button"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogClose } from "@/components/ui/dialog"
import {
  Loader2,
  X,
  UserCheck,
  Send,
  XCircle,
  Clock,
  BookOpen,
} from 'lucide-react'
import { toast } from 'sonner'
import { makeAuthenticatedRequest } from '@/lib/auth'
import { GenerateFAQDialog } from './GenerateFAQDialog'
import type { EscalationItem } from './page'

interface EscalationReviewPanelProps {
  escalation: EscalationItem
  open: boolean
  onOpenChange: (open: boolean) => void
  onUpdated: () => void
}

const STAFF_ID_KEY = 'escalation_staff_id'

function getStaffId(): string {
  if (typeof window === 'undefined') return 'staff'
  return localStorage.getItem(STAFF_ID_KEY) || 'staff'
}

function setStaffId(id: string) {
  if (typeof window !== 'undefined') {
    localStorage.setItem(STAFF_ID_KEY, id)
  }
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

export function EscalationReviewPanel({
  escalation,
  open,
  onOpenChange,
  onUpdated,
}: EscalationReviewPanelProps) {
  const [staffAnswer, setStaffAnswer] = useState(escalation.ai_answer || '')
  const [currentStaffId, setCurrentStaffId] = useState(getStaffId())
  const [isClaiming, setIsClaiming] = useState(false)
  const [isResponding, setIsResponding] = useState(false)
  const [isClosing, setIsClosing] = useState(false)
  const [showGenerateFAQ, setShowGenerateFAQ] = useState(false)

  // Reset form when escalation changes
  useEffect(() => {
    setStaffAnswer(escalation.staff_answer || escalation.ai_answer || '')
  }, [escalation])

  const handleClaim = async () => {
    setIsClaiming(true)
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/escalations/${escalation.id}/claim`,
        {
          method: 'POST',
          body: JSON.stringify({ staff_id: currentStaffId }),
        }
      )

      if (response.ok) {
        toast.success('Escalation claimed successfully')
        setStaffId(currentStaffId)
        onUpdated()
      } else {
        const data = await response.json().catch(() => ({ detail: 'Failed to claim escalation' }))
        toast.error(data.detail || 'Failed to claim escalation')
      }
    } catch {
      toast.error('An error occurred while claiming the escalation')
    } finally {
      setIsClaiming(false)
    }
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
            staff_id: currentStaffId,
          }),
        }
      )

      if (response.ok) {
        toast.success('Response sent successfully')
        setStaffId(currentStaffId)
        onUpdated()
        onOpenChange(false)
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

  const statusBadge = getStatusBadge(escalation.status)
  const channelBadge = getChannelBadge(escalation.channel)
  const canClaim = escalation.status === 'pending'
  const canRespond = escalation.status === 'pending' || escalation.status === 'in_review'
  const canClose = escalation.status !== 'closed'
  const canGenerateFAQ = escalation.status === 'responded' || escalation.status === 'closed'
  const isActionInProgress = isClaiming || isResponding || isClosing

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
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
              Escalation Review
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${statusBadge.className}`}>
                {statusBadge.label}
              </span>
            </DialogTitle>
            <DialogDescription>
              Review and respond to escalated support question
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-5">
            {/* Metadata bar */}
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground pb-3 border-b border-border">
              <Clock className="h-3.5 w-3.5" />
              <span className="tabular-nums">{formatTimestamp(escalation.created_at)}</span>
              <span className="text-border">|</span>
              <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ${channelBadge.className}`}>
                {channelBadge.label}
              </span>
              <span className="text-border">|</span>
              <span>Priority: {escalation.priority}</span>
              {escalation.staff_id && (
                <>
                  <span className="text-border">|</span>
                  <span>Claimed by: {escalation.staff_id}</span>
                </>
              )}
              <span className="text-border">|</span>
              <span className="font-mono text-[10px] text-muted-foreground/60 truncate max-w-[200px]" title={escalation.id}>
                {escalation.id}
              </span>
            </div>

            {/* Escalation Reason */}
            {escalation.reason && (
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Escalation Reason</span>
                <p className="text-sm p-3 bg-yellow-500/10 rounded-lg border-l-2 border-yellow-500/40 text-yellow-400 leading-relaxed">
                  {escalation.reason}
                </p>
              </div>
            )}

            {/* Question */}
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Question</span>
              <p className="text-sm p-3 bg-accent rounded-lg text-card-foreground leading-relaxed">
                {escalation.question}
              </p>
            </div>

            {/* AI Draft Answer */}
            <div className="space-y-1">
              <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">AI Draft Answer</span>
              <div className="text-sm p-3 bg-accent rounded-lg text-card-foreground leading-relaxed whitespace-pre-wrap">
                {escalation.ai_answer}
              </div>
              {typeof escalation.ai_confidence === 'number' && (
                <p className="text-xs text-muted-foreground mt-1">
                  AI Confidence: {(escalation.ai_confidence * 100).toFixed(0)}%
                </p>
              )}
            </div>

            {/* Sources */}
            {escalation.sources && escalation.sources.length > 0 && (
              <div className="space-y-2">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Sources Used</span>
                <div className="space-y-2">
                  {escalation.sources.map((source, idx) => (
                    <div key={idx} className="p-3 border border-border rounded-lg bg-accent/50">
                      <div className="flex items-center gap-2 mb-1.5">
                        <span className="font-medium text-sm text-card-foreground">{source.title}</span>
                        <span className="px-2 py-0.5 bg-blue-500/15 text-blue-400 border border-blue-500/20 rounded text-[10px] font-medium">
                          {source.type}
                        </span>
                      </div>
                      <p className="text-xs text-muted-foreground leading-relaxed">
                        {source.content.substring(0, 300)}{source.content.length > 300 ? '...' : ''}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Staff Response (if already responded) */}
            {escalation.staff_answer && (escalation.status === 'responded' || escalation.status === 'closed') && (
              <div className="space-y-1">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Staff Response</span>
                <div className="text-sm p-3 bg-emerald-500/10 rounded-lg border-l-2 border-emerald-500/40 text-emerald-400 leading-relaxed whitespace-pre-wrap">
                  {escalation.staff_answer}
                </div>
                {escalation.responded_at && (
                  <p className="text-xs text-muted-foreground mt-1">
                    Responded: {formatTimestamp(escalation.responded_at)}
                  </p>
                )}
              </div>
            )}

            {/* Staff ID Input */}
            {canRespond && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Your Staff ID</Label>
                <input
                  type="text"
                  value={currentStaffId}
                  onChange={(e) => setCurrentStaffId(e.target.value)}
                  placeholder="Enter your staff ID"
                  className="flex h-9 w-full max-w-xs rounded-md border border-border bg-background px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                />
              </div>
            )}

            {/* Editable Staff Answer */}
            {canRespond && (
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground uppercase tracking-wider">Your Response</Label>
                <Textarea
                  rows={8}
                  placeholder="Edit the AI draft or write your own response..."
                  value={staffAnswer}
                  onChange={(e) => setStaffAnswer(e.target.value)}
                  className="resize-y"
                />
              </div>
            )}

            {/* Action Buttons */}
            <div className="flex items-center gap-3 pt-2 border-t border-border">
              {canClaim && (
                <Button
                  onClick={handleClaim}
                  variant="outline"
                  size="sm"
                  disabled={isActionInProgress || !currentStaffId.trim()}
                >
                  {isClaiming ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <UserCheck className="mr-2 h-4 w-4" />
                  )}
                  Claim
                </Button>
              )}

              {canRespond && (
                <Button
                  onClick={handleRespond}
                  size="sm"
                  disabled={isActionInProgress || !staffAnswer.trim() || !currentStaffId.trim()}
                >
                  {isResponding ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <Send className="mr-2 h-4 w-4" />
                  )}
                  Send Response
                </Button>
              )}

              {canClose && (
                <Button
                  onClick={handleClose}
                  variant="outline"
                  size="sm"
                  disabled={isActionInProgress}
                  className="text-muted-foreground hover:text-foreground"
                >
                  {isClosing ? (
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  ) : (
                    <XCircle className="mr-2 h-4 w-4" />
                  )}
                  Close
                </Button>
              )}

              {canGenerateFAQ && (
                <Button
                  onClick={() => setShowGenerateFAQ(true)}
                  variant="outline"
                  size="sm"
                  className="ml-auto"
                >
                  <BookOpen className="mr-2 h-4 w-4" />
                  Generate FAQ
                </Button>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Generate FAQ Dialog */}
      {showGenerateFAQ && (
        <GenerateFAQDialog
          escalation={escalation}
          open={showGenerateFAQ}
          onOpenChange={setShowGenerateFAQ}
        />
      )}
    </>
  )
}
