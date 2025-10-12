/**
 * Component to render individual chat messages
 */

import Image from "next/image"
import { UserIcon } from "lucide-react"
import { cn } from "@/lib/utils"
import { Rating } from "@/components/ui/rating"
import { SourceDisplay } from "./source-display"
import type { Message } from "../types/chat.types"

interface MessageItemProps {
    message: Message
    onRating?: (messageId: string, rating: number) => void
}

export const MessageItem = ({ message, onRating }: MessageItemProps) => {
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
            <div className={cn("flex-1 space-y-2", message.role === "user" ? "text-right" : "")}>
                <div className="inline-block rounded-lg px-3 py-2 text-sm bg-muted">
                    {message.content}
                </div>
                {message.sources && message.sources.length > 0 && (
                    <SourceDisplay sources={message.sources} />
                )}
                {message.role === "assistant" && message.id && !message.isThankYouMessage && onRating && (
                    <Rating
                        className="justify-start"
                        onRate={(rating) => onRating(message.id!, rating)}
                    />
                )}
            </div>
        </div>
    )
}
