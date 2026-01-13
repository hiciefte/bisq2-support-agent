/**
 * Simplified source badges component
 * Displays sources as compact inline badges without label prefix
 */

import { cn } from "@/lib/utils"
import { BookOpen, MessageSquare } from "lucide-react"

interface Source {
    title: string
    type: string
    content: string
}

interface SourceBadgesProps {
    sources: Source[]
    className?: string
}

const getSourceConfig = (sourceType: string) => {
    switch (sourceType) {
        case "wiki":
            return {
                label: "Wiki",
                icon: BookOpen,
                className: "bg-primary/10 text-primary",
            }
        case "faq":
            return {
                label: "FAQ",
                icon: MessageSquare,
                className: "bg-secondary/50 text-secondary-foreground",
            }
        default:
            return {
                label: "Support Chat",
                icon: MessageSquare,
                className: "bg-secondary/50 text-secondary-foreground",
            }
    }
}

export const SourceBadges = ({ sources, className }: SourceBadgesProps) => {
    if (!sources || sources.length === 0) {
        return null
    }

    // Deduplicate sources by type
    const uniqueTypes = Array.from(new Set(sources.map((source) => source.type)))

    return (
        <div className={cn("flex items-center gap-1.5", className)}>
            {uniqueTypes.map((sourceType) => {
                const config = getSourceConfig(sourceType)
                const Icon = config.icon

                return (
                    <span
                        key={sourceType}
                        className={cn(
                            "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium",
                            config.className
                        )}
                    >
                        <Icon className="h-3 w-3" aria-hidden="true" />
                        {config.label}
                    </span>
                )
            })}
        </div>
    )
}
