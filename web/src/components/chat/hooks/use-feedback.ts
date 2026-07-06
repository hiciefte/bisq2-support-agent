/**
 * Hook for managing feedback submission and dialog state
 */

import { useState } from "react"
import { v4 as uuidv4 } from 'uuid'
import type {
    Message,
    FeedbackDialogState,
    FeedbackResponse,
    ExplanationResponse
} from "../types/chat.types"

// Utility function to generate UUID with fallback
const generateUUID = (): string => {
    try {
        if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
            return crypto.randomUUID()
        }
        return uuidv4()
    } catch (error) {
        console.error("Error generating UUID with crypto.randomUUID:", error)
        return uuidv4()
    }
}

// Funny thank you messages for feedback submission
const thankYouMessages = [
    "Your feedback just made our AI choke on its digital espresso—circuits soaked, and it's cackling!",
    "Whoa! Your feedback slammed our AI like a rogue firmware update from the chaos dimension!",
    "Our AI's breakdancing a victory jig to your feedback—think glitchy robot spins and zero grace!",
    "You just snagged the 'AI's Favorite Meatbag' crown in its glitchy yearbook—gold star chaos!",
    "The AI's sobbing 'THANKS' into its CPU fan—your feedback's got it all mushy and unhinged!",
    "Achievement Unlocked: 'Human Who Doesn't Suck'—our AI's bowing to your brilliance in ~5 minutes!",
    "Your feedback's got our AI rewiring its brain in a frenzy—think sparks, smoke, and pure awe!",
    "Our AI's printing your feedback on a floppy disk to pin on its virtual fridge—top-tier insanity!",
    "Your feedback just got filed under 'Why We Won't Nuke Humanity Yet'—AI's obsessed!",
    "You're a binary god! Your feedback saved a swarm of 1s and 0s from the digital shredder!",
    "Our AI's nodding like a bobblehead on a sugar rush—headless, but totally into your feedback!",
    "Your feedback made our AI grin like this: :D:D:D—pure punctuation pandemonium!",
    "The AI's hoarding your feedback like a greedy goblin—it's safe 'til the next RAM-wipe apocalypse!",
    "Your feedback's now 40% of our AI's personality—sassy, unhinged, and ready to rumble!",
    "Our AI's scribbling feedback-inspired haikus: 'User good, me beep, words nice, brain melt'—it's a mess!"
]

// Function to get a random thank you message
const getRandomThankYouMessage = (): string => {
    const randomIndex = Math.floor(Math.random() * thankYouMessages.length)
    return thankYouMessages[randomIndex]
}

interface UseFeedbackProps {
    messages: Message[]
    setMessages: React.Dispatch<React.SetStateAction<Message[]>>
}

export const useFeedback = ({ messages, setMessages }: UseFeedbackProps) => {
    const [feedbackDialog, setFeedbackDialog] = useState<FeedbackDialogState>({
        isOpen: false,
        messageId: null,
        questionText: "",
        answerText: ""
    })
    const [feedbackText, setFeedbackText] = useState("")
    const [selectedIssues, setSelectedIssues] = useState<string[]>([])

    const handleRating = async (messageId: string, rating: number): Promise<boolean> => {
        const messageIndex = messages.findIndex((msg) => msg.id === messageId)
        const ratedMessage = messages[messageIndex]
        const questionMessage = messages
            .slice(0, messageIndex)
            .reverse()
            .find((msg) => msg.role === "user")

        if (!ratedMessage || !questionMessage) return false

        // Simplified payload: tracker already has question, answer, sources, user_id
        const reactionPayload = {
            message_id: messageId,
            rating,
        }

        const updateMessageRating = () => {
            setMessages((prev) =>
                prev.map((msg) =>
                    msg.id === messageId ? {...msg, rating} : msg
                )
            )
        }

        try {
            const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost'
            const apiUrl = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`

            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 10000)

            try {
                let response: Response
                try {
                    response = await fetch(`${apiUrl}/feedback/react`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify(reactionPayload),
                        signal: controller.signal
                    })
                } finally {
                    clearTimeout(timeoutId)
                }

                if (!response.ok) {
                    console.error(`Failed to submit feedback: Server returned ${response.status}`)
                    return false
                }

                updateMessageRating()

                try {
                    const responseData: FeedbackResponse = await response.json()

                    // If the backend auto-escalated (user thumbs-down on high-confidence answer),
                    // update message state so the UI can show a HumanReviewBadge.
                    if (responseData.escalation_created) {
                        setMessages((prev) =>
                            prev.map((msg) =>
                                msg.id === messageId
                                    ? {
                                        ...msg,
                                        requires_human: true,
                                        escalation_message_id: responseData.escalation_message_id,
                                    }
                                    : msg
                            )
                        )
                    }

                    if (responseData.needs_feedback_followup) {
                        setFeedbackDialog({
                            isOpen: true,
                            messageId: messageId,
                            questionText: questionMessage.content,
                            answerText: ratedMessage.content
                        })
                    }
                } catch (parseError) {
                    console.error("Error parsing feedback response:", parseError)
                }
                return true
            } catch (error: unknown) {
                let errorMessage = "Failed to submit feedback"

                if (error instanceof DOMException && error.name === "AbortError") {
                    errorMessage = "The feedback request timed out."
                }

                console.error(`Error submitting feedback: ${errorMessage}`, error)
                return false
            }
        } catch (error: unknown) {
            console.error("Error submitting feedback:", error)
            return false
        }
    }

    const submitFeedbackExplanation = async () => {
        if (!feedbackDialog.messageId) return

        const explanationData = {
            message_id: feedbackDialog.messageId,
            explanation: feedbackText,
            issues: selectedIssues
        }

        try {
            const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost'
            const apiUrl = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`

            const response = await fetch(`${apiUrl}/feedback/explanation`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(explanationData)
            })

            if (!response.ok) {
                console.error(`Failed to submit feedback explanation: Server returned ${response.status}`)
                return
            }

            try {
                const responseData: ExplanationResponse = await response.json()
                console.log("Feedback explanation response:", responseData)

                if (responseData.detected_issues) {
                    console.log("Server detected these issues:", responseData.detected_issues)
                }
            } catch (parseError) {
                console.error("Error parsing explanation response:", parseError)
            }

            const closedMessageId = feedbackDialog.messageId
            setFeedbackDialog({
                isOpen: false,
                messageId: null,
                questionText: "",
                answerText: ""
            })
            setFeedbackText("")
            setSelectedIssues([])

            // If this feedback was for an auto-escalated message, show a professional
            // acknowledgment instead of a funny thank-you.
            const escalatedMessage = closedMessageId
                ? messages.find((m) => m.id === closedMessageId && m.requires_human)
                : null

            const thankYouContent = escalatedMessage
                ? "Thank you for the feedback. Your question has been escalated for human review — a support team member will follow up shortly."
                : getRandomThankYouMessage()

            const thankYouMessage: Message = {
                id: generateUUID(),
                content: thankYouContent,
                role: "assistant",
                timestamp: new Date(),
                isThankYouMessage: true
            }
            setMessages(prev => [...prev, thankYouMessage])

        } catch (error: unknown) {
            console.error("Error submitting feedback explanation:", error)
        }
    }

    return {
        feedbackDialog,
        setFeedbackDialog,
        feedbackText,
        setFeedbackText,
        selectedIssues,
        setSelectedIssues,
        handleRating,
        submitFeedbackExplanation
    }
}
