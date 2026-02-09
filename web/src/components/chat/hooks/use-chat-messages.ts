/**
 * Hook for managing chat messages, API communication, and message state
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { v4 as uuidv4 } from 'uuid'
import { API_BASE_URL } from '@/lib/config'
import type { Message } from "../types/chat.types"

// Constants
const MAX_CHAT_HISTORY_LENGTH = 8
const CHAT_STORAGE_KEY = "bisq_chat_messages"

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

// Function to clean up AI responses
const cleanupResponse = (text: string): string => {
    return text.replace(/```+\s*$/, '').trim()
}

// Funny loading messages with {time} placeholder
const loadingMessages = [
    "Hang tight, our AI's flexing on a potato CPU—your answer's dropping in {time}!",
    "Grandma's dial-up soup takes longer than this—AI's got you in {time}!",
    "Chill, the AI's meditating with a modem for {time} before it enlightens you!",
    "Hamster union break! The AI's back in {time} with your fix!",
    "AI's procrastinating like a champ—give it {time} to stumble over!",
    "Turtles in molasses? That's our CPUs—your reply's {time} out!",
    "AI's sharpening its crayon—your answer's scribbled in {time}!",
    "Coffee break with a 56k vibe—AI's buzzing back in {time}!",
    "Sloth-mode AI: slow, steady, and {time} from brilliance!",
    "CPUs moonwalking your request—give 'em {time} to slide in!",
    "Drunk penguin AI waddling your way— ETA {time}!",
    "AI's arguing with a floppy disk—your turn's in {time}!",
    "Running on Wi-Fi fumes—AI's coughing up an answer in {time}!",
    "Mini-vacay time! AI's wrestling a calculator for {time}!",
    "Stuck in a 90s dial-up loop—AI escapes in {time}!",
    "Snail rave on the CPUs—your answer drops in {time}!",
    "AI's teaching a toaster binary—your toast pops in {time}!",
    "Smoking with a Commodore 64—AI hacks back in {time}!",
    "One-handed juggling with a brick—AI's ready in {time}!",
    "Unicycle CPU uphill grind—your answer's {time} away!"
]

// Convert seconds to a human-readable format
const formatResponseTime = (seconds: number): string => {
    return seconds < 60 ? `${Math.round(seconds)} seconds` : `${Math.round(seconds / 60)} minutes`
}

// Function to get a random loading message with the time placeholder replaced
const getRandomLoadingMessage = (avgTime: number): string => {
    const randomIndex = Math.floor(Math.random() * loadingMessages.length)
    const timeString = formatResponseTime(avgTime)
    return loadingMessages[randomIndex].replace('{time}', timeString)
}

const parseStoredMessages = (rawValue: string | null): Message[] => {
    if (!rawValue) {
        return []
    }

    try {
        const parsed: unknown = JSON.parse(rawValue)
        if (!Array.isArray(parsed)) {
            return []
        }

        return parsed
            .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
            .map((item) => ({
                ...item,
                timestamp: typeof item.timestamp === "string" ? new Date(item.timestamp) : new Date(),
            } as Message))
    } catch {
        return []
    }
}

export const useChatMessages = () => {
    // Start empty to keep server/client first render consistent, then hydrate from storage on mount.
    const [messages, setMessages] = useState<Message[]>([])
    const [storageHydrated, setStorageHydrated] = useState(false)

    const [input, setInput] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [loadingMessage, setLoadingMessage] = useState("")
    const [globalAverageResponseTime, setGlobalAverageResponseTime] = useState<number>(300)

    // Debounced save to localStorage
    const saveTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const debouncedSaveToLocalStorage = useCallback((msgs: Message[]) => {
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current)
        }
        saveTimeoutRef.current = setTimeout(() => {
            if (typeof window !== 'undefined') {
                localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(msgs))
            }
        }, 1000)
    }, [])

    useEffect(() => {
        if (typeof window === "undefined") {
            return
        }

        setMessages(parseStoredMessages(localStorage.getItem(CHAT_STORAGE_KEY)))
        setStorageHydrated(true)
    }, [])

    // Save messages to localStorage whenever they change (debounced)
    // Also clear localStorage when messages array becomes empty to avoid stale rehydration
    useEffect(() => {
        if (!storageHydrated) {
            return
        }

        if (messages.length > 0) {
            debouncedSaveToLocalStorage(messages)
        } else {
            // Clear localStorage when messages are emptied
            localStorage.removeItem(CHAT_STORAGE_KEY)
        }
        return () => {
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current)
            }
        }
    }, [messages, debouncedSaveToLocalStorage, storageHydrated])

    // Fetch global stats on component mount
    useEffect(() => {
        const fetchGlobalStats = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/chat/stats`)
                if (response.ok) {
                    const stats = await response.json()
                    const avgTime = stats.last_24h_average_response_time || stats.average_response_time || 300
                    setGlobalAverageResponseTime(avgTime)
                } else {
                    setGlobalAverageResponseTime(12)
                }
            } catch {
                setGlobalAverageResponseTime(12)
            }
        }

        fetchGlobalStats()
    }, [])

    // Memoized average response time calculation
    const avgResponseTime = useMemo(() => {
        const responseTimes = messages
            .filter(msg => msg.role === "assistant" && msg.metadata?.response_time)
            .map(msg => msg.metadata!.response_time)

        if (responseTimes.length === 0) {
            return globalAverageResponseTime
        }

        return responseTimes.reduce((acc, time) => acc + time, 0) / responseTimes.length
    }, [messages, globalAverageResponseTime])

    // Update loading message when isLoading changes
    useEffect(() => {
        if (isLoading) {
            setLoadingMessage(getRandomLoadingMessage(avgResponseTime))
        }
    }, [isLoading, avgResponseTime])

    const sendMessage = async (text: string) => {
        const userMessage: Message = {
            id: generateUUID(),
            content: text,
            role: "user",
            timestamp: new Date(),
        }

        // Use functional update to prevent message loss during rapid sends
        setMessages((prev) => [...prev, userMessage])

        // Compute updatedMessages for chatHistory (closure-based, acceptable for API call)
        const updatedMessages = [...messages, userMessage]

        setInput("")
        setIsLoading(true)

        try {
            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 600000)

            const chatHistory = updatedMessages.map(msg => ({
                role: msg.role,
                content: msg.content
            })).slice(-MAX_CHAT_HISTORY_LENGTH)

            try {
                const response = await fetch(`${API_BASE_URL}/chat/query`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        question: text,
                        chat_history: chatHistory
                    }),
                    signal: controller.signal
                })

                clearTimeout(timeoutId)

                if (!response.ok) {
                    const errorMessage: Message = {
                        id: generateUUID(),
                        content: `Error: Server returned ${response.status}. Please try again.`,
                        role: "assistant",
                        timestamp: new Date(),
                    }
                    setMessages((prev) => [...prev, errorMessage])
                    return
                }

                const data = await response.json()
                const assistantMessage: Message = {
                    id: generateUUID(),
                    content: cleanupResponse(data.answer),
                    role: "assistant",
                    timestamp: new Date(),
                    sources: data.sources,
                    metadata: {
                        response_time: data.response_time,
                        token_count: data.token_count || 0
                    },
                    confidence: data.confidence,
                    detected_version: data.detected_version,
                    version_confidence: data.version_confidence,
                    mcp_tools_used: data.mcp_tools_used,
                    routing_action: data.routing_action
                }

                // Use functional update to avoid message loss when multiple sends overlap
                setMessages((prev) => [...prev, assistantMessage])
            } catch (error: unknown) {
                let errorContent = "An error occurred while processing your request."

                if (error instanceof DOMException && error.name === "AbortError") {
                    errorContent = "The request took too long to complete. The server might be busy processing your question. Please try again later or ask a simpler question."
                } else if (error instanceof Error && process.env.NODE_ENV !== 'production') {
                    errorContent = `An error occurred: ${error.name} - ${error.message}. Please try again.`
                }

                const errorMessage: Message = {
                    id: generateUUID(),
                    content: cleanupResponse(errorContent),
                    role: "assistant",
                    timestamp: new Date(),
                }

                setMessages((prev) => [...prev, errorMessage])
            }
        } catch {
            const errorMessage: Message = {
                id: generateUUID(),
                content: "An unexpected error occurred. Please try again.",
                role: "assistant",
                timestamp: new Date(),
            }

            setMessages((prev) => [...prev, errorMessage])
        } finally {
            setIsLoading(false)
        }
    }

    const clearChatHistory = () => {
        setMessages([])
        if (typeof window !== 'undefined') {
            localStorage.removeItem(CHAT_STORAGE_KEY)
        }
    }

    return {
        messages,
        setMessages,
        input,
        setInput,
        isLoading,
        loadingMessage,
        avgResponseTime,
        sendMessage,
        clearChatHistory
    }
}
