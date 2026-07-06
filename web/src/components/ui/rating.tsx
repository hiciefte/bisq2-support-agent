import * as React from "react"
import { ThumbsUp, ThumbsDown } from "lucide-react"
import { cn } from "@/lib/utils"

interface RatingProps {
  onRate: (rating: number) => boolean | void | Promise<boolean | void>
  initialRating?: number | null
  className?: string
  disabled?: boolean
  promptText?: string
  thankYouText?: string
  savingText?: string
  errorText?: string
}

export function Rating({
  onRate,
  initialRating,
  className,
  disabled = false,
  promptText = "Was this response helpful?",
  thankYouText = "Thank you for your feedback!",
  savingText = "Saving...",
  errorText = "Could not save feedback. Try again.",
}: RatingProps) {
  const [rating, setRating] = React.useState<number | null>(initialRating ?? null)
  const [hasRated, setHasRated] = React.useState(initialRating != null)
  const [pendingRating, setPendingRating] = React.useState<number | null>(null)
  const [error, setError] = React.useState<string | null>(null)

  React.useEffect(() => {
    setRating(initialRating ?? null)
    setHasRated(initialRating != null)
    setError(null)
    setPendingRating(null)
  }, [initialRating])

  const handleRate = async (value: number) => {
    if (disabled || hasRated || pendingRating !== null) return
    setPendingRating(value)
    setError(null)
    try {
      const result = await onRate(value)
      if (result === false) {
        setError(errorText)
        return
      }
      setRating(value)
      setHasRated(true)
    } catch {
      setError(errorText)
    } finally {
      setPendingRating(null)
    }
  }

  const isSubmitting = pendingRating !== null
  const statusText = hasRated ? thankYouText : isSubmitting ? savingText : error ?? promptText

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="text-sm text-muted-foreground" role="status" aria-live="polite">
        {statusText}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          aria-label="Rate as helpful"
          disabled={disabled || hasRated || isSubmitting}
          className={cn(
            "rounded-sm p-2 text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default transition-colors",
            !hasRated && "disabled:opacity-50",
            !hasRated && "hover:text-[#25B135]",
            (rating === 1 || pendingRating === 1) && "text-[#25B135] opacity-100"
          )}
          onClick={() => handleRate(1)}
        >
          <ThumbsUp className="h-4 w-4" />
        </button>
        <button
          type="button"
          aria-label="Rate as unhelpful"
          disabled={disabled || hasRated || isSubmitting}
          className={cn(
            "rounded-sm p-2 text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default transition-colors",
            !hasRated && "disabled:opacity-50",
            !hasRated && "hover:text-destructive",
            (rating === 0 || pendingRating === 0) && "text-destructive opacity-100"
          )}
          onClick={() => handleRate(0)}
        >
          <ThumbsDown className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
