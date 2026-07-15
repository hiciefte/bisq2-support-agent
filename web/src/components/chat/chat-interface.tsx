"use client"

/**
 * Main chat interface component
 * Refactored to use modular hooks and components
 */

import { FormEvent, useCallback, useEffect, useMemo } from "react"
import type { Dispatch, SetStateAction } from "react"
import { API_BASE_URL } from "@/lib/config"
import { PrivacyWarningModal } from "@/components/privacy/privacy-warning-modal"
import { MessageList } from "./components/message-list"
import { ChatInput } from "./components/chat-input"
import { FeedbackDialog } from "./components/feedback-dialog"
import { ChatProvider } from "./context"
import { useChatMessages } from "./hooks/use-chat-messages"
import { useChatScroll } from "./hooks/use-chat-scroll"
import { useFeedback } from "./hooks/use-feedback"
import { useEscalationPolling } from "./hooks/use-escalation-polling"
import type { Message } from "./types/chat.types"

// Convert seconds to a human-readable format
const formatResponseTime = (seconds: number): string => {
    return seconds < 60 ? `${Math.round(seconds)} seconds` : `${Math.round(seconds / 60)} minutes`
}

interface PendingEscalation {
    messageId: string
    localMessageId: string
}

interface ChatInterfaceProps {
    retentionDays: number
}

interface EscalationResolutionWatcherProps {
    pending: PendingEscalation
    setMessages: Dispatch<SetStateAction<Message[]>>
}

function EscalationResolutionWatcher({
    pending,
    setMessages,
}: EscalationResolutionWatcherProps) {
    const escalationPoll = useEscalationPolling(pending.messageId, true)

    useEffect(() => {
        if (escalationPoll.status === "stale") {
            setMessages(prev =>
                prev.map(msg =>
                    msg.id === pending.localMessageId
                        ? {
                              ...msg,
                              escalation_polling_status: "stale",
                          }
                        : msg
                )
            )
            return
        }

        if (escalationPoll.status !== "resolved") return

        // Staff responded: attach staff response and mark escalation as resolved.
        // Prefer presence of staff answer over resolution flag to handle
        // "closed-after-responded" lifecycle transitions.
        if (escalationPoll.staffAnswer) {
            setMessages(prev =>
                prev.map(msg =>
                    msg.id === pending.localMessageId
                        ? {
                              ...msg,
                              escalation_polling_status: undefined,
                              escalation_resolution: "responded",
                              escalation_resolved_at: escalationPoll.respondedAt || new Date().toISOString(),
                              escalation_user_language: escalationPoll.userLanguage ?? msg.escalation_user_language,
                              staff_response: {
                                  ...msg.staff_response,
                                  answer: escalationPoll.staffAnswer!,
                                  responded_at: escalationPoll.respondedAt || new Date().toISOString(),
                                  rating: escalationPoll.staffAnswerRating ?? msg.staff_response?.rating,
                                  rate_token: escalationPoll.rateToken ?? msg.staff_response?.rate_token,
                              },
                          }
                        : msg
                )
            )
            return
        }

        // Closed/dismissed without reply: stop showing "Support team notified" forever.
        if (escalationPoll.resolution === "closed") {
            setMessages(prev =>
                prev.map(msg =>
                    msg.id === pending.localMessageId
                        ? {
                              ...msg,
                              requires_human: false,
                              escalation_polling_status: undefined,
                              escalation_resolution: "closed",
                              escalation_resolved_at: escalationPoll.respondedAt || new Date().toISOString(),
                              escalation_user_language: escalationPoll.userLanguage ?? msg.escalation_user_language,
                          }
                        : msg
                )
            )
        }
    }, [
        escalationPoll.status,
        escalationPoll.staffAnswer,
        escalationPoll.respondedAt,
        escalationPoll.resolution,
        escalationPoll.staffAnswerRating,
        escalationPoll.rateToken,
        escalationPoll.userLanguage,
        pending.localMessageId,
        setMessages,
    ])

    return null
}

const ChatInterface = ({ retentionDays }: ChatInterfaceProps) => {
    // Chat messages and API communication
    const {
        messages,
        setMessages,
        input,
        setInput,
        isLoading,
        loadingMessage,
        avgResponseTime,
        sendMessage,
        cancelCurrentRequest,
        clearChatHistory
    } = useChatMessages()

    // Auto-scroll behavior
    const { scrollAreaRef, loadingRef } = useChatScroll(messages, isLoading)

    // Feedback management
    const {
        feedbackDialog,
        setFeedbackDialog,
        feedbackText,
        setFeedbackText,
        selectedIssues,
        setSelectedIssues,
        handleRating,
        submitFeedbackExplanation
    } = useFeedback({ messages, setMessages })

    // Poll every escalated message that has not received a terminal staff state.
    const pendingEscalations = useMemo(() => {
        return messages
            .filter(
                (msg) =>
                    msg.requires_human &&
                    msg.escalation_message_id &&
                    !msg.staff_response &&
                    msg.escalation_resolution !== "closed" &&
                    msg.escalation_polling_status !== "stale"
            )
            .map((msg) => ({
                messageId: msg.escalation_message_id!,
                localMessageId: msg.id,
            }))
    }, [messages])

    // Handle staff answer rating
    const handleStaffRating = useCallback(
        async (messageId: string, rating: number, rateToken?: string) => {
        try {
            const resp = await fetch(`${API_BASE_URL}/escalations/${messageId}/rate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    rating,
                    ...(rateToken ? { rate_token: rateToken } : {}),
                }),
            })
            if (resp.ok) {
                // Update local state after server confirms the rating
                setMessages(prev =>
                    prev.map(msg =>
                        msg.escalation_message_id === messageId && msg.staff_response
                            ? { ...msg, staff_response: { ...msg.staff_response, rating } }
                            : msg
                    )
                )
            }
        } catch (error) {
            console.error("Failed to submit staff answer rating:", error)
        }
    }, [setMessages])

    // Format average response time for display
    const formattedAvgTime = formatResponseTime(avgResponseTime)

    // Handle form submission
    const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        if (!input.trim()) return
        await sendMessage(input)
    }

    // Handle example question clicks (memoized for context provider)
    const handleQuestionClick = useCallback(async (question: string) => {
        await sendMessage(question)
    }, [sendMessage])

    // Memoized setInput for context provider
    const handleSetInput = useCallback((value: string) => {
        setInput(value)
    }, [setInput])

    // Handle feedback dialog issue toggle
    const handleIssueToggle = (issueId: string) => {
        setSelectedIssues(prev =>
            prev.includes(issueId)
                ? prev.filter(id => id !== issueId)
                : [...prev, issueId]
        )
    }

    // Handle feedback dialog close
    const handleDialogOpenChange = (open: boolean) => {
        if (!open) {
            // Reset all feedback state when dialog closes
            setFeedbackDialog(prev => ({ ...prev, isOpen: false }))
            setFeedbackText('')
            setSelectedIssues([])
        }
    }

    return (
        <ChatProvider onSendQuestion={handleQuestionClick} onSetInput={handleSetInput}>
            {pendingEscalations.map((pending) => (
                <EscalationResolutionWatcher
                    key={`${pending.messageId}:${pending.localMessageId}`}
                    pending={pending}
                    setMessages={setMessages}
                />
            ))}
            <PrivacyWarningModal retentionDays={retentionDays} />
            <div className="flex flex-col h-full overflow-hidden">
                <div role="log" aria-live="polite" aria-label="Chat conversation" className="flex-1 min-h-0 flex flex-col">
                    <MessageList
                        messages={messages}
                        isLoading={isLoading}
                        loadingMessage={loadingMessage}
                        formattedAvgTime={formattedAvgTime}
                        scrollAreaRef={scrollAreaRef}
                        loadingRef={loadingRef}
                        onRating={handleRating}
                        onStaffRate={handleStaffRating}
                    />
                </div>

                <FeedbackDialog
                    dialogState={feedbackDialog}
                    feedbackText={feedbackText}
                    selectedIssues={selectedIssues}
                    onOpenChange={handleDialogOpenChange}
                    onFeedbackTextChange={setFeedbackText}
                    onIssueToggle={handleIssueToggle}
                    onSubmit={submitFeedbackExplanation}
                />

                <ChatInput
                    input={input}
                    isLoading={isLoading}
                    hasMessages={messages.length > 0}
                    onInputChange={setInput}
                    onSubmit={handleSubmit}
                    onQuestionClick={handleQuestionClick}
                    onCancelRequest={cancelCurrentRequest}
                    onClearHistory={clearChatHistory}
                />
            </div>
        </ChatProvider>
    )
}

export { ChatInterface }
