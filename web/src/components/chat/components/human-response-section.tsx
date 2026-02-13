/**
 * Inline display of a staff response below an AI message in the chat.
 * Shown when a staff member has responded to an escalated question.
 */

import { CheckCircle } from "lucide-react"

interface StaffResponse {
  answer: string
  responded_at: string
}

interface HumanResponseSectionProps {
  response: StaffResponse
}

function formatResponseDate(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function HumanResponseSection({ response }: HumanResponseSectionProps) {
  return (
    <div className="mt-2 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800">
      <div className="flex items-center gap-1.5 mb-1.5">
        <CheckCircle className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
        <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">
          Staff Response
        </span>
      </div>
      <p className="text-sm text-emerald-900 dark:text-emerald-100 leading-relaxed whitespace-pre-wrap">
        {response.answer}
      </p>
      <p className="text-[10px] text-emerald-600/70 dark:text-emerald-400/60 mt-1.5">
        {formatResponseDate(response.responded_at)}
      </p>
    </div>
  )
}
