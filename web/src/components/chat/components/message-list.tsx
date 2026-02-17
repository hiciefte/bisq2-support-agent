/**
 * Component to render the list of messages with loading indicator
 */

import Image from "next/image"
import { MessageItem } from "./message-item"
import { WelcomeScreen } from "./welcome-screen"
import type { Message } from "../types/chat.types"

interface MessageListProps {
    messages: Message[]
    isLoading: boolean
    loadingMessage: string
    formattedAvgTime: string
    scrollAreaRef: React.RefObject<HTMLDivElement | null>
    loadingRef: React.RefObject<HTMLDivElement | null>
    onRating?: (messageId: string, rating: number) => void
    onStaffRate?: (messageId: string, rating: number, rateToken?: string) => void
}

export const MessageList = ({
    messages,
    isLoading,
    loadingMessage,
    formattedAvgTime,
    scrollAreaRef,
    loadingRef,
    onRating,
    onStaffRate
}: MessageListProps) => {
    return (
        <div className="flex-1 overflow-hidden">
            <div className="h-full overflow-y-auto" ref={scrollAreaRef}>
                <div className="mx-auto w-full max-w-2xl px-4">
                    <div className="flex-1 space-y-6 pb-48 pt-4">
                        {messages.length === 0 ? (
                            <WelcomeScreen formattedAvgTime={formattedAvgTime} />
                        ) : (
                            <>
                                {messages.map((message) => (
                                    <MessageItem
                                        key={message.id}
                                        message={message}
                                        onRating={onRating}
                                        onStaffRate={onStaffRate}
                                    />
                                ))}
                            </>
                        )}
                        {isLoading && (
                            <div
                                ref={loadingRef}
                                className="flex items-start gap-4 px-4"
                                role="status"
                                aria-live="polite"
                                aria-label="Assistant is thinking"
                            >
                                <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-background shadow">
                                    <Image
                                        src="/bisq-fav.png"
                                        alt="Bisq AI"
                                        width={24}
                                        height={24}
                                        priority
                                        className="rounded"
                                    />
                                </div>
                                <div className="flex-1 space-y-2">
                                    <div className="inline-flex flex-col rounded-lg px-3 py-2 text-sm bg-muted">
                                        <div className="flex gap-1 mb-2">
                                            <span className="animate-bounce">.</span>
                                            <span className="animate-bounce delay-100">.</span>
                                            <span className="animate-bounce delay-200">.</span>
                                        </div>
                                        <p className="text-xs text-muted-foreground">{loadingMessage}</p>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    )
}
