"use client"

import {useEffect, useRef, useState} from "react"
import {Button} from "@/components/ui/button"
import {Input} from "@/components/ui/input"
import {Loader2, MessageSquare, Plus, Send, UserIcon} from "lucide-react"
import {cn} from "@/lib/utils"
import {Rating} from "@/components/ui/rating"
import Image from "next/image"
import {v4 as uuidv4} from 'uuid'
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import {Textarea} from "@/components/ui/textarea"
import {Checkbox} from "@/components/ui/checkbox"
import {Label} from "@/components/ui/label"
import {PrivacyWarningModal} from "@/components/privacy/privacy-warning-modal"
import Link from "next/link"

// Constants
const MAX_CHAT_HISTORY_LENGTH = 8; // Configurable: Adjust this to include more or less context

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
        // Log the error before falling back
        console.error("Error generating UUID with crypto.randomUUID:", error);
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
    isThankYouMessage?: boolean
}

// Convert seconds to a human-readable format
const formatResponseTime = (seconds: number): string => {
    return seconds < 60 ? `${Math.round(seconds)} seconds` : `${Math.round(seconds / 60)} minutes`;
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
];

// Function to get a random loading message with the time placeholder replaced
const getRandomLoadingMessage = (avgTime: number): string => {
    const randomIndex = Math.floor(Math.random() * loadingMessages.length);
    const timeString = formatResponseTime(avgTime);
    return loadingMessages[randomIndex].replace('{time}', timeString);
};

// Function to get a random thank you message
const getRandomThankYouMessage = (): string => {
    const randomIndex = Math.floor(Math.random() * thankYouMessages.length);
    return thankYouMessages[randomIndex];
};

// Function to clean up AI responses
const cleanupResponse = (text: string): string => {
    // Remove trailing backticks that might be included in the AI response
    return text.replace(/```+\s*$/, '').trim();
};

// Add these interface definitions near other interfaces
interface FeedbackDialogState {
    isOpen: boolean
    messageId: string | null
    questionText: string
    answerText: string
}

interface FeedbackIssue {
    id: string
    label: string
}

// Add these type definitions near the top of the file, with the other type definitions
interface FeedbackResponse {
    success: boolean;
    message: string;
    needs_feedback_followup?: boolean;
}

interface ExplanationResponse {
    success: boolean;
    message: string;
    detected_issues?: string[];
}

const ChatInterface = () => {
    // Load messages from localStorage on initial render
    const [messages, setMessages] = useState<Message[]>(() => {
        if (typeof window !== 'undefined') {
            const savedMessages = localStorage.getItem('bisq_chat_messages');
            return savedMessages ? JSON.parse(savedMessages) : [];
        }
        return [];
    });
    const [input, setInput] = useState("")
    const [isLoading, setIsLoading] = useState(false)
    const [loadingMessage, setLoadingMessage] = useState("");
    const scrollAreaRef = useRef<HTMLDivElement>(null)
    const inputRef = useRef<HTMLInputElement>(null)
    const loadingRef = useRef<HTMLDivElement>(null)
    const [globalAverageResponseTime, setGlobalAverageResponseTime] = useState<number>(300); // Default to 5 minutes
    const [feedbackDialog, setFeedbackDialog] = useState<FeedbackDialogState>({
        isOpen: false,
        messageId: null,
        questionText: "",
        answerText: ""
    });
    const [feedbackText, setFeedbackText] = useState("");
    const [selectedIssues, setSelectedIssues] = useState<string[]>([]);

    // Save messages to localStorage whenever they change
    useEffect(() => {
        if (typeof window !== 'undefined' && messages.length > 0) {
            localStorage.setItem('bisq_chat_messages', JSON.stringify(messages));
            console.log('Saved messages to localStorage:', messages);
        }
    }, [messages]);

    // Fetch global stats on component mount
    useEffect(() => {
        const fetchGlobalStats = async () => {
            try {
                // Use the same API URL construction as in sendMessage
                const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
                const apiUrl = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`;
                const statsUrl = `${apiUrl}/chat/stats`;
                console.log(`Fetching stats from: ${statsUrl}`);

                const response = await fetch(statsUrl);
                console.log(`Stats response status: ${response.status} ${response.statusText}`);

                if (response.ok) {
                    const stats = await response.json();
                    console.log('Stats response data:', stats);
                    // Use the last 24h average if available, otherwise use the overall average
                    const avgTime = stats.last_24h_average_response_time || stats.average_response_time || 300;
                    setGlobalAverageResponseTime(avgTime);
                    console.log('Loaded global average response time:', avgTime);
                } else {
                    console.error('Failed to fetch global stats:', response.statusText);
                    // Fall back to a reasonable default if we can't get stats
                    console.log('Using default average response time of 12 seconds');
                    setGlobalAverageResponseTime(12); // Use a more reasonable default based on actual data
                }
            } catch (error) {
                console.error('Error fetching global stats:', error);
                // Fall back to a reasonable default if we can't get stats
                console.log('Using default average response time of 12 seconds');
                setGlobalAverageResponseTime(12); // Use a more reasonable default based on actual data
            }
        };

        fetchGlobalStats();
    }, []);

    // Calculate average response time from existing messages
    const calculateLocalAverageResponseTime = (): number => {
        const responseTimes = messages
            .filter(msg => msg.role === "assistant" && msg.metadata?.response_time)
            .map(msg => msg.metadata!.response_time);

        if (responseTimes.length === 0) {
            // If no local response times, use the global average
            return globalAverageResponseTime;
        }

        const sum = responseTimes.reduce((acc, time) => acc + time, 0);
        return sum / responseTimes.length;
    };

    // Get the average response time, preferring local data if available
    const avgResponseTime = calculateLocalAverageResponseTime();
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
            loadingRef.current.scrollIntoView({behavior: "smooth"})
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

        // Update messages state with the new user message
        const updatedMessages = [...messages, userMessage];
        setMessages(updatedMessages);
        console.log('Updated messages state:', updatedMessages);

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
            const timeoutId = setTimeout(() => controller.abort(), 600000); // 60 second timeout

            // Format previous messages for chat history
            // Use updatedMessages to ensure the latest user message is included
            const chatHistory = updatedMessages.map(msg => ({
                role: msg.role,
                content: msg.content
            })).slice(-MAX_CHAT_HISTORY_LENGTH); // Only send limited messages to keep context manageable

            // For production, remove or customize this logging
            if (process.env.NODE_ENV !== 'production') {
                console.log("Sending chat history:", chatHistory);
            }

            try {
                const response = await fetch(`${apiUrl}/chat/query`, {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        question: text,
                        chat_history: chatHistory // Send chat history to the API
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

                // Use the updatedMessages approach for consistent state handling
                const updatedWithResponse = [...updatedMessages, assistantMessage];
                setMessages(updatedWithResponse);
                console.log('Updated messages with assistant response:', updatedWithResponse);
            } catch (error: unknown) {
                // Handle AbortController error (timeout) or other fetch errors
                let errorContent = "An error occurred while processing your request.";

                if (error instanceof DOMException && error.name === "AbortError") {
                    errorContent = "The request took too long to complete. The server might be busy processing your question. Please try again later or ask a simpler question.";
                } else {
                    console.error("Error fetching response:", error);
                    // Include error message in the log if available
                    if (error instanceof Error) {
                        console.error("Error message:", error.message);
                    }
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
            // Log the detailed error information
            console.error("Error in sendMessage:", error);
            if (error instanceof Error) {
                console.error("Error message:", error.message);
            }
            if (error instanceof Error) {
                console.error("Error stack:", error.stack);
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

        // Prepare conversation history (last 10 messages before the rated message)
        // Filter out thank you messages to maintain proper user/assistant alternation
        const conversationHistory = messages
            .slice(Math.max(0, messageIndex - 10), messageIndex)
            .filter(msg => !msg.isThankYouMessage)
            .map(msg => ({
                role: msg.role,
                content: msg.content
            }));

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
            },
            conversation_history: conversationHistory
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
                            msg.id === messageId ? {...msg, rating} : msg
                        )
                    )

                    return
                }

                // Update message with rating locally
                setMessages((prev) =>
                    prev.map((msg) =>
                        msg.id === messageId ? {...msg, rating} : msg
                    )
                )

                // Store in local storage as backup
                const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}")
                storedRatings[messageId] = feedbackData
                localStorage.setItem("messageRatings", JSON.stringify(storedRatings))

                // Try to parse response data for feedback follow-up
                try {
                    const responseData: FeedbackResponse = await response.json();

                    // Check if we need to follow up based on the response
                    if (responseData.needs_feedback_followup) {
                        setFeedbackDialog({
                            isOpen: true,
                            messageId: messageId,
                            questionText: questionMessage.content,
                            answerText: ratedMessage.content
                        });
                    }
                } catch (parseError) {
                    console.error("Error parsing feedback response:", parseError);
                }
            } catch (error: unknown) {
                // Handle AbortController error (timeout) or other fetch errors
                let errorMessage = "Failed to submit feedback";

                if (error instanceof DOMException && error.name === "AbortError") {
                    errorMessage = "The feedback request timed out. Your rating has been saved locally.";
                }

                console.error(`Error submitting feedback: ${errorMessage}`, error);

                // Even if there's a network error, still update the UI and store locally
                setMessages((prev) =>
                    prev.map((msg) =>
                        msg.id === messageId ? {...msg, rating} : msg
                    )
                )

                // Store in local storage as backup
                const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}")
                storedRatings[messageId] = feedbackData
                localStorage.setItem("messageRatings", JSON.stringify(storedRatings))
            }
        } catch (error: unknown) {
            console.error("Error submitting feedback:", error)

            // Even if there's a network error, still update the UI and store locally
            setMessages((prev) =>
                prev.map((msg) =>
                    msg.id === messageId ? {...msg, rating} : msg
                )
            )

            // Store in local storage as backup
            const storedRatings = JSON.parse(localStorage.getItem("messageRatings") || "{}")
            storedRatings[messageId] = feedbackData
            localStorage.setItem("messageRatings", JSON.stringify(storedRatings))
        }
    }

    // Add a function to clear chat history
    const clearChatHistory = () => {
        setMessages([]);
        if (typeof window !== 'undefined') {
            localStorage.removeItem('bisq_chat_messages');
            console.log('Chat history cleared');
        }
    }

    // Common feedback issues
    const feedbackIssues: FeedbackIssue[] = [
        {id: "too_verbose", label: "Answer is too long/verbose"},
        {id: "too_technical", label: "Answer is too technical"},
        {id: "not_specific", label: "Answer is not specific enough"},
        {id: "inaccurate", label: "Information is incorrect"},
        {id: "outdated", label: "Information is outdated"},
        {id: "confusing", label: "Answer is confusing"},
        {id: "incomplete", label: "Answer is incomplete"}
    ];

    // Add this function to handle submitting the feedback explanation
    const submitFeedbackExplanation = async () => {
        if (!feedbackDialog.messageId) return;

        const explanationData = {
            message_id: feedbackDialog.messageId,
            explanation: feedbackText,
            issues: selectedIssues
        };

        try {
            const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
            const apiUrl = process.env.NEXT_PUBLIC_API_URL || `http://${hostname}:8000`;

            const response = await fetch(`${apiUrl}/feedback/explanation`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(explanationData)
            });

            if (!response.ok) {
                console.error(`Failed to submit feedback explanation: Server returned ${response.status}`);
                return;
            }

            try {
                const responseData: ExplanationResponse = await response.json();
                console.log("Feedback explanation response:", responseData);

                // You could use the detected_issues from the response if needed
                if (responseData.detected_issues) {
                    console.log("Server detected these issues:", responseData.detected_issues);
                }
            } catch (parseError) {
                console.error("Error parsing explanation response:", parseError);
            }

            // Reset dialog state
            setFeedbackDialog({
                isOpen: false,
                messageId: null,
                questionText: "",
                answerText: ""
            });
            setFeedbackText("");
            setSelectedIssues([]);

            // Add a thank you message to the chat
            const thankYouMessage: Message = {
                id: generateUUID(),
                content: getRandomThankYouMessage(),
                role: "assistant",
                timestamp: new Date(),
                isThankYouMessage: true
            };
            setMessages(prev => [...prev, thankYouMessage]);

        } catch (error: unknown) {
            console.error("Error submitting feedback explanation:", error);
        }
    }

    return (
        <>
            <PrivacyWarningModal />
            <div className="flex flex-col h-full overflow-hidden">
            {/* Messages container */}
            <div className="flex-1 overflow-hidden">
                <div className="h-full overflow-y-auto" ref={scrollAreaRef}>
                    <div className="mx-auto w-full max-w-2xl px-4">
                        <div className="flex-1 space-y-6 pb-32 pt-4">
                            {messages.length === 0 ? (
                                <div
                                    className="flex h-[calc(100vh-280px)] flex-col items-center justify-center">
                                    <div
                                        className="flex items-center justify-center space-x-3 mb-4">
                                        <Image
                                            src="/bisq-fav.png"
                                            alt="Bisq AI"
                                            width={40}
                                            height={40}
                                            className="rounded"
                                        />
                                        <Plus className="h-5 w-5 text-muted-foreground"/>
                                        <MessageSquare className="h-8 w-8 text-muted-foreground"/>
                                    </div>
                                    <p className="text-lg font-medium mb-2">Welcome to Bisq Support
                                        AI</p>
                                    <p className="text-sm text-muted-foreground text-center max-w-sm mb-8">
                                        Meet your digital dumpster fire of wisdom! Our CPU-powered
                                        chaos takes
                                        about {formattedAvgTime} to answer, but the wait&#39;s worth
                                        it. Picture a
                                        caffeinated gremlin strapped to spare toaster parts, here to
                                        solve your Bisq 2
                                        questions!
                                    </p>
                                </div>
                            ) : (
                                <>
                                    {messages.map((message, index) => (
                                        <div key={index}
                                             className={cn("flex items-start gap-4 px-4", message.role === "user" ? "flex-row-reverse" : "")}>
                                            {message.role === "assistant" ? (
                                                <div
                                                    className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-background shadow">
                                                    <Image
                                                        src="/bisq-fav.png"
                                                        alt="Bisq AI"
                                                        width={24}
                                                        height={24}
                                                        className="rounded"
                                                    />
                                                </div>
                                            ) : (
                                                <div
                                                    className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-accent">
                                                    <UserIcon className="h-4 w-4"/>
                                                </div>
                                            )}
                                            <div
                                                className={cn("flex-1 space-y-2", message.role === "user" ? "text-right" : "")}>
                                                <div
                                                    className="inline-block rounded-lg px-3 py-2 text-sm bg-muted">
                                                    {message.content}
                                                </div>
                                                {message.sources && message.sources.length > 0 && (
                                                    <div className="text-xs text-muted-foreground">
                                                        <div className="flex items-center gap-2">
                                                            <span
                                                                className="text-xs font-medium">Sources:</span>
                                                            {/* Deduplicate sources by type */}
                                                            {Array.from(new Set(message.sources.map(source => source.type))).map((sourceType, index) => (
                                                                <span key={index} className={cn(
                                                                    "px-2 py-1 rounded-md text-xs",
                                                                    sourceType === "wiki" ? "bg-primary/10" : "bg-secondary/50"
                                                                )}>
                                                                    {sourceType === "wiki" ? "Wiki" : "Support Chat"}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    </div>
                                                )}
                                                {message.role === "assistant" && message.id && !message.isThankYouMessage && (
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
                                    <div
                                        className="flex h-8 w-8 shrink-0 select-none items-center justify-center rounded-full bg-background shadow">
                                        <Image
                                            src="/bisq-fav.png"
                                            alt="Bisq AI"
                                            width={24}
                                            height={24}
                                            className="rounded"
                                        />
                                    </div>
                                    <div className="flex-1 space-y-2">
                                        <div
                                            className="inline-flex flex-col rounded-lg px-3 py-2 text-sm bg-muted">
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

            {/* Feedback Dialog */}
            <Dialog open={feedbackDialog.isOpen}
                    onOpenChange={(open) => !open && setFeedbackDialog(prev => ({
                        ...prev,
                        isOpen: false
                    }))}>
                <DialogContent className="sm:max-w-xl border-border/60 shadow-lg">
                    <DialogHeader className="pb-2">
                        <div className="flex items-center gap-2 mb-1">
                            <Image
                                src="/bisq-fav.png"
                                alt="Bisq AI"
                                width={20}
                                height={20}
                                className="rounded"
                            />
                            <DialogTitle>Help us improve</DialogTitle>
                        </div>
                        <DialogDescription className="text-muted-foreground text-sm">
                            What could we improve about this answer?
                        </DialogDescription>
                    </DialogHeader>

                    <div className="grid gap-4 py-4">
                        <div className="grid gap-3">
                            <div className="font-medium text-sm">Common issues:</div>
                            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                {feedbackIssues.map((issue) => (
                                    <div key={issue.id}
                                         className={cn(
                                             "flex items-center space-x-2 rounded-md border p-2 cursor-pointer transition-colors",
                                             selectedIssues.includes(issue.id)
                                                 ? "border-[#25B135]/50 bg-[#25B135]/10"
                                                 : "border-border/60 hover:bg-muted/50"
                                         )}
                                         onClick={() => {
                                             setSelectedIssues(prev =>
                                                 prev.includes(issue.id)
                                                     ? prev.filter(id => id !== issue.id)
                                                     : [...prev, issue.id]
                                             );
                                         }}
                                    >
                                        <Checkbox
                                            id={issue.id}
                                            checked={selectedIssues.includes(issue.id)}
                                            className={cn(
                                                "cursor-pointer",
                                                selectedIssues.includes(issue.id) ? "text-[#25B135] border-[#25B135]" : ""
                                            )}
                                            onClick={(e) => {
                                                // Stop propagation to prevent double toggling
                                                e.stopPropagation();
                                            }}
                                            onCheckedChange={(checked: boolean | "indeterminate") => {
                                                setSelectedIssues(prev =>
                                                    checked === true
                                                        ? [...prev, issue.id]
                                                        : prev.filter(id => id !== issue.id)
                                                );
                                            }}
                                        />
                                        <Label
                                            htmlFor={issue.id}
                                            className="cursor-pointer text-sm font-normal"
                                            onClick={(e) => e.stopPropagation()}
                                        >
                                            {issue.label}
                                        </Label>
                                    </div>
                                ))}
                            </div>
                        </div>

                        <div className="grid gap-2 mt-2">
                            <Label htmlFor="feedback-text" className="text-sm">Tell us more:</Label>
                            <Textarea
                                id="feedback-text"
                                placeholder="Please share any specific issues or suggestions for improvement..."
                                value={feedbackText}
                                onChange={(e) => setFeedbackText(e.target.value)}
                                rows={3}
                                className="resize-none border-border/60 focus:border-[#25B135]/30 focus-visible:ring-[#25B135]/10"
                            />
                        </div>
                    </div>

                    <DialogFooter className="sm:justify-between gap-2">
                        <Button
                            variant="outline"
                            className="border-border/60 text-muted-foreground hover:bg-muted/80"
                            onClick={() => setFeedbackDialog(prev => ({...prev, isOpen: false}))}
                        >
                            Cancel
                        </Button>
                        <Button
                            onClick={submitFeedbackExplanation}
                            disabled={!feedbackText && selectedIssues.length === 0}
                            className={cn(
                                "transition-colors",
                                (feedbackText || selectedIssues.length > 0)
                                    ? "bg-[#25B135] hover:bg-[#25B135]/90 text-white"
                                    : "bg-muted text-muted-foreground"
                            )}
                        >
                            Submit Feedback
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            {/* Input form */}
            <form onSubmit={handleSubmit}
                  className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-background from-50% to-transparent to-100% p-4">
                <div className="mx-auto w-full max-w-2xl px-4">
                    {messages.length === 0 && (
                        <div className="grid grid-cols-2 gap-4 w-full mb-4">
                            {exampleQuestions.map((question, index) => (
                                <button
                                    key={index}
                                    type="button"
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
                            placeholder={isLoading ? "Thinking..." : "Ask about Bisq (never share private keys or personal info)"}
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
                                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground"/>
                            ) : (
                                <Send className={cn(
                                    "h-4 w-4",
                                    input.trim() ? "text-white" : "text-muted-foreground"
                                )}/>
                            )}
                        </Button>
                    </div>
                    {messages.length > 0 && (
                        <div className="flex justify-center mt-3">
                            <button
                                onClick={clearChatHistory}
                                className="text-xs text-muted-foreground/60 hover:text-muted-foreground/90 transition-colors"
                                type="button"
                            >
                                Clear conversation
                            </button>
                        </div>
                    )}
                    <div className="flex justify-center mt-4 pb-4">
                        <Link
                            href="/privacy"
                            className="text-xs text-muted-foreground/60 hover:text-muted-foreground/90 transition-colors"
                        >
                            Privacy Policy
                        </Link>
                    </div>
                </div>
            </form>
        </div>
        </>
    )
}

export {ChatInterface}
