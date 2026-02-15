import * as React from "react"
import { ThumbsUp, ThumbsDown } from "lucide-react"
import { cn } from "@/lib/utils"

interface RatingProps {
  onRate: (rating: number) => void
  initialRating?: number
  className?: string
  disabled?: boolean
  promptText?: string
  thankYouText?: string
}

export function Rating({
  onRate,
  initialRating,
  className,
  disabled = false,
  promptText = "Was this response helpful?",
  thankYouText = "Thank you for your feedback!",
}: RatingProps) {
  const [rating, setRating] = React.useState<number | null>(initialRating ?? null)
  const [hasRated, setHasRated] = React.useState(initialRating !== undefined)

  const handleRate = (value: number) => {
    if (disabled || hasRated) return
    setRating(value)
    setHasRated(true)
    onRate(value)
  }

  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="text-sm text-muted-foreground">
        {hasRated ? thankYouText : promptText}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          aria-label="Rate as helpful"
          disabled={disabled || hasRated}
          className={cn(
            "rounded-sm p-2 text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default transition-colors",
            !hasRated && "disabled:opacity-50",
            !hasRated && "hover:text-[#25B135]",
            rating === 1 && "text-[#25B135] opacity-100"
          )}
          onClick={() => handleRate(1)}
        >
          <ThumbsUp className="h-4 w-4" />
        </button>
        <button
          type="button"
          aria-label="Rate as unhelpful"
          disabled={disabled || hasRated}
          className={cn(
            "rounded-sm p-2 text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-default transition-colors",
            !hasRated && "disabled:opacity-50",
            !hasRated && "hover:text-destructive",
            rating === 0 && "text-destructive opacity-100"
          )}
          onClick={() => handleRate(0)}
        >
          <ThumbsDown className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}
