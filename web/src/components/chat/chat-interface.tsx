"use client"

/**
 * Main chat interface component
 * Refactored to use modular hooks and components
 */

import { FormEvent } from "react"
import { PrivacyWarningModal } from "@/components/privacy/privacy-warning-modal"
import { MessageList } from "./components/message-list"
import { ChatInput } from "./components/chat-input"
import { FeedbackDialog } from "./components/feedback-dialog"
import { useChatMessages } from "./hooks/use-chat-messages"
import { useChatScroll } from "./hooks/use-chat-scroll"
import { useFeedback } from "./hooks/use-feedback"

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

    // Format average response time for display
    const formattedAvgTime = formatResponseTime(avgResponseTime)

    // Handle form submission
    const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault()
        if (!input.trim()) return
        await sendMessage(input)
    }

    // Handle example question clicks
    const handleQuestionClick = async (question: string) => {
        await sendMessage(question)
    }

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
            setFeedbackDialog(prev => ({ ...prev, isOpen: false }))
        }
    }

    return (
        <>
            <PrivacyWarningModal />
            <div className="flex flex-col h-full overflow-hidden">
                <MessageList
                    messages={messages}
                    isLoading={isLoading}
                    loadingMessage={loadingMessage}
                    formattedAvgTime={formattedAvgTime}
                    scrollAreaRef={scrollAreaRef}
                    loadingRef={loadingRef}
                    onRating={handleRating}
                />

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
        </>
    )
}

export { ChatInterface }
