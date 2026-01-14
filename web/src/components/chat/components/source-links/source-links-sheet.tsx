/**
 * Mobile bottom sheet for displaying source links
 * Uses Radix UI Sheet for accessible sliding panel
 */

"use client"

import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
} from "@/components/ui/sheet"
import { SourceLinkItem } from "./source-link-item"
import { groupSourcesByArticle } from "./relevance-utils"
import type { Source } from "../../types/chat.types"

interface SourceLinksSheetProps {
    sources: Source[]
    open: boolean
    onOpenChange: (open: boolean) => void
}

export function SourceLinksSheet({
    sources,
    open,
    onOpenChange,
}: SourceLinksSheetProps) {
    const groupedSources = groupSourcesByArticle(sources)

    return (
        <Sheet open={open} onOpenChange={onOpenChange}>
            <SheetContent side="bottom" className="h-[70vh] rounded-t-xl">
                <SheetHeader className="border-b pb-3">
                    <SheetTitle>Sources ({sources.length})</SheetTitle>
                </SheetHeader>

                <div className="overflow-y-auto h-[calc(70vh-4rem)] py-2">
                    {groupedSources.map((source, idx) => (
                        <SourceLinkItem
                            key={`${source.type}-${source.title}-${idx}`}
                            source={source}
                        />
                    ))}
                </div>
            </SheetContent>
        </Sheet>
    )
}
