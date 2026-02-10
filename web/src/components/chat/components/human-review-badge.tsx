/**
 * Badge shown on chat messages that have been escalated for human review.
 * Displays a sky-blue notification with pulse animation while awaiting staff response.
 */

import { Users } from "lucide-react"

export function HumanReviewBadge() {
  return (
    <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium bg-sky-50 dark:bg-sky-950/30 border border-sky-200 dark:border-sky-800 text-sky-700 dark:text-sky-300 motion-safe:animate-pulse">
      <Users className="h-3 w-3" />
      <span>Support team notified</span>
    </div>
  )
}
