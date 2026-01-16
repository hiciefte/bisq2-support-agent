/**
 * Desktop popover for displaying source links
 * Uses Radix UI Popover for accessible dropdown
 */

"use client"

import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover"
import { X } from "lucide-react"
import { SourceLinkItem } from "./source-link-item"
import { groupSourcesByArticle } from "./relevance-utils"
import type { Source } from "../../types/chat.types"

interface SourceLinksPopoverProps {
    sources: Source[]
    open: boolean
    onOpenChange: (open: boolean) => void
    trigger: React.ReactNode
}

export function SourceLinksPopover({
    sources,
    open,
    onOpenChange,
    trigger,
}: SourceLinksPopoverProps) {
    const groupedSources = groupSourcesByArticle(sources)

    return (
        <Popover open={open} onOpenChange={onOpenChange}>
            <PopoverTrigger asChild>{trigger}</PopoverTrigger>

            <PopoverContent
                className="w-[min(320px,calc(100vw-2rem))] max-h-96 overflow-hidden p-0"
                sideOffset={8}
                align="start"
            >
                {/* Header */}
                <div className="flex items-center justify-between px-3 py-2 border-b">
                    <h3 className="font-medium text-sm">
                        Sources ({sources.length})
                    </h3>
                    <button
                        onClick={() => onOpenChange(false)}
                        className="rounded-full p-1 hover:bg-muted transition-colors"
                        aria-label="Close"
                    >
                        <X className="h-4 w-4" aria-hidden="true" />
                    </button>
                </div>

                {/* Content */}
                <div className="overflow-y-auto max-h-80">
                    {groupedSources.map((source, idx) => (
                        <SourceLinkItem
                            key={`${source.type}-${source.title}-${idx}`}
                            source={source}
                        />
                    ))}
                </div>
            </PopoverContent>
        </Popover>
    )
}
