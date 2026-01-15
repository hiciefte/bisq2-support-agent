/**
 * Source badges component
 * Displays sources as a clickable badge that opens source details
 */

import { SourceLinksTrigger } from "./source-links"
import type { Source } from "../types/chat.types"

interface SourceBadgesProps {
    sources: Source[]
    className?: string
}

export function SourceBadges({ sources, className }: SourceBadgesProps) {
    // SourceLinksTrigger handles empty sources internally
    return <SourceLinksTrigger sources={sources} className={className} />
}
