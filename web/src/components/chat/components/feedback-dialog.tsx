/**
 * Feedback dialog component for collecting detailed feedback
 */

import Image from "next/image"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog"
import { cn } from "@/lib/utils"
import type { FeedbackDialogState, FeedbackIssue } from "../types/chat.types"

// Common feedback issues
const feedbackIssues: FeedbackIssue[] = [
    { id: "too_verbose", label: "Answer is too long/verbose" },
    { id: "too_technical", label: "Answer is too technical" },
    { id: "not_specific", label: "Answer is not specific enough" },
    { id: "inaccurate", label: "Information is incorrect" },
    { id: "outdated", label: "Information is outdated" },
    { id: "confusing", label: "Answer is confusing" },
    { id: "incomplete", label: "Answer is incomplete" }
]

interface FeedbackDialogProps {
    dialogState: FeedbackDialogState
    feedbackText: string
    selectedIssues: string[]
    onOpenChange: (open: boolean) => void
    onFeedbackTextChange: (text: string) => void
    onIssueToggle: (issueId: string) => void
    onSubmit: () => void
}

export const FeedbackDialog = ({
    dialogState,
    feedbackText,
    selectedIssues,
    onOpenChange,
    onFeedbackTextChange,
    onIssueToggle,
    onSubmit
}: FeedbackDialogProps) => {
    return (
        <Dialog open={dialogState.isOpen} onOpenChange={onOpenChange}>
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
                                <div
                                    key={issue.id}
                                    className={cn(
                                        "flex items-center space-x-2 rounded-md border p-2 cursor-pointer transition-colors",
                                        selectedIssues.includes(issue.id)
                                            ? "border-[#25B135]/50 bg-[#25B135]/10"
                                            : "border-border/60 hover:bg-muted/50"
                                    )}
                                    onClick={() => onIssueToggle(issue.id)}
                                >
                                    <Checkbox
                                        id={issue.id}
                                        checked={selectedIssues.includes(issue.id)}
                                        className={cn(
                                            "cursor-pointer",
                                            selectedIssues.includes(issue.id) ? "text-[#25B135] border-[#25B135]" : ""
                                        )}
                                        onClick={(e) => e.stopPropagation()}
                                        onCheckedChange={(checked: boolean | "indeterminate") => {
                                            if (checked === true) {
                                                onIssueToggle(issue.id)
                                            } else if (checked === false) {
                                                onIssueToggle(issue.id)
                                            }
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
                            onChange={(e) => onFeedbackTextChange(e.target.value)}
                            rows={3}
                            className="resize-none border-border/60 focus:border-[#25B135]/30 focus-visible:ring-[#25B135]/10"
                        />
                    </div>
                </div>

                <DialogFooter className="sm:justify-between gap-2">
                    <Button
                        variant="outline"
                        className="border-border/60 text-muted-foreground hover:bg-muted/80"
                        onClick={() => onOpenChange(false)}
                    >
                        Cancel
                    </Button>
                    <Button
                        onClick={onSubmit}
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
    )
}
