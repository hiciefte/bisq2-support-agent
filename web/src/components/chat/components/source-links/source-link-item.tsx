/**
 * Individual source link item component
 * Displays a single source with title, section, content preview, and relevance
 */

"use client"

import { ExternalLink, BookOpen, MessageSquare, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { RelevancePill } from "./relevance-pill"
import type { GroupedSource } from "./relevance-utils"
import { useState } from "react"

interface SourceLinkItemProps {
    source: GroupedSource
}

export function SourceLinkItem({ source }: SourceLinkItemProps) {
    const [expanded, setExpanded] = useState(false)
    const hasMultipleSections = source.sections.length > 1

    const Icon = source.type === "wiki" ? BookOpen : MessageSquare

    const handleClick = () => {
        if (source.url) {
            window.open(source.url, "_blank", "noopener,noreferrer")
        } else if (hasMultipleSections) {
            setExpanded(!expanded)
        }
    }

    return (
        <div className="border-b border-border/50 last:border-0">
            <button
                onClick={handleClick}
                className={cn(
                    "w-full flex items-start gap-3 p-3 text-left transition-colors",
                    (source.url || hasMultipleSections) &&
                        "hover:bg-muted/50 cursor-pointer"
                )}
            >
                <Icon
                    className="h-4 w-4 mt-0.5 text-muted-foreground flex-shrink-0"
                    aria-hidden="true"
                />

                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium text-sm truncate">
                            {source.title}
                        </span>
                        {source.url && (
                            <ExternalLink
                                className="h-3 w-3 text-muted-foreground flex-shrink-0"
                                aria-hidden="true"
                            />
                        )}
                    </div>

                    {source.sections[0]?.section && (
                        <p className="text-xs text-muted-foreground mb-1">
                            #{source.sections[0].section}
                            {hasMultipleSections &&
                                ` +${source.sections.length - 1} more`}
                        </p>
                    )}

                    <p className="text-xs text-muted-foreground line-clamp-2">
                        {source.sections[0]?.content}
                    </p>
                </div>

                <div className="flex flex-col items-end gap-1 flex-shrink-0">
                    <RelevancePill score={source.maxScore} />
                    {hasMultipleSections && !source.url && (
                        <ChevronDown
                            className={cn(
                                "h-4 w-4 text-muted-foreground transition-transform",
                                expanded && "rotate-180"
                            )}
                            aria-hidden="true"
                        />
                    )}
                </div>
            </button>

            {/* Expanded sections for grouped items */}
            {expanded && hasMultipleSections && (
                <div className="pl-10 pr-3 pb-3 space-y-2">
                    {source.sections.slice(1).map((section, idx) => (
                        <div
                            key={idx}
                            className="text-xs text-muted-foreground pl-3 border-l-2 border-border"
                        >
                            {section.section && (
                                <p className="font-medium mb-0.5">
                                    #{section.section}
                                </p>
                            )}
                            <p className="line-clamp-2">{section.content}</p>
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
}
