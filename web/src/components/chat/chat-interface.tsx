"use client"

import {useEffect, useRef, useState} from "react"
import {Button} from "@/components/ui/button"
import {Input} from "@/components/ui/input"
import {Loader2, MessageSquare, Plus, Send, UserIcon} from "lucide-react"
import {cn} from "@/lib/utils"
import {Rating} from "@/components/ui/rating"
import Image from "next/image"
import { v4 as uuidv4 } from 'uuid'

// Utility function to generate UUID with fallback
const generateUUID = (): string => {
  try {
    // Try to use the native crypto.randomUUID() first
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID();
    }
    // Fall back to uuid library if crypto.randomUUID is not available
    return uuidv4();
  } catch (error) {
    // Final fallback in case of any errors
    return uuidv4();
  }
};

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

// Function to calculate average response time from messages
const calculateAverageResponseTime = (messages: Message[]): number => {
  const responseTimes = messages
    .filter(msg => msg.role === "assistant" && msg.metadata?.response_time)
    .map(msg => msg.metadata!.response_time);
  
  if (responseTimes.length === 0) return 300; // Default to 5 minutes (300 seconds) if no data
  
  const sum = responseTimes.reduce((acc, time) => acc + time, 0);
  return sum / responseTimes.length;
};

// Convert seconds to a human-readable format
const formatResponseTime = (seconds: number): string => {
  if (seconds < 60) return `${Math.round(seconds)} seconds`;
  const minutes = Math.round(seconds / 60);
  return `~${minutes} minute${minutes !== 1 ? 's' : ''}`;
};

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
];

// Function to get a random loading message with the time placeholder replaced
const getRandomLoadingMessage = (avgTime: number): string => {
  const randomIndex = Math.floor(Math.random() * loadingMessages.length);
  const timeString = formatResponseTime(avgTime);
  return loadingMessages[randomIndex].replace('{time}', timeString);
};

// Function to clean up AI responses
const cleanupResponse = (text: string): string => {
  // Remove trailing backticks that might be included in the AI response
  return text.replace(/```+\s*$/, '').trim();
};

const ChatInterface = () => {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [loadingMessage, setLoadingMessage] = useState("");
  const scrollAreaRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const loadingRef = useRef<HTMLDivElement>(null)
  
  // Calculate average response time from existing messages
  const avgResponseTime = calculateAverageResponseTime(messages);
  const formattedAvgTime = formatResponseTime(avgResponseTime);

  // Example questions that can be clicked
  const exampleQuestions = [
    "What is Bisq Easy and how does it work?",
    "How does the reputation system work in Bisq 2?",
    "What are the main differences between Bisq 1 and Bisq 2?",
    "How can I safely buy bitcoin on Bisq 2?"
  ]

  // Update loading message when isLoading changes
  useEffect(() => {
    if (isLoading) {
      setLoadingMessage(getRandomLoadingMessage(avgResponseTime));
    }
  }, [isLoading, avgResponseTime]);

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
      id: generateUUID(),
      content: text,
      role: "user",
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)

    try {
      // Use window.location.hostname to get the current server's hostname
      // This ensures that when accessed remotely, it uses the correct server address
      const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`;
      console.log(`Using API URL: ${apiUrl}`);
      
      // Create an AbortController to handle timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 60000); // 60 second timeout
      
      try {
        const response = await fetch(`${apiUrl}/chat/query`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            question: text,
          }),
          signal: controller.signal
        });
        
        // Clear the timeout since the request completed
        clearTimeout(timeoutId);

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

        setMessages((prev) => [...prev, assistantMessage])
      } catch (error) {
        // Handle AbortController error (timeout) or other fetch errors
        let errorContent = "An error occurred while processing your request.";
        
        if (error instanceof DOMException && error.name === "AbortError") {
          errorContent = "The request took too long to complete. The server might be busy processing your question. Please try again later or ask a simpler question.";
        } else {
          console.error("Error fetching response:", error);
        }
        
        const errorMessage: Message = {
          id: generateUUID(),
          content: cleanupResponse(errorContent),
          role: "assistant",
          timestamp: new Date(),
        }
        
        setMessages((prev) => [...prev, errorMessage])
      }
    } catch (error) {
      console.error("Error in sendMessage:", error);
      
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
      // Use the same dynamic API URL as the chat query
      const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`;
      
      // Create an AbortController to handle timeout
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10000); // 10 second timeout for feedback
      
      try {
        const response = await fetch(`${apiUrl}/feedback/submit`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify(feedbackData),
          signal: controller.signal
        });
        
        // Clear the timeout since the request completed
        clearTimeout(timeoutId);

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
        // Handle AbortController error (timeout) or other fetch errors
        let errorMessage = "Failed to submit feedback";
        
        if (error instanceof DOMException && error.name === "AbortError") {
          errorMessage = "The feedback request timed out. Your rating has been saved locally.";
        }
        
        console.error(`Error submitting feedback: ${errorMessage}`, error);
        
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
                    Meet your digital dumpster fire of wisdom! Our CPU-powered chaos takes about {formattedAvgTime} to answer, but the wait's worth it. Picture a caffeinated gremlin strapped to spare toaster parts, here to solve your Bisq 2 questions!
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
