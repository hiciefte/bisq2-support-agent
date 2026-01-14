/**
 * Relevance pill component for displaying source relevance level
 */

import { cn } from "@/lib/utils"
import { getRelevanceConfig } from "./relevance-utils"

interface RelevancePillProps {
    score: number | undefined
    className?: string
}

export function RelevancePill({ score, className }: RelevancePillProps) {
    const config = getRelevanceConfig(score)

    return (
        <span
            className={cn(
                "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
                config.className,
                className
            )}
        >
            {config.label}
        </span>
    )
}
