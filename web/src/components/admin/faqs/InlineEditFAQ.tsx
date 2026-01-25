"use client";

import { useState, useEffect, useRef, useMemo, memo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { SimilarFaqsPanel, SimilarFAQItem } from "@/components/admin/SimilarFaqsPanel";
import { Badge } from "@/components/ui/badge";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import {
    Command,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Loader2, ChevronsUpDown, Check, AlertCircle } from "lucide-react";
import { makeAuthenticatedRequest } from "@/lib/auth";
import { API_BASE_URL } from "@/lib/config";
import debounce from "lodash.debounce";
import { cn } from "@/lib/utils";

export interface FAQ {
    id: string;
    question: string;
    answer: string;
    category: string;
    source: string;
    verified: boolean;
    protocol: "multisig_v1" | "bisq_easy" | "musig" | "all";
    created_at?: string;
    updated_at?: string;
    verified_at?: string | null;
}

export interface InlineEditFAQProps {
    faq: FAQ;
    index: number;
    draftEdits: Map<string, Partial<FAQ>>;
    setDraftEdits: React.Dispatch<React.SetStateAction<Map<string, Partial<FAQ>>>>;
    failedFaqIds: Set<string>;
    handleSaveInlineEdit: (faqId: string, updatedFaq: FAQ) => Promise<void>;
    handleCancelEdit: (faqId: string) => void;
    editCategoryComboboxOpen: boolean;
    setEditCategoryComboboxOpen: (open: boolean) => void;
    availableCategories: string[];
    onViewSimilarFaq?: (faqId: number) => void;
}

/**
 * Inline editing component for FAQs.
 * Memoized to prevent re-creation on parent state updates.
 * This fixes the focus jumping issue by maintaining stable component identity.
 */
export const InlineEditFAQ = memo(
    ({
        faq,
        draftEdits,
        setDraftEdits,
        failedFaqIds,
        handleSaveInlineEdit,
        handleCancelEdit,
        editCategoryComboboxOpen,
        setEditCategoryComboboxOpen,
        availableCategories,
        onViewSimilarFaq,
    }: InlineEditFAQProps) => {
        const draft = draftEdits.get(faq.id);
        const currentValues = draft ? { ...faq, ...draft } : faq;
        const [isSubmitting, setIsSubmitting] = useState(false);
        const questionInputRef = useRef<HTMLInputElement>(null);

        // Similarity check state
        const [editSimilarFaqs, setEditSimilarFaqs] = useState<SimilarFAQItem[]>([]);
        const [isCheckingEditSimilar, setIsCheckingEditSimilar] = useState(false);

        // Check if question has changed from original
        const questionChanged = currentValues.question !== faq.question;

        // High similarity warning threshold (85%)
        const hasHighSimilarity = editSimilarFaqs.some((item) => item.similarity >= 0.85);

        // Debounced similarity check function
        const checkSimilarFaqs = useMemo(
            () =>
                debounce(async (question: string) => {
                    // Skip if question is too short or unchanged
                    if (question.length < 10 || question === faq.question) {
                        setEditSimilarFaqs([]);
                        setIsCheckingEditSimilar(false);
                        return;
                    }

                    setIsCheckingEditSimilar(true);
                    try {
                        const response = await makeAuthenticatedRequest(
                            `${API_BASE_URL}/admin/faqs/check-similar`,
                            {
                                method: "POST",
                                headers: { "Content-Type": "application/json" },
                                body: JSON.stringify({
                                    question,
                                    threshold: 0.65,
                                    limit: 5,
                                    exclude_id: faq.id,
                                }),
                            }
                        );
                        if (response.ok) {
                            const data = await response.json();
                            setEditSimilarFaqs(data.similar_faqs || []);
                        }
                    } catch (error) {
                        console.error("Failed to check similar FAQs:", error);
                    } finally {
                        setIsCheckingEditSimilar(false);
                    }
                }, 600),
            [faq.id, faq.question]
        );

        // Cleanup debounce on unmount
        useEffect(() => {
            return () => {
                checkSimilarFaqs.cancel();
            };
        }, [checkSimilarFaqs]);

        // Auto-focus question input when entering edit mode
        useEffect(() => {
            questionInputRef.current?.focus();
        }, []);

        const handleSubmit = async () => {
            setIsSubmitting(true);
            await handleSaveInlineEdit(faq.id, currentValues as FAQ);
            setIsSubmitting(false);
        };

        const updateDraft = (updates: Partial<FAQ>) => {
            setDraftEdits((prev) => new Map(prev).set(faq.id, { ...draft, ...updates }));
        };

        const hasFailed = failedFaqIds.has(faq.id);

        return (
            <Card
                className={cn(
                    "transition-all duration-200",
                    hasFailed && "border-destructive ring-1 ring-destructive"
                )}
            >
                <CardHeader>
                    {hasFailed && (
                        <div className="mb-2">
                            <Badge variant="destructive" className="mb-2">
                                <AlertCircle className="h-3 w-3 mr-1" />
                                Failed to Save
                            </Badge>
                        </div>
                    )}
                    <Input
                        ref={questionInputRef}
                        value={currentValues.question}
                        onChange={(e) => {
                            updateDraft({ question: e.target.value });
                            checkSimilarFaqs(e.target.value);
                        }}
                        onBlur={() => {
                            if (questionChanged) {
                                checkSimilarFaqs(currentValues.question);
                            }
                        }}
                        placeholder="Question"
                        className="text-lg font-semibold"
                    />
                </CardHeader>
                <CardContent className="space-y-4">
                    {/* Similar FAQs panel - appears when similar FAQs are detected */}
                    {(editSimilarFaqs.length > 0 || isCheckingEditSimilar) && (
                        <SimilarFaqsPanel
                            similarFaqs={editSimilarFaqs}
                            isLoading={isCheckingEditSimilar}
                            onViewFaq={onViewSimilarFaq}
                            className="mb-2"
                        />
                    )}

                    <Textarea
                        value={currentValues.answer}
                        onChange={(e) => updateDraft({ answer: e.target.value })}
                        placeholder="Answer"
                        rows={6}
                    />

                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div className="space-y-2">
                            <Label>Category</Label>
                            <Popover
                                open={editCategoryComboboxOpen}
                                onOpenChange={setEditCategoryComboboxOpen}
                            >
                                <PopoverTrigger asChild>
                                    <Button
                                        variant="outline"
                                        role="combobox"
                                        aria-expanded={editCategoryComboboxOpen}
                                        className="w-full justify-between"
                                    >
                                        {currentValues.category || "Select category..."}
                                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                                    </Button>
                                </PopoverTrigger>
                                <PopoverContent className="w-full p-0">
                                    <Command>
                                        <CommandInput
                                            placeholder="Search or type new category..."
                                            value={currentValues.category}
                                            onValueChange={(value) =>
                                                updateDraft({ category: value })
                                            }
                                            onKeyDown={(e) => {
                                                if (e.key === "Enter") {
                                                    // Close popover when Enter is pressed to create new category
                                                    setEditCategoryComboboxOpen(false);
                                                }
                                            }}
                                        />
                                        <CommandList>
                                            <CommandEmpty>
                                                Press Enter to create &quot;{currentValues.category}
                                                &quot;
                                            </CommandEmpty>
                                            {availableCategories.length > 0 && (
                                                <CommandGroup heading="Existing Categories">
                                                    {availableCategories.map((category) => (
                                                        <CommandItem
                                                            key={category}
                                                            value={category}
                                                            onSelect={(currentValue) => {
                                                                updateDraft({
                                                                    category: currentValue,
                                                                });
                                                                setEditCategoryComboboxOpen(false);
                                                            }}
                                                        >
                                                            <Check
                                                                className={cn(
                                                                    "mr-2 h-4 w-4",
                                                                    currentValues.category ===
                                                                        category
                                                                        ? "opacity-100"
                                                                        : "opacity-0"
                                                                )}
                                                            />
                                                            {category}
                                                        </CommandItem>
                                                    ))}
                                                </CommandGroup>
                                            )}
                                        </CommandList>
                                    </Command>
                                </PopoverContent>
                            </Popover>
                        </div>

                        <div className="space-y-2">
                            <Label>Source</Label>
                            <Input value={currentValues.source} disabled />
                        </div>

                        <div className="space-y-2">
                            <Label>Protocol</Label>
                            <Select
                                value={currentValues.protocol || "bisq_easy"}
                                onValueChange={(value) =>
                                    updateDraft({
                                        protocol: value as
                                            | "multisig_v1"
                                            | "bisq_easy"
                                            | "musig"
                                            | "all",
                                    })
                                }
                            >
                                <SelectTrigger>
                                    <SelectValue placeholder="Select protocol" />
                                </SelectTrigger>
                                <SelectContent>
                                    <SelectItem value="bisq_easy">
                                        Bisq Easy (Default)
                                    </SelectItem>
                                    <SelectItem value="multisig_v1">
                                        Bisq 1 (Multisig)
                                    </SelectItem>
                                    <SelectItem value="musig">MuSig</SelectItem>
                                    <SelectItem value="all">
                                        General (All Protocols)
                                    </SelectItem>
                                </SelectContent>
                            </Select>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <Button
                            onClick={handleSubmit}
                            disabled={isSubmitting}
                            variant={hasHighSimilarity ? "destructive" : "default"}
                            className={cn(
                                "min-w-[80px]",
                                hasHighSimilarity && "bg-amber-500 hover:bg-amber-600 text-white"
                            )}
                        >
                            {isSubmitting ? (
                                <>
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    Saving
                                </>
                            ) : hasHighSimilarity ? (
                                <>
                                    <AlertCircle className="mr-2 h-4 w-4" />
                                    Save Anyway
                                </>
                            ) : (
                                "Save"
                            )}
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => handleCancelEdit(faq.id)}
                            disabled={isSubmitting}
                        >
                            Cancel
                        </Button>
                        {hasHighSimilarity && (
                            <span className="text-xs text-amber-600 dark:text-amber-400">
                                Similar FAQ detected
                            </span>
                        )}
                    </div>
                </CardContent>
            </Card>
        );
    }
);

InlineEditFAQ.displayName = "InlineEditFAQ";
