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
import type { Message } from "../types/chat.types"

interface MessageItemProps {
    message: Message
    onRating?: (messageId: string, rating: number) => void
}

export const MessageItem = memo(function MessageItem({ message, onRating }: MessageItemProps) {
    const isAssistant = message.role === "assistant"
    const hasSources = message.sources && message.sources.length > 0
    const hasConfidence = message.confidence !== undefined
    const hasLiveData = Boolean(message.mcp_tools_used)
    const canRate = message.id && !message.isThankYouMessage && onRating

    const hasMetadata = isAssistant && (hasSources || hasConfidence || hasLiveData || canRate)

    // Format timestamp for LiveDataBadge
    const formattedTimestamp = message.timestamp instanceof Date
        ? message.timestamp.toISOString()
        : message.timestamp

    // Extract tool names from MCP tools
    const toolNames = Array.isArray(message.mcp_tools_used)
        ? message.mcp_tools_used.map(t => t.tool)
        : undefined

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
                    {message.content}
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
                            {hasLiveData && (
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
