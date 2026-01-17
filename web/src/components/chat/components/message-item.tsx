/**
 * Component to render individual chat messages
 * Consolidated metadata row following Apple/Vercel/shadcn design principles
 * Memoized to prevent unnecessary re-renders when parent state changes
 */

import { memo } from "react"
import Image from "next/image"
import { UserIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Rating } from "@/components/ui/rating"
import { LiveDataBadge } from "@/components/live-data"
import { SourceBadges } from "./source-badges"
import { ConfidenceBadge } from "./confidence-badge"
import { LiveDataContent } from "./live-data-content"
import type { Message } from "../types/chat.types"

interface MessageItemProps {
    message: Message
    onRating?: (messageId: string, rating: number) => void
}

export const MessageItem = memo(function MessageItem({ message, onRating }: MessageItemProps) {
    const isAssistant = message.role === "assistant"
    const hasSources = message.sources && message.sources.length > 0
    const hasConfidence = message.confidence !== undefined
    const hasLiveData = message.mcp_tools_used && message.mcp_tools_used.length > 0
    const canRate = message.id && !message.isThankYouMessage && onRating

    // Format timestamp for LiveDataBadge
    const formattedTimestamp = message.timestamp instanceof Date
        ? message.timestamp.toISOString()
        : message.timestamp

    // Extract tool data from MCP tools (single filter pass, reused for inline check)
    const toolNames = message.mcp_tools_used?.map(t => t.tool)
    const toolResults = message.mcp_tools_used
        ?.filter(t => t.result).map(t => ({ tool: t.tool, result: t.result! })) ?? []

    // Check if live data is displayed inline (via LiveDataContent with PriceDisplay)
    // Reuses toolResults to avoid double-filtering
    const hasInlineLiveData = toolResults.length > 0

    // Only show LiveDataBadge in metadata row when live data is NOT displayed inline
    const showLiveBadgeInMetadata = hasLiveData && !hasInlineLiveData

    const hasMetadata = isAssistant && (hasSources || hasConfidence || showLiveBadgeInMetadata || canRate)

    return (
        <div
            className={cn(
                "flex items-start gap-4 px-4",
                !isAssistant && "flex-row-reverse"
            )}
        >
            {isAssistant ? (
                <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-background shadow">
                    <Image
                        src="/bisq-fav.png"
                        alt="Bisq AI"
                        width={24}
                        height={24}
                        className="rounded"
                    />
                </div>
            ) : (
                <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-accent">
                    <UserIcon className="h-4 w-4" />
                </div>
            )}
            <div className={cn("flex-1 space-y-2", !isAssistant && "text-right")}>
                <div className="inline-block rounded-lg px-3 py-2 text-sm bg-muted">
                    {isAssistant && hasLiveData && toolResults.length > 0 ? (
                        <LiveDataContent
                            content={message.content}
                            toolResults={toolResults}
                            timestamp={formattedTimestamp}
                        />
                    ) : (
                        message.content
                    )}
                </div>

                {hasMetadata && (
                    <div
                        className={cn(
                            "flex items-start gap-2 pt-1 text-xs",
                            "flex-col sm:flex-row sm:items-center sm:justify-between"
                        )}
                    >
                        <div className="flex flex-wrap items-center gap-2">
                            {hasSources && <SourceBadges sources={message.sources!} />}
                            {hasConfidence && (
                                <ConfidenceBadge
                                    confidence={message.confidence!}
                                    version={message.detected_version}
                                />
                            )}
                            {showLiveBadgeInMetadata && (
                                <LiveDataBadge
                                    type="live"
                                    timestamp={formattedTimestamp}
                                    toolsUsed={toolNames}
                                />
                            )}
                        </div>

                        {canRate && (
                            <Rating
                                className="self-end sm:self-auto flex-shrink-0"
                                onRate={(rating) => onRating(message.id!, rating)}
                            />
                        )}
                    </div>
                )}
            </div>
        </div>
    )
})
