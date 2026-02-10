"use client"

import { useState, FormEvent } from 'react'
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Label } from "@/components/ui/label"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { makeAuthenticatedRequest } from '@/lib/auth'
import type { EscalationItem } from './page'

interface GenerateFAQDialogProps {
  escalation: EscalationItem
  open: boolean
  onOpenChange: (open: boolean) => void
}

const FAQ_CATEGORIES = [
  'General',
  'Trading',
  'Wallet',
  'Security',
  'Reputation',
  'Payments',
  'Technical',
  'Bisq Easy',
  'Bisq 2',
  'Fees',
  'Account',
]

const PROTOCOL_OPTIONS = [
  { value: 'none', label: 'None' },
  { value: 'bisq_easy', label: 'Bisq Easy' },
  { value: 'multisig_v1', label: 'Multisig v1' },
  { value: 'musig', label: 'MuSig' },
  { value: 'all', label: 'All Protocols' },
]

export function GenerateFAQDialog({
  escalation,
  open,
  onOpenChange,
}: GenerateFAQDialogProps) {
  const [question, setQuestion] = useState(escalation.question)
  const [answer, setAnswer] = useState(escalation.staff_answer || escalation.ai_answer || '')
  const [category, setCategory] = useState('General')
  const [protocol, setProtocol] = useState('none')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault()

    if (!question.trim() || !answer.trim()) {
      toast.error('Question and answer are required')
      return
    }

    setIsSubmitting(true)
    try {
      const body: Record<string, string> = {
        question: question.trim(),
        answer: answer.trim(),
        category,
      }

      if (protocol !== 'none') {
        body.protocol = protocol
      }

      const response = await makeAuthenticatedRequest(
        `/admin/escalations/${escalation.id}/generate-faq`,
        {
          method: 'POST',
          body: JSON.stringify(body),
        }
      )

      if (response.ok) {
        toast.success('FAQ generated successfully')
        onOpenChange(false)
      } else {
        const data = await response.json().catch(() => ({ detail: 'Failed to generate FAQ' }))
        toast.error(data.detail || 'Failed to generate FAQ')
      }
    } catch {
      toast.error('An error occurred while generating the FAQ')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Generate FAQ from Escalation</DialogTitle>
          <DialogDescription>
            Create a new FAQ entry from this resolved escalation
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit}>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label>Question</Label>
              <Input
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="FAQ question"
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label>Answer</Label>
              <Textarea
                rows={6}
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder="FAQ answer"
                required
                className="resize-y"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1.5">
                <Label>Category</Label>
                <Select value={category} onValueChange={setCategory}>
                  <SelectTrigger>
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
                <Label>Protocol</Label>
                <Select value={protocol} onValueChange={setProtocol}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select protocol" />
                  </SelectTrigger>
                  <SelectContent>
                    {PROTOCOL_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>{opt.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
          <DialogFooter className="mt-6">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Generate FAQ
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
