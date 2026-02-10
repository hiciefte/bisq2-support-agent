"use client"

/**
 * Main chat interface component
 * Refactored to use modular hooks and components
 */

import { FormEvent, useCallback, useEffect, useMemo } from "react"
import { PrivacyWarningModal } from "@/components/privacy/privacy-warning-modal"
import { MessageList } from "./components/message-list"
import { ChatInput } from "./components/chat-input"
import { FeedbackDialog } from "./components/feedback-dialog"
import { ChatProvider } from "./context"
import { useChatMessages } from "./hooks/use-chat-messages"
import { useChatScroll } from "./hooks/use-chat-scroll"
import { useFeedback } from "./hooks/use-feedback"
import { useEscalationPolling } from "./hooks/use-escalation-polling"

// Convert seconds to a human-readable format
const formatResponseTime = (seconds: number): string => {
    return seconds < 60 ? `${Math.round(seconds)} seconds` : `${Math.round(seconds / 60)} minutes`
}

const ChatInterface = () => {
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

    // Find the most recent escalated message that hasn't received a staff response yet
    const pendingEscalation = useMemo(() => {
        for (let i = messages.length - 1; i >= 0; i--) {
            const msg = messages[i]
            if (msg.requires_human && msg.escalation_message_id && !msg.staff_response) {
                return { messageId: msg.escalation_message_id, msgId: msg.id }
            }
        }
        return null
    }, [messages])

    // Poll for escalation resolution
    const escalationPoll = useEscalationPolling(
        pendingEscalation?.messageId ?? null,
        !!pendingEscalation
    )

    // When polling resolves, update the message with the staff response
    useEffect(() => {
        if (
            escalationPoll.status === 'resolved' &&
            escalationPoll.staffAnswer &&
            pendingEscalation
        ) {
            setMessages(prev =>
                prev.map(msg =>
                    msg.id === pendingEscalation.msgId
                        ? {
                              ...msg,
                              staff_response: {
                                  answer: escalationPoll.staffAnswer!,
                                  responded_at: escalationPoll.respondedAt || new Date().toISOString(),
                              },
                          }
                        : msg
                )
            )
        }
    }, [escalationPoll.status, escalationPoll.staffAnswer, escalationPoll.respondedAt, pendingEscalation, setMessages])

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
            <PrivacyWarningModal />
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
                    onClearHistory={clearChatHistory}
                />
            </div>
        </ChatProvider>
    )
}

export { ChatInterface }
