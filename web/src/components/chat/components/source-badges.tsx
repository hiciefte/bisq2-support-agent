/**
 * Source badges component
 * Displays sources as a clickable badge that opens source details
 */

import { SourceLinksTrigger } from "./source-links"
import { cn } from "@/lib/utils"
import type { Source } from "../types/chat.types"

interface SourceBadgesProps {
    sources: Source[]
    className?: string
}

export const SourceBadges = ({ sources, className }: SourceBadgesProps) => {
    return (
        <div className={cn("flex items-center gap-1.5", className)}>
            <SourceLinksTrigger sources={sources} />
        </div>
    )
}
