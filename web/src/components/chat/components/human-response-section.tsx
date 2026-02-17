/**
 * Inline display of a staff response below an AI message in the chat.
 * Shown when a staff member has responded to an escalated question.
 * Renders markdown and optionally shows a rating widget.
 */

import { CheckCircle } from "lucide-react"
import { MarkdownContent } from "./markdown-content"
import { Rating } from "@/components/ui/rating"

interface StaffResponse {
  answer: string
  responded_at: string
  rating?: number
  rate_token?: string
}

interface HumanResponseSectionProps {
  response: StaffResponse
  onRate?: (rating: number) => void
  messageId?: string
}

function formatResponseDate(timestamp: string): string {
  return new Date(timestamp).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

export function HumanResponseSection({ response, onRate }: HumanResponseSectionProps) {
  return (
    <section
      aria-label="Staff response"
      className="mt-2 p-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800"
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <CheckCircle aria-hidden="true" className="h-3.5 w-3.5 text-emerald-600 dark:text-emerald-400" />
        <span className="text-xs font-medium text-emerald-700 dark:text-emerald-300">
          Staff Response
        </span>
      </div>
      <MarkdownContent
        content={response.answer}
        className="prose-staff text-sm text-emerald-900 dark:text-emerald-100"
      />
      <time
        dateTime={response.responded_at}
        className="block text-[10px] text-emerald-600/70 dark:text-emerald-400/60 mt-1.5"
      >
        {formatResponseDate(response.responded_at)}
      </time>
      {onRate && (
        <div className="mt-2 pt-2 border-t border-emerald-200/50 dark:border-emerald-800/50">
          <Rating
            onRate={onRate}
            initialRating={response.rating}
            promptText="Was the staff response helpful?"
            thankYouText="Thank you for your feedback!"
            className="text-xs text-emerald-700 dark:text-emerald-300
                       flex-col items-start gap-1 sm:flex-row sm:items-center sm:gap-3"
          />
        </div>
      )}
    </section>
  )
}
