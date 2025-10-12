/**
 * Hook for managing chat scroll behavior
 */

import { useEffect, useRef } from "react"
import type { Message } from "../types/chat.types"

export const useChatScroll = (messages: Message[], isLoading: boolean) => {
    const scrollAreaRef = useRef<HTMLDivElement>(null)
    const loadingRef = useRef<HTMLDivElement>(null)

    // Auto-scroll when messages change
    useEffect(() => {
        if (scrollAreaRef.current) {
            scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight
        }
    }, [messages])

    // Auto-scroll to loading indicator
    useEffect(() => {
        if (isLoading && loadingRef.current) {
            loadingRef.current.scrollIntoView({ behavior: "smooth" })
        }
    }, [isLoading])

    return {
        scrollAreaRef,
        loadingRef
    }
}
