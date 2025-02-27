"use client"

import {useEffect, useRef, useState} from "react"
import {Button} from "@/components/ui/button"
import {Input} from "@/components/ui/input"
import {Loader2, MessageSquare, Plus, Send, UserIcon} from "lucide-react"
import {cn} from "@/lib/utils"
import {Rating} from "@/components/ui/rating"
import Image from "next/image"

interface Message {
  id: string
  content: string
  role: "user" | "assistant"
  timestamp: Date
  rating?: number
  sources?: Array<{
    title: string
    type: string
    content: string
  }>
  metadata?: {
    response_time: number
    token_count: number
  }
}

const ChatInterface = () => {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const loadingRef = useRef<HTMLDivElement>(null)

  // Example questions that can be clicked
  const exampleQuestions = [
    "What is Bisq Easy and how does it work?",
    "How does the reputation system work in Bisq 2?",
    "What are the main differences between Bisq 1 and Bisq 2?",
    "How can I safely buy bitcoin on Bisq 2?"
  ]

  useEffect(() => {
    if (scrollAreaRef.current) {
      scrollAreaRef.current.scrollTop = scrollAreaRef.current.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    if (isLoading && loadingRef.current) {
      loadingRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [isLoading])

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!input.trim()) return
    await sendMessage(input)
  }

  const handleQuestionClick = async (question: string) => {
    await sendMessage(question)
  }

  const sendMessage = async (text: string) => {
    const userMessage: Message = {
      id: crypto.randomUUID(),
      content: text,
      role: "user",
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)

    try {
      const response = await fetch("http://localhost:8000/chat/query", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: text,
        }),
      })

      if (!response.ok) {
        const errorMessage: Message = {
          id: crypto.randomUUID(),
          content: `Error: Server returned ${response.status}. Please try again.`,
          role: "assistant",
          timestamp: new Date(),
        }
        setMessages((prev) => [...prev, errorMessage])
        return
      }

      const data = await response.json()
      const assistantMessage: Message = {
        id: crypto.randomUUID(),
        content: data.answer,
        role: "assistant",
        timestamp: new Date(),
        sources: data.sources,
        metadata: {
          response_time: data.response_time,
          token_count: data.token_count
        }
      }

      setMessages((prev) => [...prev, assistantMessage])
    } catch (error) {
      console.error("Error:", error)
      const errorMessage: Message = {
        id: crypto.randomUUID(),
        content: "Sorry, I encountered an error connecting to the server. Please check your connection and try again.",
        role: "assistant",
        timestamp: new Date(),
      }
      setMessages((prev) => [...prev, errorMessage])
    } finally {
      setIsLoading(false)
    }
  }

  const handleRating = async (messageId: string, rating: number) => {
    // Find the rated message and its corresponding question
    const messageIndex = messages.findIndex((msg) => msg.id === messageId)
    const ratedMessage = messages[messageIndex]
    const questionMessage = messages
      .slice(0, messageIndex)
      .reverse()
      .find((msg) => msg.role === "user")

    if (!ratedMessage || !questionMessage) return

    // Get previous ratings in this conversation
    const previousRatings = messages
      .slice(0, messageIndex)
      .filter((msg) => msg.role === "assistant" && msg.rating !== undefined)
      .map((msg) => msg.rating!)

    // Prepare feedback data
    const feedbackData = {
      message_id: messageId,
      question: questionMessage.content,
      answer: ratedMessage.content,
      rating,
      sources: ratedMessage.sources,
      metadata: {
        response_time: ratedMessage.metadata?.response_time || 0,
        token_count: ratedMessage.metadata?.token_count,
        conversation_id: messages[0].id,
        timestamp: new Date().toISOString(),
        previous_ratings: previousRatings
      }
    }

    try {
      // Send feedback to server
      const response = await fetch("http://localhost:8000/feedback/submit", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(feedbackData),
      })

      if (!response.ok) {
        // Handle error response directly instead of throwing
        console.error(`Failed to submit feedback: Server returned ${response.status}`)
        
        // Store in local storage as backup even when server request fails
        const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}")
        storedRatings[messageId] = feedbackData
        localStorage.setItem("messageRatings", JSON.stringify(storedRatings))
        
        // Still update the UI to show the rating
        setMessages((prev) =>
          prev.map((msg) =>
            msg.id === messageId ? { ...msg, rating } : msg
          )
        )
        
        return
      }

      // Update message with rating locally
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === messageId ? { ...msg, rating } : msg
        )
      )

      // Store in local storage as backup
      const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}")
      storedRatings[messageId] = feedbackData
      localStorage.setItem("messageRatings", JSON.stringify(storedRatings))
    } catch (error) {
      console.error("Error submitting feedback:", error)
      
      // Even if there's a network error, still update the UI and store locally
      setMessages((prev) =>
        prev.map((msg) =>
          msg.id === messageId ? { ...msg, rating } : msg
        )
      )
      
      // Store in local storage as backup
      const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}")
      storedRatings[messageId] = feedbackData
      localStorage.setItem("messageRatings", JSON.stringify(storedRatings))
    }
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Messages container */}
      <div className="flex-1 overflow-hidden">
        <div className="h-full overflow-y-auto">
          <div className="mx-auto w-full max-w-2xl px-4">
            <div className="flex-1 space-y-6 pb-32 pt-4">
              {messages.length === 0 ? (
                <div className="flex h-[calc(100vh-280px)] flex-col items-center justify-center">
                  <div className="flex items-center justify-center space-x-3 mb-4">
                    <Image
                      src="/bisq-fav.png"
                      alt="Bisq AI"
                      width={40}
                      height={40}
                      className="rounded"
                    />
                    <Plus className="h-5 w-5 text-muted-foreground" />
                    <MessageSquare className="h-8 w-8 text-muted-foreground" />
                  </div>
                  <p className="text-lg font-medium mb-2">Welcome to Bisq Support AI</p>
                  <p className="text-sm text-muted-foreground text-center max-w-sm mb-8">
                    Your AI-powered assistant for Bisq-related questions. Ask anything about trading, features, or troubleshooting.
                  </p>
                </div>
              ) : (
                <>
                  {messages.map((message, index) => (
                    <div key={index} className={cn("flex items-start gap-4 px-4", message.role === "user" ? "flex-row-reverse" : "")}>
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
                          <div className="text-xs text-muted-foreground">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-medium">Sources:</span>
                              {message.sources.map((source, index) => (
                                <span key={index} className={cn(
                                  "px-2 py-1 rounded-md text-xs",
                                  source.type === "wiki" ? "bg-primary/10" : "bg-secondary/50"
                                )}>
                                  {source.type === "wiki" ? "Wiki" : "Support Chat"}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        {message.role === "assistant" && message.id && (
                          <Rating
                            className="justify-start"
                            onRate={(rating) => handleRating(message.id!, rating)}
                          />
                        )}
                      </div>
                    </div>
                  ))}
                </>
              )}
              {isLoading && (
                <div ref={loadingRef} className="flex items-start gap-4 px-4">
                  <div className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-background shadow">
                    <Image
                      src="/bisq-fav.png"
                      alt="Bisq AI"
                      width={24}
                      height={24}
                      className="rounded"
                    />
                  </div>
                  <div className="flex-1 space-y-2">
                    <div className="inline-flex items-center rounded-lg px-3 py-2 text-sm bg-muted">
                      <div className="flex gap-1">
                        <span className="animate-bounce">.</span>
                        <span className="animate-bounce delay-100">.</span>
                        <span className="animate-bounce delay-200">.</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Input form */}
      <form onSubmit={handleSubmit} className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-background from-50% to-transparent to-100% p-4">
        <div className="mx-auto w-full max-w-2xl px-4">
          {messages.length === 0 && (
            <div className="grid grid-cols-2 gap-4 w-full mb-4">
              {exampleQuestions.map((question, index) => (
                <button
                  key={index}
                  onClick={() => handleQuestionClick(question)}
                  className="rounded-lg border border-border/60 bg-card/50 p-4 text-left text-sm text-muted-foreground transition-colors hover:bg-muted"
                >
                  {question}
                </button>
              ))}
            </div>
          )}
          <div className="relative">
            <Input
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder={isLoading ? "Thinking..." : "Ask a question..."}
              className="min-h-[80px] pt-3 pb-10 pr-12 rounded-lg bg-muted/50 focus:bg-background align-top"
              disabled={isLoading}
            />
            <Button 
              type="submit" 
              size="icon" 
              disabled={isLoading || !input.trim()}
              className={cn(
                "absolute right-2 bottom-2 transition-colors",
                input.trim() ? "bg-[#25B135] hover:bg-[#25B135]/90" : "bg-transparent hover:bg-transparent"
              )}
            >
              {isLoading ? (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              ) : (
                <Send className={cn(
                  "h-4 w-4",
                  input.trim() ? "text-white" : "text-muted-foreground"
                )} />
              )}
            </Button>
          </div>
        </div>
      </form>
    </div>
  )
}

export { ChatInterface }
