/**
 * Source links trigger component
 * Displays a badge that opens source details on click
 * Uses popover on desktop and bottom sheet on mobile
 */

"use client"

import { useState } from "react"
import { BookMarked } from "lucide-react"
import { cn } from "@/lib/utils"
import { SourceLinksPopover } from "./source-links-popover"
import { SourceLinksSheet } from "./source-links-sheet"
import { useMediaQuery } from "../../hooks/use-media-query"
import type { Source } from "../../types/chat.types"

interface SourceLinksTriggerProps {
    sources: Source[]
    className?: string
}

export function SourceLinksTrigger({
    sources,
    className,
}: SourceLinksTriggerProps) {
    const [open, setOpen] = useState(false)
    const isMobile = useMediaQuery("(max-width: 640px)")

    if (!sources || sources.length === 0) {
        return null
    }

    const sourceCount = sources.length
    const label = sourceCount === 1 ? "1 source" : `${sourceCount} sources`

    const TriggerButton = (
        <button
            onClick={() => setOpen(true)}
            className={cn(
                "inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs",
                "bg-primary/10 text-primary hover:bg-primary/20 transition-colors",
                "focus:outline-none focus:ring-2 focus:ring-primary/50",
                className
            )}
            aria-haspopup="dialog"
            aria-expanded={open}
        >
            <BookMarked className="h-3.5 w-3.5" aria-hidden="true" />
            <span>{label}</span>
        </button>
    )

    if (isMobile) {
        return (
            <>
                {TriggerButton}
                <SourceLinksSheet
                    sources={sources}
                    open={open}
                    onOpenChange={setOpen}
                />
            </>
        )
    }

    return (
        <SourceLinksPopover
            sources={sources}
            open={open}
            onOpenChange={setOpen}
            trigger={TriggerButton}
        />
    )
}
