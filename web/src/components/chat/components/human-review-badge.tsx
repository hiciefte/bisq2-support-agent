/**
 * Badge shown on chat messages that have been escalated for human review.
 * Displays a sky-blue notification with pulse animation while awaiting staff response.
 */

import { RefreshCw, Users } from "lucide-react"

interface HumanReviewBadgeProps {
  label?: string
  stale?: boolean
}

export function HumanReviewBadge({
  label,
  stale = false,
}: HumanReviewBadgeProps) {
  const Icon = stale ? RefreshCw : Users
  const text = label ?? (stale
    ? "Support response check timed out. Refresh to check again."
    : "Support team notified")

  return (
    <div
      className={
        stale
          ? "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-300"
          : "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-sky-50 dark:bg-sky-950/30 border border-sky-200 dark:border-sky-800 text-sky-700 dark:text-sky-300 motion-safe:animate-pulse"
      }
    >
      <Icon className="h-3 w-3" />
      <span>{text}</span>
    </div>
  )
}
