/**
 * Hook for managing chat messages, API communication, and message state
 */

import { useEffect, useState } from "react"
import { v4 as uuidv4 } from 'uuid'
import { API_BASE_URL } from '@/lib/config'
import type { Message } from "../types/chat.types"

// Constants
const MAX_CHAT_HISTORY_LENGTH = 8

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

export const useChatMessages = () => {
    // Load messages from localStorage on initial render
    const [messages, setMessages] = useState<Message[]>(() => {
        if (typeof window !== 'undefined') {
            const savedMessages = localStorage.getItem('bisq_chat_messages')
            return savedMessages ? JSON.parse(savedMessages) : []
        }
        return []
    })

    const [input, setInput] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [loadingMessage, setLoadingMessage] = useState("")
    const [globalAverageResponseTime, setGlobalAverageResponseTime] = useState<number>(300)

    // Save messages to localStorage whenever they change
    useEffect(() => {
        if (typeof window !== 'undefined' && messages.length > 0) {
            localStorage.setItem('bisq_chat_messages', JSON.stringify(messages))
            console.log('Saved messages to localStorage:', messages)
        }
    }, [messages])

    // Fetch global stats on component mount
    useEffect(() => {
        const fetchGlobalStats = async () => {
            try {
                const statsUrl = `${API_BASE_URL}/chat/stats`
                console.log(`Fetching stats from: ${statsUrl}`)

                const response = await fetch(statsUrl)
                console.log(`Stats response status: ${response.status} ${response.statusText}`)

                if (response.ok) {
                    const stats = await response.json()
                    console.log('Stats response data:', stats)
                    const avgTime = stats.last_24h_average_response_time || stats.average_response_time || 300
                    setGlobalAverageResponseTime(avgTime)
                    console.log('Loaded global average response time:', avgTime)
                } else {
                    console.error('Failed to fetch global stats:', response.statusText)
                    console.log('Using default average response time of 12 seconds')
                    setGlobalAverageResponseTime(12)
                }
            } catch (error) {
                console.error('Error fetching global stats:', error)
                console.log('Using default average response time of 12 seconds')
                setGlobalAverageResponseTime(12)
            }
        }

        fetchGlobalStats()
    }, [])

    // Calculate average response time from existing messages
    const calculateLocalAverageResponseTime = (): number => {
        const responseTimes = messages
            .filter(msg => msg.role === "assistant" && msg.metadata?.response_time)
            .map(msg => msg.metadata!.response_time)

        if (responseTimes.length === 0) {
            return globalAverageResponseTime
        }

        const sum = responseTimes.reduce((acc, time) => acc + time, 0)
        return sum / responseTimes.length
    }

    // Get the average response time, preferring local data if available
    const avgResponseTime = calculateLocalAverageResponseTime()

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

        const updatedMessages = [...messages, userMessage]
        setMessages(updatedMessages)
        console.log('Updated messages state:', updatedMessages)

        setInput("")
        setIsLoading(true)

        try {
            console.log(`Using API URL: ${API_BASE_URL}`)

            const controller = new AbortController()
            const timeoutId = setTimeout(() => controller.abort(), 600000)

            const chatHistory = updatedMessages.map(msg => ({
                role: msg.role,
                content: msg.content
            })).slice(-MAX_CHAT_HISTORY_LENGTH)

            if (process.env.NODE_ENV !== 'production') {
                console.log("Sending chat history:", chatHistory)
            }

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
                    }
                }

                const updatedWithResponse = [...updatedMessages, assistantMessage]
                setMessages(updatedWithResponse)
                console.log('Updated messages with assistant response:', updatedWithResponse)
            } catch (error: unknown) {
                let errorContent = "An error occurred while processing your request."

                if (error instanceof DOMException && error.name === "AbortError") {
                    errorContent = "The request took too long to complete. The server might be busy processing your question. Please try again later or ask a simpler question."
                } else {
                    console.error("Error fetching response:", error)
                    if (error instanceof Error) {
                        console.error("Error name:", error.name)
                        console.error("Error message:", error.message)
                        console.error("Error stack:", error.stack)

                        if (process.env.NODE_ENV !== 'production') {
                            errorContent = `An error occurred: ${error.name} - ${error.message}. Please try again.`
                        }
                    }

                    console.error("Request URL:", `${API_BASE_URL}/chat/query`)
                    console.error("Question length:", text.length)
                    console.error("Chat history length:", chatHistory.length)
                }

                const errorMessage: Message = {
                    id: generateUUID(),
                    content: cleanupResponse(errorContent),
                    role: "assistant",
                    timestamp: new Date(),
                }

                setMessages((prev) => [...prev, errorMessage])
            }
        } catch (error: unknown) {
            console.error("Error in sendMessage:", error)
            if (error instanceof Error) {
                console.error("Error message:", error.message)
                console.error("Error stack:", error.stack)
            }

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
            localStorage.removeItem('bisq_chat_messages')
            console.log('Chat history cleared')
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
