/**
 * Chat input component with example questions and privacy link
 */

import { useRef } from "react"
import Link from "next/link"
import { Loader2, Send } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

// Example questions that can be clicked - showcasing Bisq 1, Bisq 2, and different protocols
const exampleQuestions = [
    "What is Bisq Easy and how does it work?",
    "How does the multisig escrow work in Bisq 1?",
    "What are the main differences between Bisq 1 and Bisq 2?",
    "How does the reputation system protect buyers in Bisq 2?"
]

interface ChatInputProps {
    input: string
    isLoading: boolean
    hasMessages: boolean
    onInputChange: (value: string) => void
    onSubmit: (e: React.FormEvent<HTMLFormElement>) => void
    onQuestionClick: (question: string) => void
    onClearHistory: () => void
}

export const ChatInput = ({
    input,
    isLoading,
    hasMessages,
    onInputChange,
    onSubmit,
    onQuestionClick,
    onClearHistory
}: ChatInputProps) => {
    const inputRef = useRef<HTMLInputElement>(null)

    return (
        <form
            onSubmit={onSubmit}
            className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-background from-50% to-transparent to-100% p-4"
        >
            <div className="mx-auto w-full max-w-2xl px-4">
                {!hasMessages && (
                    <div className="grid grid-cols-2 gap-4 w-full mb-4">
                        {exampleQuestions.map((question) => (
                            <button
                                key={question}
                                type="button"
                                aria-label={`Ask example question: ${question}`}
                                onClick={() => onQuestionClick(question)}
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
                        onChange={(e) => onInputChange(e.target.value)}
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
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        ) : (
                            <Send className={cn(
                                "h-4 w-4",
                                input.trim() ? "text-white" : "text-muted-foreground"
                            )} />
                        )}
                    </Button>
                </div>
                {hasMessages && (
                    <div className="flex justify-center mt-3">
                        <button
                            onClick={onClearHistory}
                            className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                            type="button"
                        >
                            Clear conversation
                        </button>
                    </div>
                )}
                <div className="flex justify-center gap-4 mt-4 pb-4">
                    <Link
                        href="/terms"
                        className="text-xs text-muted-foreground/60 hover:text-muted-foreground/90 transition-colors"
                    >
                        Terms of Service
                    </Link>
                    <span className="text-xs text-muted-foreground/40">|</span>
                    <Link
                        href="/privacy"
                        className="text-xs text-muted-foreground/60 hover:text-muted-foreground/90 transition-colors"
                    >
                        Privacy Policy
                    </Link>
                    <span className="text-xs text-muted-foreground/40">|</span>
                    <Link
                        href="/faq"
                        className="text-xs text-muted-foreground/60 hover:text-muted-foreground/90 transition-colors"
                    >
                        Browse FAQs
                    </Link>
                </div>
            </div>
        </form>
    )
}
