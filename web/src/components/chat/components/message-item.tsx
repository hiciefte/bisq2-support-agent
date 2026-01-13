/**
 * Component to render individual chat messages
 * Updated with consolidated metadata row following Apple/Vercel/shadcn design principles
 */

import Image from "next/image"
import { UserIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Rating } from "@/components/ui/rating"
import { SourceBadges } from "./source-badges"
import { ConfidenceBadge } from "./confidence-badge"
import type { Message } from "../types/chat.types"

interface MessageItemProps {
    message: Message
    onRating?: (messageId: string, rating: number) => void
}

export const MessageItem = ({ message, onRating }: MessageItemProps) => {
    const hasMetadata =
        message.role === "assistant" &&
        ((message.sources && message.sources.length > 0) ||
            message.confidence !== undefined ||
            (message.id && !message.isThankYouMessage && onRating))

    return (
        <div
            className={cn(
                "flex items-start gap-4 px-4",
                message.role === "user" ? "flex-row-reverse" : ""
            )}
        >
            {message.role === "assistant" ? (
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
            <div
                className={cn(
                    "flex-1 space-y-2",
                    message.role === "user" ? "text-right" : ""
                )}
            >
                <div className="inline-block rounded-lg px-3 py-2 text-sm bg-muted">
                    {message.content}
                </div>

                {/* Consolidated metadata row - sources, confidence, and rating */}
                {hasMetadata && (
                    <div
                        className={cn(
                            "flex items-start gap-2 pt-1 text-xs",
                            "flex-col sm:flex-row sm:items-center sm:justify-between"
                        )}
                    >
                        {/* Left side: Sources and confidence */}
                        <div className="flex flex-wrap items-center gap-2">
                            {message.sources && message.sources.length > 0 && (
                                <SourceBadges sources={message.sources} />
                            )}
                            {message.confidence !== undefined && (
                                <ConfidenceBadge
                                    confidence={message.confidence}
                                    version={message.detected_version}
                                />
                            )}
                        </div>

                        {/* Right side: Rating */}
                        {message.id && !message.isThankYouMessage && onRating && (
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
}
