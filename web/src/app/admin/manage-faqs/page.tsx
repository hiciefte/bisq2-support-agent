"use client";

import { useState, useEffect, useRef, FormEvent, useMemo, memo, useCallback } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { VectorStoreStatusBanner } from "@/components/admin/VectorStoreStatusBanner";
import { SimilarFaqsPanel, SimilarFAQItem } from "@/components/admin/SimilarFaqsPanel";
import {
    SimilarFaqReviewQueue,
    SimilarFaqCandidate,
} from "@/components/admin/SimilarFaqReviewQueue";
import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
    Pencil,
    Trash2,
    Loader2,
    PlusCircle,
    Filter,
    X,
    Search,
    RotateCcw,
    BadgeCheck,
    ChevronRight,
    AlertCircle,
    CheckSquare,
    ChevronsUpDown,
    Check,
    FileQuestion,
    MoreVertical,
    Download,
    Clock,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Skeleton } from "@/components/ui/skeleton";
import {
    Command,
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
    CommandShortcut,
} from "@/components/ui/command";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetFooter,
    SheetHeader,
    SheetTitle,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DatePicker } from "@/components/ui/date-picker";
import { makeAuthenticatedRequest } from "@/lib/auth";
import { API_BASE_URL } from "@/lib/config";
import debounce from "lodash.debounce";
import { format, startOfDay, endOfDay } from "date-fns";
import { useToast } from "@/hooks/use-toast";
import { toast as sonnerToast } from "sonner";
import { useHotkeys } from "react-hotkeys-hook";
import { cn } from "@/lib/utils";

interface FAQ {
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

interface FAQListResponse {
    faqs: FAQ[];
    total_count: number;
    page: number;
    page_size: number;
    total_pages: number;
}

interface InlineEditFAQProps {
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

// Extracted InlineEditFAQ component to prevent re-creation on parent state updates
// This fixes the focus jumping issue by maintaining stable component identity
const InlineEditFAQ = memo(
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

// Helper function to format dates for display
const formatTimestamp = (timestamp?: string | null): string => {
    if (!timestamp) return "N/A";
    try {
        const date = new Date(timestamp);
        return new Intl.DateTimeFormat("en-US", {
            year: "numeric",
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
            timeZone: "UTC",
            timeZoneName: "short",
        }).format(date);
    } catch {
        return "Invalid date";
    }
};

// Helper function to serialize dates for API requests
const serializeDateFilter = (date: Date | undefined, toEndOfDay: boolean = false): string | null => {
    if (!date) return null;
    // Use startOfDay/endOfDay to preserve the full local day and convert to proper UTC instants
    const localBoundary = toEndOfDay ? endOfDay(date) : startOfDay(date);
    return localBoundary.toISOString();
};

export default function ManageFaqsPage() {
    const { toast } = useToast();
    const [faqData, setFaqData] = useState<FAQListResponse | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isFormOpen, setIsFormOpen] = useState(false);
    const [formData, setFormData] = useState({
        question: "",
        answer: "",
        category: "",
        source: "Manual",
        protocol: "bisq_easy" as "multisig_v1" | "bisq_easy" | "musig" | "all",
    });
    const [error, setError] = useState<string | null>(null);
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize] = useState(10);

    // Filter state
    const [showFilters, setShowFilters] = useState(false);
    const [filters, setFilters] = useState({
        search_text: "",
        categories: [] as string[],
        source: "",
        verified: "all" as "all" | "verified" | "unverified",
        protocol: "",
        verified_from: undefined as Date | undefined,
        verified_to: undefined as Date | undefined,
    });

    // Available categories and sources from the data
    const [availableCategories, setAvailableCategories] = useState<string[]>([]);
    const [availableSources, setAvailableSources] = useState<string[]>([]);

    // "Do not show again" state for verify FAQ confirmation
    const [skipVerifyConfirmation, setSkipVerifyConfirmation] = useState(false);
    const [doNotShowAgain, setDoNotShowAgain] = useState(false);

    // Delete confirmation dialog state (for keyboard shortcut integration)
    const [showDeleteConfirmDialog, setShowDeleteConfirmDialog] = useState(false);
    const [faqToDelete, setFaqToDelete] = useState<FAQ | null>(null);

    // Collapsible state - track which FAQs are manually expanded
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

    // Bulk selection state
    const [bulkSelectionMode, setBulkSelectionMode] = useState(false);
    const [selectedFaqIds, setSelectedFaqIds] = useState<Set<string>>(new Set());

    // Command Palette state
    const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

    // Keyboard navigation state
    const [selectedIndex, setSelectedIndex] = useState<number>(-1);

    // Category combobox state
    const [categoryComboboxOpen, setCategoryComboboxOpen] = useState(false);
    const [editCategoryComboboxOpen, setEditCategoryComboboxOpen] = useState(false);

    // Similar FAQ check state
    const [similarFaqs, setSimilarFaqs] = useState<SimilarFAQItem[]>([]);
    const [isCheckingSimilar, setIsCheckingSimilar] = useState(false);

    // Similar FAQ review queue state (Phase 7)
    const [pendingReviewItems, setPendingReviewItems] = useState<SimilarFaqCandidate[]>([]);
    const [isLoadingPendingReview, setIsLoadingPendingReview] = useState(true);

    // Inline editing state
    const [editingFaqId, setEditingFaqId] = useState<string | null>(null);
    const [draftEdits, setDraftEdits] = useState<Map<string, Partial<FAQ>>>(new Map());
    const [failedFaqIds, setFailedFaqIds] = useState<Set<string>>(new Set());

    const currentPageRef = useRef(currentPage);
    const previousDataHashRef = useRef<string>("");
    const savedScrollPositionRef = useRef<number | null>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);
    const faqRefs = useRef<Map<string, HTMLDivElement>>(new Map());

    // React 19 compatible ref callback - memoized to avoid re-creation
    const setFaqRef = useCallback((faqId: string) => {
        return (el: HTMLDivElement | null) => {
            if (el) {
                faqRefs.current.set(faqId, el);
            } else {
                faqRefs.current.delete(faqId);
            }
        };
    }, []);

    // Server-side search handles all filtering - no client-side filtering needed
    const displayFaqs = faqData;

    // Keep the ref in sync with the latest page
    useEffect(() => {
        currentPageRef.current = currentPage;
    }, [currentPage]);

    // Restore scroll position after background refresh if it was saved
    useEffect(() => {
        if (savedScrollPositionRef.current !== null) {
            window.scrollTo(0, savedScrollPositionRef.current);
            savedScrollPositionRef.current = null;
        }
    }, [faqData, availableCategories, availableSources]);

    useEffect(() => {
        // Since we're wrapped with SecureAuth, we know we're authenticated
        fetchFaqs();

        // Load "do not show again" preference from localStorage
        try {
            const skipConfirmation = localStorage.getItem("skipVerifyFaqConfirmation");
            if (skipConfirmation === "true") setSkipVerifyConfirmation(true);
        } catch {
            // ignore storage errors; default is to show confirmation
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Re-fetch data when filters change (NO interval here - that's separate)
    useEffect(() => {
        setCurrentPage(1); // Reset to first page when filters change
        fetchFaqs(1);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filters]);

    // Keyboard shortcuts using react-hotkeys-hook
    // Command palette (works everywhere)
    useHotkeys(
        "mod+k",
        (e) => {
            e.preventDefault();
            setCommandPaletteOpen(true);
        },
        { enableOnFormTags: true }
    );

    // Focus search
    useHotkeys(
        "/",
        (e) => {
            e.preventDefault();
            searchInputRef.current?.focus();
        },
        { enableOnFormTags: false }
    );

    // Navigate down (j key)
    useHotkeys(
        "j",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && displayFaqs?.faqs.length) {
                setSelectedIndex((prev) =>
                    prev < (displayFaqs?.faqs.length || 0) - 1 ? prev + 1 : prev
                );
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, displayFaqs]
    );

    // Navigate up (k key)
    useHotkeys(
        "k",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && displayFaqs?.faqs.length) {
                setSelectedIndex((prev) => (prev > 0 ? prev - 1 : prev === -1 ? 0 : prev));
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, displayFaqs]
    );

    // Set protocol to Bisq Easy (e key) - replaces old edit mode shortcut
    useHotkeys(
        "e",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                handleSetProtocol(selectedFaq, "bisq_easy");
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, selectedIndex, displayFaqs]
    );

    // Set protocol to Multisig v1 (1 key) - US-003
    useHotkeys(
        "1",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                handleSetProtocol(selectedFaq, "multisig_v1");
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, selectedIndex, displayFaqs]
    );

    // Set protocol to MuSig (m key) - US-003
    useHotkeys(
        "m",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                handleSetProtocol(selectedFaq, "musig");
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, selectedIndex, displayFaqs]
    );

    // Set protocol to All (0 key) - US-003
    useHotkeys(
        "0",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                handleSetProtocol(selectedFaq, "all");
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, selectedIndex, displayFaqs]
    );

    // Exit edit mode or other escape actions
    useHotkeys(
        "escape",
        () => {
            if (editingFaqId) {
                const faq = displayFaqs?.faqs.find((f) => f.id === editingFaqId);
                if (faq) {
                    handleCancelEdit(faq.id);
                }
            } else if (bulkSelectionMode) {
                setBulkSelectionMode(false);
                setSelectedFaqIds(new Set());
            } else if (isFormOpen) {
                setIsFormOpen(false);
            } else if (selectedIndex >= 0) {
                setSelectedIndex(-1);
            }
        },
        { enableOnFormTags: true },
        [editingFaqId, bulkSelectionMode, isFormOpen, selectedIndex, displayFaqs]
    );

    // Enter edit mode (Enter key) - US-006
    useHotkeys(
        "enter",
        (e) => {
            if (!editingFaqId && selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                e.preventDefault();
                enterEditMode(displayFaqs.faqs[selectedIndex]);
            }
        },
        { enableOnFormTags: false },
        [editingFaqId, selectedIndex, displayFaqs]
    );

    // Delete FAQ (d key)
    // In bulk mode: delete all selected FAQs
    // In normal mode: show confirmation dialog before deleting single FAQ
    useHotkeys(
        "d",
        (e) => {
            e.preventDefault();
            if (bulkSelectionMode && selectedFaqIds.size > 0) {
                // Bulk mode: delete all selected FAQs (already has its own confirmation)
                handleBulkDelete();
            } else if (selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                // Normal mode: show confirmation dialog before deleting
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                setFaqToDelete(selectedFaq);
                setShowDeleteConfirmDialog(true);
            }
        },
        { enableOnFormTags: false },
        [selectedIndex, displayFaqs, bulkSelectionMode, selectedFaqIds]
    );

    // Verify FAQ (v key)
    // In bulk mode: verify all selected FAQs
    // In normal mode: verify single FAQ (respects confirmation dialog setting)
    useHotkeys(
        "v",
        (e) => {
            e.preventDefault();
            if (bulkSelectionMode && selectedFaqIds.size > 0) {
                // Bulk mode: verify all selected FAQs
                handleBulkVerify();
            } else if (selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                // Normal mode: verify single FAQ
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                if (!selectedFaq.verified) {
                    // Directly verify if user has opted out of confirmation, otherwise rely on button click
                    if (skipVerifyConfirmation) {
                        handleVerifyFaq(selectedFaq);
                    } else {
                        // Trigger the verify button click to show confirmation dialog
                        const verifyButton = document.querySelector(
                            `button[aria-label="Verify FAQ: ${selectedFaq.question}"]`
                        ) as HTMLButtonElement;
                        if (verifyButton) {
                            verifyButton.click();
                        }
                    }
                }
            }
        },
        { enableOnFormTags: false },
        [selectedIndex, displayFaqs, bulkSelectionMode, selectedFaqIds, skipVerifyConfirmation]
    );

    // New FAQ (n key)
    useHotkeys(
        "n",
        (e) => {
            e.preventDefault();
            openNewFaqForm();
        },
        { enableOnFormTags: false }
    );

    // Bulk selection mode (b key)
    useHotkeys(
        "b",
        (e) => {
            e.preventDefault();
            setBulkSelectionMode(!bulkSelectionMode);
            if (bulkSelectionMode) {
                setSelectedFaqIds(new Set());
            }
        },
        { enableOnFormTags: false },
        [bulkSelectionMode]
    );

    // Select all FAQs (a key) - only works in bulk selection mode
    useHotkeys(
        "a",
        (e) => {
            if (bulkSelectionMode && displayFaqs?.faqs.length) {
                e.preventDefault();
                // Select all current page FAQs
                const allIds = new Set(displayFaqs.faqs.map((faq) => faq.id));
                setSelectedFaqIds(allIds);

                toast({
                    title: "All FAQs Selected",
                    description: `Selected all ${allIds.size} FAQ${allIds.size > 1 ? "s" : ""} on this page`,
                });
            }
        },
        { enableOnFormTags: false },
        [bulkSelectionMode, displayFaqs]
    );

    // Scroll selected FAQ into view when selection changes
    useEffect(() => {
        if (selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
            const selectedFaq = displayFaqs.faqs[selectedIndex];
            const element = faqRefs.current.get(selectedFaq.id);
            if (element) {
                element.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                });
            }
        }
    }, [selectedIndex, displayFaqs]);

    // Reset selected index when FAQ data changes (pagination, filtering, etc.)
    useEffect(() => {
        setSelectedIndex(-1);
    }, [currentPage, filters]);

    const fetchFaqs = useCallback(
        async (page = 1, isBackgroundRefresh = false) => {
            // Save scroll position for background refreshes
            if (isBackgroundRefresh) {
                savedScrollPositionRef.current = window.scrollY;
            }

            // Only show loading spinner if not a background refresh
            if (!isBackgroundRefresh) {
                setIsLoading(true);
            }

            try {
                // Build query parameters
                const params = new URLSearchParams({
                    page: page.toString(),
                    page_size: pageSize.toString(),
                });

                if (filters.search_text && filters.search_text.trim()) {
                    params.append("search_text", filters.search_text.trim());
                }

                if (filters.categories.length > 0) {
                    params.append("categories", filters.categories.join(","));
                }

                if (filters.source) {
                    params.append("source", filters.source);
                }

                if (filters.verified && filters.verified !== "all") {
                    params.append("verified", filters.verified === "verified" ? "true" : "false");
                }

                if (filters.protocol && filters.protocol.trim()) {
                    params.append("protocol", filters.protocol.trim());
                }

                if (filters.verified_from) {
                    const serialized = serializeDateFilter(filters.verified_from, false);
                    if (serialized) params.append("verified_from", serialized);
                }

                if (filters.verified_to) {
                    const serialized = serializeDateFilter(filters.verified_to, true);
                    if (serialized) params.append("verified_to", serialized);
                }

                const response = await makeAuthenticatedRequest(`/admin/faqs?${params.toString()}`);
                if (response.ok) {
                    const data = await response.json();

                    // Clear error on successful response (regardless of whether data changed)
                    setError(null);

                    // Calculate hash of new data for comparison
                    const dataHash = JSON.stringify(data);

                    // Only update state if data has actually changed
                    if (dataHash !== previousDataHashRef.current) {
                        previousDataHashRef.current = dataHash;
                        setFaqData(data);

                        // Extract unique categories and sources ONLY if no filters are active
                        // This prevents the category list from disappearing when a category filter is applied
                        if (data.faqs && !hasActiveFilters) {
                            const categories = [
                                ...new Set(
                                    data.faqs.map((faq: FAQ) => faq.category).filter(Boolean)
                                ),
                            ] as string[];
                            const sources = [
                                ...new Set(data.faqs.map((faq: FAQ) => faq.source).filter(Boolean)),
                            ] as string[];
                            setAvailableCategories(categories);
                            setAvailableSources(sources);
                        }
                    }
                } else {
                    const errorText = `Failed to fetch FAQs. Status: ${response.status}`;
                    console.error(errorText);
                    setError(errorText);
                    if (response.status === 401 || response.status === 403) {
                        // Let SecureAuth handle authentication errors
                        window.location.reload();
                    }
                }
            } catch (error) {
                const errorText = "An unexpected error occurred while fetching FAQs.";
                console.error(errorText, error);
                setError(errorText);
            } finally {
                if (!isBackgroundRefresh) {
                    setIsLoading(false);
                }
            }
        },
        [filters, pageSize]
    ); // Dependencies: filters and pageSize are read inside fetchFaqs

    // Auto-refresh interval - must be AFTER fetchFaqs definition
    useEffect(() => {
        const intervalId = setInterval(() => {
            // Use current page from ref, and pass true for background refresh
            // The fetchFaqs function will use the current filters state
            fetchFaqs(currentPageRef.current, true);
        }, 30000);

        // Cleanup interval on unmount
        return () => clearInterval(intervalId);
    }, [fetchFaqs]); // Include fetchFaqs so interval uses latest version with current filters

    // Fetch pending similar FAQ review items (Phase 7)
    const fetchPendingReviewItems = useCallback(async () => {
        try {
            const response = await makeAuthenticatedRequest("/admin/similar-faqs/pending");
            if (response.ok) {
                const data = await response.json();
                setPendingReviewItems(data.items || []);
            } else {
                console.error("Failed to fetch pending review items:", response.status);
            }
        } catch (error) {
            console.error("Error fetching pending review items:", error);
        } finally {
            setIsLoadingPendingReview(false);
        }
    }, []);

    // Fetch pending review items on mount and poll every 30s
    useEffect(() => {
        fetchPendingReviewItems();
        const intervalId = setInterval(fetchPendingReviewItems, 30000);
        return () => clearInterval(intervalId);
    }, [fetchPendingReviewItems]);

    // Similar FAQ review queue action handlers (Phase 7)
    const handleApproveReviewItem = useCallback(
        async (id: string) => {
            // Optimistic UI update
            setPendingReviewItems((prev) => prev.filter((item) => item.id !== id));
            try {
                const response = await makeAuthenticatedRequest(
                    `/admin/similar-faqs/${id}/approve`,
                    { method: "POST" }
                );
                if (response.ok) {
                    toast({
                        title: "FAQ approved",
                        description: "The FAQ has been added to the knowledge base.",
                    });
                    // Refresh FAQ list to show the new FAQ
                    await fetchFaqs(currentPage);
                } else {
                    // Rollback on error
                    await fetchPendingReviewItems();
                    toast({
                        title: "Failed to approve",
                        description: "An error occurred while approving the FAQ.",
                        variant: "destructive",
                    });
                }
            } catch {
                // Rollback on error
                await fetchPendingReviewItems();
                toast({
                    title: "Failed to approve",
                    description: "An error occurred while approving the FAQ.",
                    variant: "destructive",
                });
            }
        },
        [fetchFaqs, fetchPendingReviewItems, toast, currentPage]
    );

    const handleMergeReviewItem = useCallback(
        async (id: string, mode: "replace" | "append") => {
            // Optimistic UI update
            setPendingReviewItems((prev) => prev.filter((item) => item.id !== id));
            try {
                const response = await makeAuthenticatedRequest(
                    `/admin/similar-faqs/${id}/merge`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ mode }),
                    }
                );
                if (response.ok) {
                    toast({
                        title: "FAQ merged",
                        description:
                            mode === "replace"
                                ? "The existing FAQ has been replaced."
                                : "The content has been appended to the existing FAQ.",
                    });
                    // Refresh FAQ list to show the updated FAQ
                    await fetchFaqs(currentPage);
                } else {
                    // Rollback on error
                    await fetchPendingReviewItems();
                    toast({
                        title: "Failed to merge",
                        description: "An error occurred while merging the FAQ.",
                        variant: "destructive",
                    });
                }
            } catch {
                // Rollback on error
                await fetchPendingReviewItems();
                toast({
                    title: "Failed to merge",
                    description: "An error occurred while merging the FAQ.",
                    variant: "destructive",
                });
            }
        },
        [fetchFaqs, fetchPendingReviewItems, toast, currentPage]
    );

    const handleDismissReviewItem = useCallback(
        async (id: string, reason?: string) => {
            // Optimistic UI update
            setPendingReviewItems((prev) => prev.filter((item) => item.id !== id));
            try {
                const response = await makeAuthenticatedRequest(
                    `/admin/similar-faqs/${id}/dismiss`,
                    {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ reason }),
                    }
                );
                if (response.ok) {
                    toast({
                        title: "FAQ dismissed",
                        description: "The candidate has been removed from the review queue.",
                    });
                } else {
                    // Rollback on error
                    await fetchPendingReviewItems();
                    toast({
                        title: "Failed to dismiss",
                        description: "An error occurred while dismissing the FAQ.",
                        variant: "destructive",
                    });
                }
            } catch {
                // Rollback on error
                await fetchPendingReviewItems();
                toast({
                    title: "Failed to dismiss",
                    description: "An error occurred while dismissing the FAQ.",
                    variant: "destructive",
                });
            }
        },
        [fetchPendingReviewItems, toast]
    );

    const handleFormSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setIsSubmitting(true);
        const endpoint = `/admin/faqs`;
        const method = "POST";

        try {
            const response = await makeAuthenticatedRequest(endpoint, {
                method,
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify(formData),
            });

            if (response.ok) {
                await fetchFaqs(currentPage);
                setIsFormOpen(false);
                setFormData({
                    question: "",
                    answer: "",
                    category: "",
                    source: "Manual",
                    protocol: "bisq_easy",
                });
                setError(null);
            } else {
                const errorText = `Failed to save FAQ. Status: ${response.status}`;
                console.error(errorText);
                setError(errorText);
            }
        } catch (error) {
            const errorText = "An unexpected error occurred while saving the FAQ.";
            console.error(errorText, error);
            setError(errorText);
        } finally {
            setIsSubmitting(false);
        }
    };

    /**
     * Check for similar FAQs using semantic similarity.
     * Debounced to avoid excessive API calls.
     */
    const checkSimilarFaqs = useCallback(
        debounce(async (question: string, excludeId?: string) => {
            // Skip if question is too short
            if (!question || question.trim().length < 5) {
                setSimilarFaqs([]);
                return;
            }

            setIsCheckingSimilar(true);
            try {
                const response = await makeAuthenticatedRequest("/admin/faqs/check-similar", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                    },
                    body: JSON.stringify({
                        question: question.trim(),
                        threshold: 0.65,
                        limit: 5,
                        exclude_id: excludeId ? parseInt(excludeId, 10) : null,
                    }),
                });

                if (response.ok) {
                    const data = await response.json();
                    setSimilarFaqs(data.similar_faqs || []);
                } else {
                    // Graceful degradation - don't show error, just clear similar FAQs
                    console.warn("Failed to check similar FAQs:", response.status);
                    setSimilarFaqs([]);
                }
            } catch (error) {
                // Graceful degradation
                console.warn("Error checking similar FAQs:", error);
                setSimilarFaqs([]);
            } finally {
                setIsCheckingSimilar(false);
            }
        }, 400),
        []
    );

    /**
     * Handle question input blur - triggers similar FAQ check.
     */
    const handleQuestionBlur = useCallback(() => {
        checkSimilarFaqs(formData.question);
    }, [formData.question, checkSimilarFaqs]);

    /**
     * Handle "View FAQ" click - scroll to the FAQ or open in new context.
     */
    const handleViewSimilarFaq = useCallback((faqId: number) => {
        // Find the FAQ in current data and scroll to it
        const faqIndex = displayFaqs?.faqs.findIndex((f) => f.id === String(faqId));
        if (faqIndex !== undefined && faqIndex >= 0) {
            // Close the form sheet to show the FAQ list
            setIsFormOpen(false);
            // Set selection to the found FAQ
            setSelectedIndex(faqIndex);
            // Expand it for visibility
            setExpandedIds((prev) => new Set(prev).add(String(faqId)));
            // Scroll to it after a brief delay for the sheet to close
            setTimeout(() => {
                const faqElement = faqRefs.current.get(String(faqId));
                faqElement?.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 300);
        } else {
            // FAQ not on current page - notify user
            toast({
                title: "FAQ Not On This Page",
                description: `FAQ #${faqId} may be on a different page. Try searching for it.`,
            });
        }
    }, [displayFaqs, toast]);

    /**
     * Handle "View FAQ" click from inline edit - scroll to the FAQ without closing editor.
     * This allows the user to see the similar FAQ while still editing.
     */
    const handleViewSimilarFaqFromEdit = useCallback((faqId: number) => {
        // Find the FAQ in current data and scroll to it
        const faqIndex = displayFaqs?.faqs.findIndex((f) => f.id === String(faqId));
        if (faqIndex !== undefined && faqIndex >= 0) {
            // Expand it for visibility if collapsed
            setExpandedIds((prev) => new Set(prev).add(String(faqId)));
            // Scroll to it smoothly
            setTimeout(() => {
                const faqElement = faqRefs.current.get(String(faqId));
                faqElement?.scrollIntoView({ behavior: "smooth", block: "center" });
            }, 100);
        } else {
            // FAQ not on current page - notify user
            toast({
                title: "FAQ Not On This Page",
                description: `FAQ #${faqId} may be on a different page. Try searching for it.`,
            });
        }
    }, [displayFaqs, toast]);

    // Reset similar FAQs when form closes
    useEffect(() => {
        if (!isFormOpen) {
            setSimilarFaqs([]);
            setIsCheckingSimilar(false);
        }
    }, [isFormOpen]);

    const handleDelete = async (id: string) => {
        // Store original data for rollback
        const originalFaqData = faqData;

        // Optimistic UI update - remove immediately
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.filter((f) => f.id !== id),
                total_count: prev.total_count - 1,
            };
        });

        setIsSubmitting(true);
        try {
            const response = await makeAuthenticatedRequest(`/admin/faqs/${id}`, {
                method: "DELETE",
            });

            if (response.ok) {
                // Success - optimistic update already applied, no need to refetch
                // The FAQ is already removed from the UI, maintaining scroll position
                setError(null);
                toast({
                    title: "FAQ Deleted",
                    description: "The FAQ has been successfully deleted.",
                });
            } else {
                // Rollback on error
                setFaqData(originalFaqData);
                const errorText = `Failed to delete FAQ. Status: ${response.status}`;
                console.error(errorText);
                setError(errorText);
                toast({
                    title: "Delete Failed",
                    description: errorText,
                    variant: "destructive",
                });
            }
        } catch (error) {
            // Rollback on error
            setFaqData(originalFaqData);
            const errorText = "An unexpected error occurred while deleting the FAQ.";
            console.error(errorText, error);
            setError(errorText);
            toast({
                title: "Delete Failed",
                description: errorText,
                variant: "destructive",
            });
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleDeleteWithSmartSelection = async (deletionIndex: number) => {
        if (!displayFaqs || deletionIndex < 0 || deletionIndex >= displayFaqs.faqs.length) {
            return;
        }

        const faqToDelete = displayFaqs.faqs[deletionIndex];
        const totalFaqs = displayFaqs.faqs.length;

        // Calculate new selection index BEFORE deletion
        // Design principle: Spatial Consistency - keep focus near where it was
        let newSelectedIndex = -1;
        if (totalFaqs === 1) {
            // Deleting the only FAQ - clear selection
            newSelectedIndex = -1;
        } else if (deletionIndex === totalFaqs - 1) {
            // Deleting the last FAQ - select the new last (previous FAQ)
            newSelectedIndex = deletionIndex - 1;
        } else {
            // Deleting any other FAQ - keep same index (which becomes the next FAQ)
            newSelectedIndex = deletionIndex;
        }

        // Store original selection for rollback
        const originalSelectedIndex = selectedIndex;

        // Update selection immediately for instant feedback
        // Design principle: Feedback Immediacy - <100ms response
        setSelectedIndex(newSelectedIndex);

        // Call existing delete function
        const originalFaqData = faqData;
        await (async () => {
            // Optimistic UI update - remove immediately
            // Design principle: Feedback Immediacy - <100ms response
            setFaqData((prev) => {
                if (!prev) return prev;
                return {
                    ...prev,
                    faqs: prev.faqs.filter((f) => f.id !== faqToDelete.id),
                    total_count: prev.total_count - 1,
                };
            });

            try {
                const response = await makeAuthenticatedRequest(`/admin/faqs/${faqToDelete.id}`, {
                    method: "DELETE",
                });

                if (response.ok) {
                    // Success - wait for delete animation to complete before fetching new FAQ
                    setError(null);

                    // Wait for delete animation to complete (400ms) before fetching
                    await new Promise((resolve) => setTimeout(resolve, 400));

                    // Smart fetch: Get current page data and merge only NEW FAQs to avoid re-animations
                    try {
                        const params = new URLSearchParams({
                            page: currentPage.toString(),
                            page_size: "10",
                        });

                        // Add filters if they exist (matching fetchFaqs logic)
                        if (filters.search_text && filters.search_text.trim()) {
                            params.append("search_text", filters.search_text.trim());
                        }
                        if (filters.categories.length > 0) {
                            params.append("categories", filters.categories.join(","));
                        }
                        if (filters.source) {
                            params.append("source", filters.source);
                        }
                        if (filters.verified && filters.verified !== "all") {
                            params.append(
                                "verified",
                                filters.verified === "verified" ? "true" : "false"
                            );
                        }

                        const fetchResponse = await makeAuthenticatedRequest(
                            `/admin/faqs?${params.toString()}`
                        );
                        if (fetchResponse.ok) {
                            const freshData = await fetchResponse.json();

                            // Intelligent merge: preserve existing FAQs, only add NEW ones
                            setFaqData((prev) => {
                                if (!prev) return freshData;

                                const existingIds = new Set(prev.faqs.map((f) => f.id));
                                const newFaqs = freshData.faqs.filter(
                                    (f: FAQ) => !existingIds.has(f.id)
                                );

                                // Only update if there are actually new FAQs to add
                                if (newFaqs.length === 0) {
                                    return prev; // No new FAQs, keep existing state to avoid re-render
                                }

                                return {
                                    ...freshData,
                                    faqs: [...prev.faqs, ...newFaqs], // Append new FAQs without touching existing ones
                                };
                            });
                        }
                    } catch (fetchError) {
                        console.warn("Failed to fetch new FAQ after deletion:", fetchError);
                        // Non-critical error - deletion succeeded, just couldn't fetch the next item
                    }

                    toast({
                        title: "FAQ Deleted",
                        description: "The FAQ has been successfully deleted.",
                    });
                    return true;
                } else {
                    // Rollback on error
                    setFaqData(originalFaqData);
                    setSelectedIndex(originalSelectedIndex);
                    const errorText = `Failed to delete FAQ. Status: ${response.status}`;
                    console.error(errorText);
                    setError(errorText);
                    toast({
                        title: "Delete Failed",
                        description: errorText,
                        variant: "destructive",
                    });
                    return false;
                }
            } catch (error) {
                // Rollback on error
                setFaqData(originalFaqData);
                setSelectedIndex(originalSelectedIndex);
                const errorText = "An unexpected error occurred while deleting the FAQ.";
                console.error(errorText, error);
                setError(errorText);
                toast({
                    title: "Delete Failed",
                    description: errorText,
                    variant: "destructive",
                });
                return false;
            }
        })();

        // Selection already updated above for immediate feedback
        // No need to reload page - violates Spatial Consistency and Feedback Immediacy principles
    };

    const handleVerifyFaq = async (faq: FAQ) => {
        // Store current index for jump-to-next logic
        const currentIndex = displayFaqs?.faqs.findIndex((f) => f.id === faq.id) ?? -1;

        // Optimistic UI update - instant feedback
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.map((f) => (f.id === faq.id ? { ...f, verified: true } : f)),
            };
        });

        try {
            const response = await makeAuthenticatedRequest(`/admin/faqs/${faq.id}/verify`, {
                method: "PATCH",
            });

            if (response.ok) {
                // Success - optimistic update already applied
                setError(null);
                toast({
                    title: "FAQ Verified",
                    description: "The FAQ has been successfully verified.",
                });

                // US-002: Jump to next unverified FAQ after verification
                if (displayFaqs && currentIndex >= 0) {
                    // Find next unverified FAQ after current position
                    const nextUnverifiedIndex = displayFaqs.faqs.findIndex(
                        (f, idx) => idx > currentIndex && !f.verified && f.id !== faq.id
                    );

                    if (nextUnverifiedIndex >= 0) {
                        // Found next unverified - jump to it
                        setSelectedIndex(nextUnverifiedIndex);
                    } else {
                        // No more unverified after current - check from beginning
                        const firstUnverifiedIndex = displayFaqs.faqs.findIndex(
                            (f) => !f.verified && f.id !== faq.id
                        );

                        if (firstUnverifiedIndex >= 0) {
                            // Found unverified from beginning - jump to it
                            setSelectedIndex(firstUnverifiedIndex);
                        }
                        // If no unverified anywhere, stay on current FAQ (now verified)
                    }
                }
            } else {
                // Rollback on error
                setFaqData((prev) => {
                    if (!prev) return prev;
                    return {
                        ...prev,
                        faqs: prev.faqs.map((f) =>
                            f.id === faq.id ? { ...f, verified: false } : f
                        ),
                    };
                });
                const errorText = `Failed to verify FAQ. Status: ${response.status}`;
                console.error(errorText);
                setError(errorText);
                toast({
                    title: "Verification Failed",
                    description: errorText,
                    variant: "destructive",
                });
            }
        } catch (error) {
            // Rollback on error
            setFaqData((prev) => {
                if (!prev) return prev;
                return {
                    ...prev,
                    faqs: prev.faqs.map((f) => (f.id === faq.id ? { ...f, verified: false } : f)),
                };
            });
            const errorText = "An unexpected error occurred while verifying FAQ.";
            console.error(errorText, error);
            setError(errorText);
            toast({
                title: "Verification Failed",
                description: errorText,
                variant: "destructive",
            });
        }
    };

    // US-003: Handle protocol assignment
    const handleSetProtocol = async (
        faq: FAQ,
        protocol: "multisig_v1" | "bisq_easy" | "musig" | "all"
    ) => {
        // Optimistic UI update
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.map((f) =>
                    f.id === faq.id ? { ...f, protocol: protocol === "all" ? null : protocol } : f
                ),
            };
        });

        try {
            const response = await makeAuthenticatedRequest(`/admin/faqs/${faq.id}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: faq.question,
                    answer: faq.answer,
                    category: faq.category,
                    source: faq.source,
                    protocol: protocol === "all" ? null : protocol,
                }),
            });

            if (response.ok) {
                const protocolDisplayName =
                    protocol === "multisig_v1"
                        ? "Multisig v1"
                        : protocol === "bisq_easy"
                          ? "Bisq Easy"
                          : protocol === "musig"
                            ? "MuSig"
                            : "All";
                toast({
                    title: "Protocol Updated",
                    description: `FAQ protocol set to ${protocolDisplayName}`,
                });
            } else {
                // Rollback on error
                setFaqData((prev) => {
                    if (!prev) return prev;
                    return {
                        ...prev,
                        faqs: prev.faqs.map((f) =>
                            f.id === faq.id ? { ...f, protocol: faq.protocol } : f
                        ),
                    };
                });
                toast({
                    title: "Update Failed",
                    description: "Failed to update protocol",
                    variant: "destructive",
                });
            }
        } catch {
            // Rollback on error
            setFaqData((prev) => {
                if (!prev) return prev;
                return {
                    ...prev,
                    faqs: prev.faqs.map((f) =>
                        f.id === faq.id ? { ...f, protocol: faq.protocol } : f
                    ),
                };
            });
            toast({
                title: "Update Failed",
                description: "An error occurred while updating protocol",
                variant: "destructive",
            });
        }
    };

    // Bulk action handlers
    const handleSelectAll = () => {
        if (!displayFaqs) return;
        if (selectedFaqIds.size === displayFaqs.faqs.length) {
            setSelectedFaqIds(new Set());
        } else {
            setSelectedFaqIds(new Set(displayFaqs.faqs.map((faq) => faq.id)));
        }
    };

    const handleSelectFaq = (id: string) => {
        setSelectedFaqIds((prev) => {
            const newSet = new Set(prev);
            if (newSet.has(id)) {
                newSet.delete(id);
            } else {
                newSet.add(id);
            }
            return newSet;
        });
    };

    const handleBulkDelete = async () => {
        if (selectedFaqIds.size === 0) return;

        // Store FAQs being deleted for potential rollback
        const deletingIds = Array.from(selectedFaqIds);
        const deletedFaqs = displayFaqs?.faqs.filter((faq) => selectedFaqIds.has(faq.id)) || [];

        // Show loading toast with vector store rebuild info
        toast({
            title: "Deleting FAQs...",
            description: `Removing ${deletingIds.length} FAQ${deletingIds.length > 1 ? "s" : ""}. The knowledge base will be rebuilt after deletion.`,
        });

        // Optimistic update: Remove FAQs from UI immediately
        // Design principle: Feedback Immediacy - <100ms response
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.filter((faq) => !selectedFaqIds.has(faq.id)),
                total_count: prev.total_count - selectedFaqIds.size,
            };
        });
        setSelectedFaqIds(new Set());

        try {
            // Use bulk delete endpoint with single vector store rebuild
            const response = await makeAuthenticatedRequest("/admin/faqs/bulk-delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ faq_ids: deletingIds }),
            });

            const result = await response.json();

            // Success - wait for delete animation to complete before fetching new FAQs
            setError(null);

            // Wait for delete animation to complete (400ms) before fetching
            await new Promise((resolve) => setTimeout(resolve, 400));

            // Smart fetch: Get current page data and merge only NEW FAQs to avoid re-animations
            try {
                const params = new URLSearchParams({
                    page: currentPage.toString(),
                    page_size: "10",
                });

                // Add filters if they exist (matching fetchFaqs logic)
                if (filters.search_text && filters.search_text.trim()) {
                    params.append("search_text", filters.search_text.trim());
                }
                if (filters.categories.length > 0) {
                    params.append("categories", filters.categories.join(","));
                }
                if (filters.source) {
                    params.append("source", filters.source);
                }
                if (filters.verified && filters.verified !== "all") {
                    params.append("verified", filters.verified === "verified" ? "true" : "false");
                }

                const fetchResponse = await makeAuthenticatedRequest(
                    `/admin/faqs?${params.toString()}`
                );
                if (fetchResponse.ok) {
                    const freshData = await fetchResponse.json();

                    // Intelligent merge: preserve existing FAQs, only add NEW ones
                    setFaqData((prev) => {
                        if (!prev) return freshData;

                        const existingIds = new Set(prev.faqs.map((f) => f.id));
                        const newFaqs = freshData.faqs.filter((f: FAQ) => !existingIds.has(f.id));

                        // Only update if there are actually new FAQs to add
                        if (newFaqs.length === 0) {
                            return prev; // No new FAQs, keep existing state to avoid re-render
                        }

                        return {
                            ...freshData,
                            faqs: [...prev.faqs, ...newFaqs], // Append new FAQs without touching existing ones
                        };
                    });
                }
            } catch (fetchError) {
                console.warn("Failed to fetch new FAQs after bulk deletion:", fetchError);
                // Non-critical error - deletion succeeded, just couldn't fetch the next items
            }

            // Show success toast
            toast({
                title: "Success",
                description:
                    result.message ||
                    `Successfully deleted ${deletingIds.length} FAQ${deletingIds.length > 1 ? "s" : ""}. Knowledge base has been updated.`,
            });

            // Show warning if some failed
            if (result.failed_count > 0) {
                toast({
                    variant: "destructive",
                    title: "Partial Success",
                    description: `${result.failed_count} FAQ${result.failed_count > 1 ? "s" : ""} could not be deleted`,
                });
            }
        } catch (error) {
            // Rollback on error: restore deleted FAQs
            setFaqData((prev) => {
                if (!prev) return prev;
                return {
                    ...prev,
                    faqs: [...deletedFaqs, ...prev.faqs].sort((a, b) => {
                        // Sort to maintain original order (newest first)
                        return a.id.localeCompare(b.id);
                    }),
                    total_count: prev.total_count + deletedFaqs.length,
                };
            });
            const errorText = "Failed to delete FAQs. Changes have been rolled back.";
            console.error(errorText, error);
            setError(errorText);

            // Show error toast
            toast({
                variant: "destructive",
                title: "Error",
                description: errorText,
            });
        }
    };

    const handleBulkVerify = async () => {
        if (selectedFaqIds.size === 0) return;

        // Store IDs being verified for potential rollback
        const verifyingIds = Array.from(selectedFaqIds);

        // Show loading toast
        toast({
            title: "Verifying FAQs...",
            description: `Marking ${verifyingIds.length} FAQ${verifyingIds.length > 1 ? "s" : ""} as verified`,
        });

        // Optimistic update: Mark FAQs as verified immediately
        // Design principle: Feedback Immediacy - <100ms response
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.map((faq) =>
                    selectedFaqIds.has(faq.id) ? { ...faq, verified: true } : faq
                ),
            };
        });
        setSelectedFaqIds(new Set());

        try {
            // Use bulk verify endpoint with single vector store rebuild
            const response = await makeAuthenticatedRequest("/admin/faqs/bulk-verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ faq_ids: verifyingIds }),
            });

            const result = await response.json();

            // Success - optimistic update already applied, no refetch needed
            setError(null);

            // Show success toast
            toast({
                title: "Success",
                description:
                    result.message ||
                    `Successfully verified ${verifyingIds.length} FAQ${verifyingIds.length > 1 ? "s" : ""}`,
            });

            // Show warning if some failed
            if (result.failed_count > 0) {
                toast({
                    variant: "destructive",
                    title: "Partial Success",
                    description: `${result.failed_count} FAQ${result.failed_count > 1 ? "s" : ""} could not be verified`,
                });
            }
        } catch (error) {
            // Rollback on error: restore verified status
            setFaqData((prev) => {
                if (!prev) return prev;
                return {
                    ...prev,
                    faqs: prev.faqs.map((faq) =>
                        verifyingIds.includes(faq.id) ? { ...faq, verified: false } : faq
                    ),
                };
            });
            const errorText = "Failed to verify FAQs. Changes have been rolled back.";
            console.error(errorText, error);
            setError(errorText);

            // Show error toast
            toast({
                variant: "destructive",
                title: "Error",
                description: errorText,
            });
        }
    };

    const openNewFaqForm = () => {
        setFormData({
            question: "",
            answer: "",
            category: "",
            source: "Manual",
            protocol: "bisq_easy",
        });
        setIsFormOpen(true);
        setError(null);
        window.scrollTo({ top: 0, behavior: "smooth" });
    };

    const handlePageChange = (newPage: number) => {
        if (newPage >= 1 && newPage <= (faqData?.total_pages || 1)) {
            setCurrentPage(newPage);
            fetchFaqs(newPage);
        }
    };

    // Inline editing functions
    const enterEditMode = (faq: FAQ) => {
        // If already editing, prevent starting a new edit
        if (editingFaqId && editingFaqId !== faq.id) {
            sonnerToast.warning("Save or cancel current edit first");
            return;
        }

        // Check if this FAQ has a failed submission with preserved draft
        const hasFailed = failedFaqIds.has(faq.id);
        const preservedDraft = draftEdits.get(faq.id);

        if (hasFailed && preservedDraft) {
            // Re-entering edit mode for retry
            setEditingFaqId(faq.id);
            sonnerToast.info("Retry editing", {
                description: "Your previous changes are preserved",
            });
        } else {
            // Normal edit mode entry
            setEditingFaqId(faq.id);
            setDraftEdits(new Map().set(faq.id, {}));

            // Auto-expand verified FAQs when entering edit mode
            if (faq.verified && !expandedIds.has(faq.id)) {
                setExpandedIds((prev) => new Set(prev).add(faq.id));
            }
        }
    };

    const handleCancelEdit = (faqId: string) => {
        const hasFailed = failedFaqIds.has(faqId);

        // Exit edit mode
        setEditingFaqId(null);

        if (hasFailed) {
            // Clear failure state and discard draft
            setFailedFaqIds((prev) => {
                const next = new Set(prev);
                next.delete(faqId);
                return next;
            });

            setDraftEdits((prev) => {
                const next = new Map(prev);
                next.delete(faqId);
                return next;
            });

            sonnerToast.info("Draft discarded", {
                description: "Failed changes have been removed",
            });
        } else {
            // Normal cancel - just remove draft
            setDraftEdits((prev) => {
                const next = new Map(prev);
                next.delete(faqId);
                return next;
            });
        }
    };

    const handleSaveInlineEdit = async (faqId: string, updatedFaq: FAQ) => {
        const originalFaqData = faqData;

        // Optimistic UI update
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.map((f) => (f.id === faqId ? updatedFaq : f)),
            };
        });

        try {
            const response = await makeAuthenticatedRequest(`/admin/faqs/${faqId}`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    question: updatedFaq.question,
                    answer: updatedFaq.answer,
                    category: updatedFaq.category,
                    source: updatedFaq.source,
                    protocol: updatedFaq.protocol,
                }),
            });

            if (!response.ok) {
                throw new Error(`Update failed with status ${response.status}`);
            }

            // Get the updated FAQ with new ID from the API response
            const updatedFaqFromApi: FAQ = await response.json();

            // Update FAQ data with the new FAQ ID from the server
            setFaqData((prev) => {
                if (!prev) return prev;
                return {
                    ...prev,
                    faqs: prev.faqs.map((f) => (f.id === faqId ? updatedFaqFromApi : f)),
                };
            });

            // Success - clear edit mode and failure state
            setEditingFaqId(null);
            setFailedFaqIds((prev) => {
                const next = new Set(prev);
                next.delete(faqId);
                return next;
            });
            setDraftEdits((prev) => {
                const next = new Map(prev);
                next.delete(faqId);
                return next;
            });

            // US-001: Stay on current FAQ after save (don't move to next)
            // Keep the selection on the current FAQ that was just saved
            const currentIdx =
                displayFaqs?.faqs.findIndex((f) => f.id === updatedFaqFromApi.id) ?? -1;
            if (currentIdx >= 0) {
                setSelectedIndex(currentIdx);
            }

            sonnerToast.success("FAQ updated successfully");
        } catch {
            // Rollback optimistic update
            setFaqData(originalFaqData);

            // IMPORTANT: Exit edit mode but mark as failed
            setEditingFaqId(null);

            // Mark FAQ as failed and preserve draft
            setFailedFaqIds((prev) => new Set(prev).add(faqId));
            setDraftEdits((prev) => new Map(prev).set(faqId, updatedFaq));

            sonnerToast.error("Failed to save FAQ", {
                description: "Changes preserved. Navigate back to retry.",
                action: {
                    label: "Retry Now",
                    onClick: () => {
                        const index = displayFaqs?.faqs.findIndex((f) => f.id === faqId) ?? -1;
                        if (index >= 0) {
                            setSelectedIndex(index);
                            setEditingFaqId(faqId);
                        }
                    },
                },
            });
        }
    };

    // Filter helper functions with debouncing
    const debouncedSearchChange = useMemo(
        () =>
            debounce((value: string) => {
                setFilters((prev) => ({ ...prev, search_text: value }));
            }, 300),
        []
    );

    const handleSearchChange = (value: string) => {
        // Update local state immediately for responsive UI
        debouncedSearchChange(value);
    };

    const handleCategoryToggle = (category: string) => {
        setFilters((prev) => ({
            ...prev,
            categories: prev.categories.includes(category)
                ? prev.categories.filter((c) => c !== category)
                : [...prev.categories, category],
        }));
    };

    const handleSourceChange = (source: string) => {
        setFilters((prev) => ({ ...prev, source: source === "all" ? "" : source }));
    };

    const clearAllFilters = () => {
        setFilters({
            search_text: "",
            categories: [],
            source: "",
            verified: "all",
            protocol: "",
            verified_from: undefined,
            verified_to: undefined,
        });
        // Also clear the input field value
        if (searchInputRef.current) {
            searchInputRef.current.value = "";
        }
    };

    const hasActiveFilters =
        filters.search_text ||
        filters.categories.length > 0 ||
        filters.source ||
        filters.verified !== "all" ||
        filters.protocol ||
        filters.verified_from ||
        filters.verified_to;

    return (
        <TooltipProvider>
            <div className="min-h-screen bg-background">
                {/* Persistent banner at top */}
                <VectorStoreStatusBanner />

                {/* Similar FAQ Review Queue (Phase 7) */}
                {(pendingReviewItems.length > 0 || isLoadingPendingReview) && (
                    <div className="px-8 pt-4">
                        <SimilarFaqReviewQueue
                            items={pendingReviewItems}
                            isLoading={isLoadingPendingReview}
                            onApprove={handleApproveReviewItem}
                            onMerge={handleMergeReviewItem}
                            onDismiss={handleDismissReviewItem}
                            onRefresh={fetchPendingReviewItems}
                        />
                    </div>
                )}

                <div className="p-8 space-y-8 pt-16 lg:pt-8">
                    {/* Header with persistent search */}
                    <div className="flex flex-col gap-4">
                        <div className="flex items-start justify-between">
                            <div>
                                <h1 className="text-2xl font-semibold tracking-tight leading-tight">
                                    FAQ Management
                                </h1>
                                <p className="text-muted-foreground text-sm mt-1">
                                    Create and manage frequently asked questions for the support
                                    system
                                </p>
                            </div>
                        </div>

                        {/* Persistent Search Bar and Filter Chips */}
                        <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
                            {/* Persistent Inline Search */}
                            <div className="relative w-full sm:w-64 lg:w-96">
                                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground/70 z-10 pointer-events-none" />
                                <Input
                                    ref={searchInputRef}
                                    placeholder="Search FAQs... (/)"
                                    className="pl-9 pr-4 h-9 bg-background/60 backdrop-blur-sm border-border/40 focus:border-primary focus:bg-background transition-all"
                                    defaultValue={filters.search_text}
                                    onChange={(e) => handleSearchChange(e.target.value)}
                                />
                                {filters.search_text && (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 p-0"
                                        onClick={() => {
                                            setFilters((prev) => ({ ...prev, search_text: "" }));
                                            if (searchInputRef.current) {
                                                searchInputRef.current.value = "";
                                            }
                                        }}
                                    >
                                        <X className="h-3 w-3" />
                                    </Button>
                                )}
                            </div>

                            {/* Filter Chips Row */}
                            <div className="flex items-center gap-2 flex-wrap flex-1">
                                {/* Category Filter Chip */}
                                <Select
                                    value={
                                        filters.categories.length > 0
                                            ? filters.categories[0]
                                            : "all"
                                    }
                                    onValueChange={(value) => {
                                        if (value === "all") {
                                            setFilters((prev) => ({ ...prev, categories: [] }));
                                        } else {
                                            setFilters((prev) => ({
                                                ...prev,
                                                categories: [value],
                                            }));
                                        }
                                    }}
                                >
                                    <SelectTrigger className="h-8 w-auto gap-2 px-3 border-dashed">
                                        <Badge variant="outline" className="px-0 border-0">
                                            {filters.categories.length > 0
                                                ? filters.categories[0]
                                                : "All Categories"}
                                        </Badge>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">All Categories</SelectItem>
                                        {availableCategories.map((category) => (
                                            <SelectItem key={category} value={category}>
                                                {category}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>

                                {/* Verified Status Filter Chip */}
                                <Select
                                    value={filters.verified || "all"}
                                    onValueChange={(value) => {
                                        setFilters((prev) => ({
                                            ...prev,
                                            verified: value as "all" | "verified" | "unverified",
                                        }));
                                    }}
                                >
                                    <SelectTrigger className="h-8 w-auto gap-2 px-3 border-dashed">
                                        <Badge variant="outline" className="px-0 border-0">
                                            {filters.verified === "verified"
                                                ? "Verified"
                                                : filters.verified === "unverified"
                                                  ? "Unverified"
                                                  : "All Status"}
                                        </Badge>
                                    </SelectTrigger>
                                    <SelectContent>
                                        <SelectItem value="all">All Status</SelectItem>
                                        <SelectItem value="verified">Verified Only</SelectItem>
                                        <SelectItem value="unverified">Unverified Only</SelectItem>
                                    </SelectContent>
                                </Select>

                                {/* Advanced Filter Button */}
                                <Button
                                    onClick={() => setShowFilters(!showFilters)}
                                    variant="outline"
                                    size="sm"
                                    className="h-8 border-dashed"
                                >
                                    <Filter className="mr-2 h-4 w-4" />
                                    Advanced
                                </Button>

                                {/* Reset All Filters Button */}
                                {hasActiveFilters && (
                                    <Button
                                        variant="ghost"
                                        size="sm"
                                        onClick={clearAllFilters}
                                        className="h-8 px-2 text-muted-foreground hover:text-foreground"
                                    >
                                        <RotateCcw className="mr-1 h-3 w-3" />
                                        Reset
                                    </Button>
                                )}
                            </div>
                        </div>
                    </div>

                    {/* Error Display */}
                    {error && (
                        <div
                            className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-lg"
                            role="alert"
                        >
                            <strong className="font-bold">Error: </strong>
                            <span className="block sm:inline">{error}</span>
                        </div>
                    )}

                    {/* Filters Panel */}
                    {showFilters && (
                        <Card>
                            <CardHeader className="relative">
                                <Button
                                    onClick={() => setShowFilters(false)}
                                    variant="outline"
                                    size="sm"
                                    className="absolute right-2 top-2 h-8 w-8 p-0"
                                    aria-label="Close filters"
                                >
                                    <X className="h-4 w-4" />
                                </Button>
                                <CardTitle className="flex items-center gap-2">
                                    <Filter className="h-5 w-5" />
                                    Filters
                                </CardTitle>
                                <CardDescription>
                                    Filter FAQs by text search, categories, and source
                                </CardDescription>
                            </CardHeader>
                            <CardContent className="space-y-6">
                                {/* Search Text */}
                                <div className="space-y-2">
                                    <Label htmlFor="search">Search Text</Label>
                                    <div className="relative">
                                        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                        <Input
                                            id="search"
                                            placeholder="Search in questions and answers..."
                                            value={filters.search_text}
                                            onChange={(e) => handleSearchChange(e.target.value)}
                                            className="pl-10"
                                        />
                                    </div>
                                </div>

                                {/* Categories */}
                                <div className="space-y-2">
                                    <Label>Categories</Label>
                                    <div className="flex flex-wrap gap-2">
                                        {availableCategories.map((category) => (
                                            <Badge
                                                key={category}
                                                variant={
                                                    filters.categories.includes(category)
                                                        ? "default"
                                                        : "outline"
                                                }
                                                className="cursor-pointer hover:bg-primary hover:text-primary-foreground"
                                                onClick={() => handleCategoryToggle(category)}
                                            >
                                                {category}
                                            </Badge>
                                        ))}
                                        {availableCategories.length === 0 && (
                                            <p className="text-sm text-muted-foreground">
                                                No categories available
                                            </p>
                                        )}
                                    </div>
                                </div>

                                {/* Verified Status, Source, and Bisq Version - Three columns */}
                                <div className="grid grid-cols-3 gap-4">
                                    {/* Verified Status */}
                                    <div className="space-y-2">
                                        <Label htmlFor="verified-status">Verification Status</Label>
                                        <Select
                                            value={filters.verified || "all"}
                                            onValueChange={(value) => {
                                                setFilters((prev) => ({
                                                    ...prev,
                                                    verified: value as
                                                        | "all"
                                                        | "verified"
                                                        | "unverified",
                                                }));
                                            }}
                                        >
                                            <SelectTrigger id="verified-status">
                                                <SelectValue placeholder="All Status" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="all">All Status</SelectItem>
                                                <SelectItem value="verified">
                                                    Verified Only
                                                </SelectItem>
                                                <SelectItem value="unverified">
                                                    Unverified Only
                                                </SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>

                                    {/* Source */}
                                    <div className="space-y-2">
                                        <Label htmlFor="source">Source</Label>
                                        <Select
                                            value={filters.source || "all"}
                                            onValueChange={handleSourceChange}
                                        >
                                            <SelectTrigger id="source">
                                                <SelectValue placeholder="Select source" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="all">All Sources</SelectItem>
                                                {availableSources.map((source) => (
                                                    <SelectItem key={source} value={source}>
                                                        {source}
                                                    </SelectItem>
                                                ))}
                                            </SelectContent>
                                        </Select>
                                    </div>

                                    {/* Protocol */}
                                    <div className="space-y-2">
                                        <Label htmlFor="protocol-filter">Protocol</Label>
                                        <Select
                                            value={filters.protocol || "show_all"}
                                            onValueChange={(value) => {
                                                setFilters({
                                                    ...filters,
                                                    protocol: value === "show_all" ? "" : value,
                                                });
                                                setCurrentPage(1);
                                            }}
                                        >
                                            <SelectTrigger id="protocol-filter">
                                                <SelectValue placeholder="All Protocols" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="show_all">All Protocols</SelectItem>
                                                <SelectItem value="multisig_v1">Bisq 1 (Multisig)</SelectItem>
                                                <SelectItem value="bisq_easy">Bisq Easy</SelectItem>
                                                <SelectItem value="musig">MuSig</SelectItem>
                                                <SelectItem value="all">General (All)</SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>

                                {/* Date Range Filtering */}
                                <div className="space-y-4 pt-4 border-t">
                                    <div className="space-y-2">
                                        <Label className="text-sm font-medium">
                                            Verification Date Range
                                        </Label>
                                        <p className="text-xs text-muted-foreground">
                                            Filter FAQs verified within a specific date range
                                        </p>
                                    </div>

                                    <div className="grid grid-cols-2 gap-4">
                                        {/* From Date */}
                                        <div className="space-y-2">
                                            <Label className="text-xs text-muted-foreground">
                                                From Date
                                            </Label>
                                            <DatePicker
                                                value={filters.verified_from}
                                                onChange={(date) => {
                                                    setFilters({ ...filters, verified_from: date });
                                                    setCurrentPage(1);
                                                }}
                                                placeholder="Select start date"
                                            />
                                        </div>

                                        {/* To Date */}
                                        <div className="space-y-2">
                                            <Label className="text-xs text-muted-foreground">
                                                To Date
                                            </Label>
                                            <DatePicker
                                                value={filters.verified_to}
                                                onChange={(date) => {
                                                    setFilters({ ...filters, verified_to: date });
                                                    setCurrentPage(1);
                                                }}
                                                placeholder="Select end date"
                                            />
                                        </div>
                                    </div>
                                </div>

                                {/* Filter Actions - Reset and Export */}
                                <div className="space-y-3 pt-4 border-t">
                                    {/* Action Buttons Row */}
                                    <div className="flex items-center gap-3">
                                        <Button
                                            variant="outline"
                                            onClick={clearAllFilters}
                                            disabled={!hasActiveFilters}
                                            size="sm"
                                            className="flex-shrink-0"
                                        >
                                            <RotateCcw className="mr-2 h-4 w-4" />
                                            Reset Filters
                                        </Button>

                                        <Button
                                            onClick={async () => {
                                                if (!faqData || faqData.total_count === 0) {
                                                    sonnerToast.error("No FAQs to export");
                                                    return;
                                                }

                                                try {
                                                    // Build query parameters for export endpoint
                                                    const params = new URLSearchParams();

                                                    if (
                                                        filters.search_text &&
                                                        filters.search_text.trim()
                                                    ) {
                                                        params.append(
                                                            "search_text",
                                                            filters.search_text.trim()
                                                        );
                                                    }

                                                    if (filters.categories.length > 0) {
                                                        params.append(
                                                            "categories",
                                                            filters.categories.join(",")
                                                        );
                                                    }

                                                    if (filters.source && filters.source.trim()) {
                                                        params.append(
                                                            "source",
                                                            filters.source.trim()
                                                        );
                                                    }

                                                    if (filters.verified !== "all") {
                                                        params.append(
                                                            "verified",
                                                            filters.verified === "verified"
                                                                ? "true"
                                                                : "false"
                                                        );
                                                    }

                                                    if (
                                                        filters.protocol &&
                                                        filters.protocol.trim()
                                                    ) {
                                                        params.append(
                                                            "protocol",
                                                            filters.protocol.trim()
                                                        );
                                                    }

                                                    if (filters.verified_from) {
                                                        const serialized = serializeDateFilter(
                                                            filters.verified_from,
                                                            false
                                                        );
                                                        if (serialized)
                                                            params.append(
                                                                "verified_from",
                                                                serialized
                                                            );
                                                    }

                                                    if (filters.verified_to) {
                                                        const serialized = serializeDateFilter(
                                                            filters.verified_to,
                                                            true
                                                        );
                                                        if (serialized)
                                                            params.append(
                                                                "verified_to",
                                                                serialized
                                                            );
                                                    }

                                                    // Fetch CSV via server-side streaming endpoint
                                                    // Authentication handled via cookies in makeAuthenticatedRequest
                                                    // makeAuthenticatedRequest internally prefixes with API_BASE_URL
                                                    const response = await makeAuthenticatedRequest(
                                                        `/admin/faqs/export?${params.toString()}`
                                                    );

                                                    if (!response.ok) {
                                                        throw new Error(
                                                            `Export failed: ${response.status}`
                                                        );
                                                    }

                                                    // Create blob and trigger download
                                                    const blob = await response.blob();
                                                    const url = window.URL.createObjectURL(blob);
                                                    const a = document.createElement("a");
                                                    a.href = url;

                                                    // Extract filename from Content-Disposition header or use default
                                                    const contentDisposition =
                                                        response.headers.get("Content-Disposition");
                                                    const filenameMatch =
                                                        contentDisposition?.match(
                                                            /filename="?([^"]+)"?/
                                                        );
                                                    a.download = filenameMatch
                                                        ? filenameMatch[1]
                                                        : "faqs_export.csv";

                                                    document.body.appendChild(a);
                                                    a.click();
                                                    document.body.removeChild(a);
                                                    window.URL.revokeObjectURL(url);

                                                    sonnerToast.success("Export complete", {
                                                        description: hasActiveFilters
                                                            ? "Filtered FAQs downloaded"
                                                            : "All FAQs downloaded",
                                                    });
                                                } catch (error) {
                                                    console.error("Export failed:", error);
                                                    sonnerToast.error("Failed to export FAQs", {
                                                        description: "Please try again",
                                                    });
                                                }
                                            }}
                                            variant="default"
                                            size="sm"
                                            disabled={!faqData || faqData.total_count === 0}
                                        >
                                            <Download className="mr-2 h-4 w-4" />
                                            Export {faqData?.total_count || 0} FAQs to CSV
                                        </Button>
                                    </div>

                                    {/* Active Filters Summary */}
                                    {hasActiveFilters && (
                                        <div className="text-sm text-muted-foreground">
                                            <span>
                                                {[
                                                    filters.search_text && "Text search",
                                                    filters.categories.length > 0 &&
                                                        `${filters.categories.length} categor${filters.categories.length === 1 ? "y" : "ies"}`,
                                                    filters.source && "Source",
                                                    filters.verified !== "all" &&
                                                        "Verification status",
                                                    filters.protocol && "Protocol",
                                                    (filters.verified_from ||
                                                        filters.verified_to) &&
                                                        "Date range",
                                                ]
                                                    .filter(Boolean)
                                                    .join(", ")}{" "}
                                                applied
                                            </span>
                                        </div>
                                    )}
                                </div>
                            </CardContent>
                        </Card>
                    )}

                    {/* FAQ Form */}
                    {/* FAQ Form Sheet (Slide-over Panel) */}
                    <Sheet open={isFormOpen} onOpenChange={setIsFormOpen}>
                        <SheetContent className="sm:max-w-[540px] overflow-y-auto">
                            <form onSubmit={handleFormSubmit} className="flex flex-col h-full">
                                <SheetHeader>
                                    <SheetTitle>Add New FAQ</SheetTitle>
                                    <SheetDescription>
                                        Fill out the form to add a new FAQ to the knowledge base.
                                    </SheetDescription>
                                </SheetHeader>
                                <div className="flex-1 space-y-4 py-6">
                                    <div className="space-y-2">
                                        <Label htmlFor="question">Question</Label>
                                        <Input
                                            id="question"
                                            value={formData.question}
                                            onChange={(e) =>
                                                setFormData({
                                                    ...formData,
                                                    question: e.target.value,
                                                })
                                            }
                                            onBlur={handleQuestionBlur}
                                            required
                                        />
                                    </div>

                                    {/* Similar FAQs Panel */}
                                    <SimilarFaqsPanel
                                        similarFaqs={similarFaqs}
                                        isLoading={isCheckingSimilar}
                                        onViewFaq={handleViewSimilarFaq}
                                    />

                                    <div className="space-y-2">
                                        <Label htmlFor="answer">Answer</Label>
                                        <Textarea
                                            id="answer"
                                            value={formData.answer}
                                            onChange={(e) =>
                                                setFormData({ ...formData, answer: e.target.value })
                                            }
                                            rows={8}
                                            required
                                        />
                                    </div>
                                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                        <div className="space-y-2">
                                            <Label htmlFor="category">Category</Label>
                                            <Popover
                                                open={categoryComboboxOpen}
                                                onOpenChange={setCategoryComboboxOpen}
                                            >
                                                <PopoverTrigger asChild>
                                                    <Button
                                                        variant="outline"
                                                        role="combobox"
                                                        aria-expanded={categoryComboboxOpen}
                                                        className="w-full justify-between"
                                                    >
                                                        {formData.category || "Select category..."}
                                                        <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                                                    </Button>
                                                </PopoverTrigger>
                                                <PopoverContent className="w-full p-0">
                                                    <Command>
                                                        <CommandInput
                                                            placeholder="Search or type new category..."
                                                            value={formData.category}
                                                            onValueChange={(value) =>
                                                                setFormData({
                                                                    ...formData,
                                                                    category: value,
                                                                })
                                                            }
                                                            onKeyDown={(e) => {
                                                                if (e.key === "Enter") {
                                                                    // Close popover when Enter is pressed to create new category
                                                                    setCategoryComboboxOpen(false);
                                                                }
                                                            }}
                                                        />
                                                        <CommandList>
                                                            <CommandEmpty>
                                                                Press Enter to create &quot;
                                                                {formData.category}&quot;
                                                            </CommandEmpty>
                                                            {availableCategories.length > 0 && (
                                                                <CommandGroup heading="Existing Categories">
                                                                    {availableCategories.map(
                                                                        (category) => (
                                                                            <CommandItem
                                                                                key={category}
                                                                                value={category}
                                                                                onSelect={(
                                                                                    currentValue
                                                                                ) => {
                                                                                    setFormData({
                                                                                        ...formData,
                                                                                        category:
                                                                                            currentValue,
                                                                                    });
                                                                                    setCategoryComboboxOpen(
                                                                                        false
                                                                                    );
                                                                                }}
                                                                            >
                                                                                <Check
                                                                                    className={`mr-2 h-4 w-4 ${
                                                                                        formData.category ===
                                                                                        category
                                                                                            ? "opacity-100"
                                                                                            : "opacity-0"
                                                                                    }`}
                                                                                />
                                                                                {category}
                                                                            </CommandItem>
                                                                        )
                                                                    )}
                                                                </CommandGroup>
                                                            )}
                                                        </CommandList>
                                                    </Command>
                                                </PopoverContent>
                                            </Popover>
                                        </div>
                                        <div className="space-y-2">
                                            <Label htmlFor="source">Source</Label>
                                            <Input
                                                id="source"
                                                value={formData.source}
                                                onChange={(e) =>
                                                    setFormData({
                                                        ...formData,
                                                        source: e.target.value,
                                                    })
                                                }
                                                disabled
                                            />
                                        </div>
                                    </div>
                                    <div className="space-y-2">
                                        <Label htmlFor="protocol">Protocol</Label>
                                        <Select
                                            value={formData.protocol}
                                            onValueChange={(value) =>
                                                setFormData({
                                                    ...formData,
                                                    protocol: value as
                                                        | "multisig_v1"
                                                        | "bisq_easy"
                                                        | "musig"
                                                        | "all",
                                                })
                                            }
                                        >
                                            <SelectTrigger id="protocol">
                                                <SelectValue placeholder="Select protocol" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="bisq_easy">
                                                    Bisq Easy (Default)
                                                </SelectItem>
                                                <SelectItem value="multisig_v1">Bisq 1 (Multisig)</SelectItem>
                                                <SelectItem value="musig">MuSig</SelectItem>
                                                <SelectItem value="all">
                                                    General (All Protocols)
                                                </SelectItem>
                                            </SelectContent>
                                        </Select>
                                    </div>
                                </div>
                                <SheetFooter className="mt-auto">
                                    <Button
                                        type="button"
                                        variant="outline"
                                        onClick={() => setIsFormOpen(false)}
                                    >
                                        Cancel
                                    </Button>
                                    <Button type="submit" disabled={isSubmitting}>
                                        {isSubmitting ? (
                                            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                        ) : null}
                                        Add FAQ
                                    </Button>
                                </SheetFooter>
                            </form>
                        </SheetContent>
                    </Sheet>

                    {/* FAQ List */}
                    <Card className="bg-card border border-border shadow-sm">
                        <CardHeader className="flex flex-row items-center justify-between">
                            <div>
                                <CardTitle>FAQ List</CardTitle>
                                <CardDescription>
                                    View, edit, or delete existing FAQs.
                                </CardDescription>
                            </div>
                            <div className="flex items-center gap-2">
                                {!isFormOpen && !bulkSelectionMode && (
                                    <>
                                        <TooltipProvider>
                                            <Tooltip>
                                                <TooltipTrigger asChild>
                                                    <Button
                                                        onClick={openNewFaqForm}
                                                        className="gap-2"
                                                    >
                                                        <PlusCircle className="h-4 w-4" />
                                                        <span>Add New FAQ</span>
                                                    </Button>
                                                </TooltipTrigger>
                                                <TooltipContent>
                                                    <p>Create a new FAQ entry (Press N)</p>
                                                </TooltipContent>
                                            </Tooltip>
                                        </TooltipProvider>

                                        <DropdownMenu>
                                            <TooltipProvider>
                                                <Tooltip>
                                                    <TooltipTrigger asChild>
                                                        <DropdownMenuTrigger asChild>
                                                            <Button variant="outline" size="icon">
                                                                <MoreVertical className="h-4 w-4" />
                                                            </Button>
                                                        </DropdownMenuTrigger>
                                                    </TooltipTrigger>
                                                    <TooltipContent>
                                                        <p>More actions</p>
                                                    </TooltipContent>
                                                </Tooltip>
                                            </TooltipProvider>
                                            <DropdownMenuContent align="end" className="w-48">
                                                <DropdownMenuItem
                                                    onClick={() => {
                                                        setBulkSelectionMode(true);
                                                        setSelectedFaqIds(new Set());
                                                    }}
                                                    className="cursor-pointer"
                                                >
                                                    <CheckSquare className="mr-2 h-4 w-4" />
                                                    <span>Enable Bulk Selection</span>
                                                    <kbd className="ml-auto pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground opacity-100">
                                                        B
                                                    </kbd>
                                                </DropdownMenuItem>
                                            </DropdownMenuContent>
                                        </DropdownMenu>
                                    </>
                                )}
                            </div>
                        </CardHeader>
                        <CardContent>
                            {isLoading ? (
                                <div className="space-y-4">
                                    {[1, 2, 3].map((i) => (
                                        <div
                                            key={i}
                                            className="bg-card border rounded-lg p-6 space-y-4"
                                        >
                                            <div className="flex items-start justify-between">
                                                <div className="flex-1 space-y-3">
                                                    <Skeleton className="h-6 w-3/4" />
                                                    <div className="flex items-center gap-4">
                                                        <Skeleton className="h-5 w-24 rounded-full" />
                                                        <Skeleton className="h-4 w-32" />
                                                        <Skeleton className="h-4 w-28" />
                                                    </div>
                                                </div>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    {/* Bulk Action Toolbar */}
                                    {bulkSelectionMode && (
                                        <div className="sticky top-0 z-10 bg-background/95 backdrop-blur-sm border-b px-4 py-3 -mx-6 -mt-4 mb-4">
                                            <div className="flex items-center justify-between">
                                                <div className="flex items-center gap-4">
                                                    <Checkbox
                                                        id="select-all"
                                                        checked={
                                                            (displayFaqs?.faqs.length ?? 0) > 0 &&
                                                            selectedFaqIds.size ===
                                                                (displayFaqs?.faqs.length ?? 0)
                                                        }
                                                        onCheckedChange={handleSelectAll}
                                                        disabled={isSubmitting}
                                                        aria-label="Select all FAQs"
                                                    />
                                                    <label
                                                        htmlFor="select-all"
                                                        className="text-sm font-medium cursor-pointer"
                                                    >
                                                        {selectedFaqIds.size === 0
                                                            ? "Select all"
                                                            : `${selectedFaqIds.size} selected`}
                                                    </label>
                                                </div>
                                                <div className="flex items-center gap-2">
                                                    {selectedFaqIds.size > 0 && (
                                                        <>
                                                            <Button
                                                                variant="outline"
                                                                size="sm"
                                                                onClick={handleBulkVerify}
                                                                disabled={isSubmitting}
                                                            >
                                                                {isSubmitting ? (
                                                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                                                ) : (
                                                                    <BadgeCheck className="mr-2 h-4 w-4" />
                                                                )}
                                                                Verify Selected
                                                            </Button>
                                                            <Button
                                                                variant="outline"
                                                                size="sm"
                                                                onClick={handleBulkDelete}
                                                                disabled={isSubmitting}
                                                            >
                                                                {isSubmitting ? (
                                                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                                                ) : (
                                                                    <Trash2 className="mr-2 h-4 w-4" />
                                                                )}
                                                                Delete Selected
                                                            </Button>
                                                        </>
                                                    )}
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        onClick={() => {
                                                            setBulkSelectionMode(false);
                                                            setSelectedFaqIds(new Set());
                                                        }}
                                                        disabled={isSubmitting}
                                                    >
                                                        Cancel
                                                    </Button>
                                                </div>
                                            </div>
                                        </div>
                                    )}

                                    {displayFaqs?.faqs.map((faq, index) => {
                                        // Check if this FAQ is in edit mode
                                        const isEditing = editingFaqId === faq.id;

                                        // If editing, render inline edit component (no animation to avoid React 19 warnings)
                                        if (isEditing) {
                                            return (
                                                <div
                                                    key={faq.id}
                                                    ref={setFaqRef(faq.id)}
                                                    className="mb-4"
                                                >
                                                    <InlineEditFAQ
                                                        faq={faq}
                                                        index={index}
                                                        draftEdits={draftEdits}
                                                        setDraftEdits={setDraftEdits}
                                                        failedFaqIds={failedFaqIds}
                                                        handleSaveInlineEdit={handleSaveInlineEdit}
                                                        handleCancelEdit={handleCancelEdit}
                                                        editCategoryComboboxOpen={
                                                            editCategoryComboboxOpen
                                                        }
                                                        setEditCategoryComboboxOpen={
                                                            setEditCategoryComboboxOpen
                                                        }
                                                        availableCategories={availableCategories}
                                                        onViewSimilarFaq={handleViewSimilarFaqFromEdit}
                                                    />
                                                </div>
                                            );
                                        }

                                        // Smart expansion logic: verified FAQs can be collapsed, unverified FAQs always expanded
                                        const isExpanded = !faq.verified || expandedIds.has(faq.id);
                                        const isSelected = index === selectedIndex;
                                        const hasFailed = failedFaqIds.has(faq.id);

                                        return (
                                            <motion.div
                                                key={faq.id}
                                                initial={{
                                                    opacity: 0,
                                                    height: 0,
                                                    marginBottom: 0,
                                                }}
                                                animate={{
                                                    opacity: 1,
                                                    height: "auto",
                                                    marginBottom: "1rem",
                                                }}
                                                exit={{
                                                    opacity: 0,
                                                    height: 0,
                                                    marginBottom: 0,
                                                    transition: { duration: 0.4 },
                                                }}
                                                transition={{ duration: 0.2 }}
                                                layout
                                            >
                                                <Collapsible
                                                    key={faq.id}
                                                    open={isExpanded}
                                                    onOpenChange={(open) => {
                                                        // Only allow collapsing verified FAQs
                                                        if (faq.verified) {
                                                            setExpandedIds((prev) => {
                                                                const newSet = new Set(prev);
                                                                if (open) {
                                                                    newSet.add(faq.id);
                                                                } else {
                                                                    newSet.delete(faq.id);
                                                                }
                                                                return newSet;
                                                            });
                                                        }
                                                    }}
                                                    ref={setFaqRef(faq.id)}
                                                    className={`
                                            bg-card border rounded-lg group
                                            transition-all duration-200 ease-[cubic-bezier(0.4,0,0.2,1)]
                                            ${
                                                isSelected
                                                    ? "border-green-500 shadow-lg shadow-green-500/20 ring-2 ring-green-500/30 ring-offset-2 ring-offset-background"
                                                    : "border-border hover:shadow-md hover:border-border/60 hover:-translate-y-0.5"
                                            }
                                        `}
                                                    tabIndex={-1}
                                                    style={{
                                                        outline: "none", // Remove default outline, we use custom ring
                                                    }}
                                                >
                                                    <div className="p-6">
                                                        {faq.verified ? (
                                                            <div className="flex items-start gap-3">
                                                                {bulkSelectionMode && (
                                                                    <div className="flex items-start pt-1">
                                                                        <Checkbox
                                                                            checked={selectedFaqIds.has(
                                                                                faq.id
                                                                            )}
                                                                            onCheckedChange={() =>
                                                                                handleSelectFaq(
                                                                                    faq.id
                                                                                )
                                                                            }
                                                                            disabled={isSubmitting}
                                                                            aria-label={`Select FAQ: ${faq.question}`}
                                                                        />
                                                                    </div>
                                                                )}
                                                                <CollapsibleTrigger
                                                                    className="flex-1 group/trigger focus-visible:outline-none"
                                                                    onFocus={() => {
                                                                        // Sync Tab navigation with keyboard selection
                                                                        setSelectedIndex(index);
                                                                    }}
                                                                    onClick={(e) => {
                                                                        const target =
                                                                            e.target as HTMLElement;
                                                                        const isArrowClick =
                                                                            target.closest("svg") ||
                                                                            (target.classList.contains(
                                                                                "relative"
                                                                            ) &&
                                                                                target.querySelector(
                                                                                    "svg"
                                                                                ));

                                                                        if (isExpanded) {
                                                                            if (isArrowClick) {
                                                                                // Collapsing via arrow: Don't update selection
                                                                                // This avoids animation conflict between collapse and layout animations
                                                                                return; // Let collapse happen naturally
                                                                            } else {
                                                                                // Clicking content when expanded: Select but stay expanded
                                                                                setSelectedIndex(
                                                                                    index
                                                                                );
                                                                                e.preventDefault();
                                                                            }
                                                                        } else {
                                                                            // Expanding: Always set selection
                                                                            setSelectedIndex(index);
                                                                        }
                                                                    }}
                                                                >
                                                                    <div className="flex items-start justify-between gap-3 text-left">
                                                                        <div className="flex-1 space-y-2">
                                                                            <div className="flex items-start gap-2">
                                                                                <h3 className="font-medium text-card-foreground text-[15px] leading-[1.4] tracking-tight flex-1">
                                                                                    {faq.question}
                                                                                </h3>
                                                                                {hasFailed && (
                                                                                    <Badge
                                                                                        variant="destructive"
                                                                                        className="text-[10px]"
                                                                                    >
                                                                                        <AlertCircle className="h-3 w-3 mr-1" />
                                                                                        Failed
                                                                                    </Badge>
                                                                                )}
                                                                                <div className="relative flex-shrink-0">
                                                                                    <ChevronRight
                                                                                        className={`h-5 w-5 text-muted-foreground transition-transform duration-200 mt-0.5 ${
                                                                                            isExpanded
                                                                                                ? "rotate-90"
                                                                                                : ""
                                                                                        }`}
                                                                                    />
                                                                                    {/* Focus ring for the icon */}
                                                                                    <div className="absolute inset-0 -m-2 rounded-md opacity-0 group-focus-visible/trigger:opacity-100 ring-2 ring-green-500/30 ring-offset-2 ring-offset-background transition-opacity pointer-events-none" />
                                                                                </div>
                                                                            </div>

                                                                            <div className="flex items-center gap-4 text-[12px] text-muted-foreground">
                                                                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground font-medium text-[12px] tracking-[0.3px] uppercase">
                                                                                    {faq.category}
                                                                                </span>
                                                                                <span className="font-medium tracking-[0.3px]">
                                                                                    Source:{" "}
                                                                                    {faq.source}
                                                                                </span>
                                                                                {/* Protocol badge - US-003 */}
                                                                                <Badge
                                                                                    variant="outline"
                                                                                    data-testid="protocol-badge"
                                                                                    className={`text-[11px] ${
                                                                                        faq.protocol ===
                                                                                        "multisig_v1"
                                                                                            ? "bg-blue-50 text-blue-700 border-blue-300"
                                                                                            : faq.protocol ===
                                                                                                "bisq_easy"
                                                                                              ? "bg-green-50 text-green-700 border-green-300"
                                                                                              : faq.protocol ===
                                                                                                  "musig"
                                                                                                ? "bg-orange-50 text-orange-700 border-orange-300"
                                                                                                : "bg-purple-50 text-purple-700 border-purple-300"
                                                                                    }`}
                                                                                >
                                                                                    {faq.protocol ===
                                                                                    "multisig_v1"
                                                                                        ? "Multisig"
                                                                                        : faq.protocol ===
                                                                                            "bisq_easy"
                                                                                          ? "Bisq Easy"
                                                                                          : faq.protocol ===
                                                                                              "musig"
                                                                                            ? "MuSig"
                                                                                            : "All"}
                                                                                </Badge>
                                                                                {faq.verified ? (
                                                                                    <Tooltip>
                                                                                        <TooltipTrigger
                                                                                            asChild
                                                                                        >
                                                                                            <span
                                                                                                className="inline-flex items-center gap-1 text-green-600 cursor-help"
                                                                                                aria-label="Verified FAQ"
                                                                                            >
                                                                                                <BadgeCheck
                                                                                                    className="h-4 w-4"
                                                                                                    aria-hidden="true"
                                                                                                />
                                                                                                <span className="text-[12px] font-medium tracking-[0.3px] uppercase">
                                                                                                    Verified
                                                                                                </span>
                                                                                            </span>
                                                                                        </TooltipTrigger>
                                                                                        <TooltipContent className="max-w-xs">
                                                                                            <p className="text-sm">
                                                                                                Verified
                                                                                                FAQs
                                                                                                are
                                                                                                marked
                                                                                                as
                                                                                                reviewed
                                                                                                and
                                                                                                approved.
                                                                                                They
                                                                                                receive
                                                                                                higher
                                                                                                priority
                                                                                                in
                                                                                                search
                                                                                                results.
                                                                                            </p>
                                                                                        </TooltipContent>
                                                                                    </Tooltip>
                                                                                ) : (
                                                                                    <Tooltip>
                                                                                        <TooltipTrigger
                                                                                            asChild
                                                                                        >
                                                                                            <span
                                                                                                className="inline-flex items-center gap-1 text-amber-600 cursor-help"
                                                                                                aria-label="Unverified FAQ - Needs Review"
                                                                                            >
                                                                                                <AlertCircle
                                                                                                    className="h-4 w-4"
                                                                                                    aria-hidden="true"
                                                                                                />
                                                                                                <span className="text-[12px] font-medium tracking-[0.3px] uppercase">
                                                                                                    Needs
                                                                                                    Review
                                                                                                </span>
                                                                                            </span>
                                                                                        </TooltipTrigger>
                                                                                        <TooltipContent className="max-w-xs">
                                                                                            <p className="text-sm">
                                                                                                Unverified
                                                                                                FAQs
                                                                                                need
                                                                                                review
                                                                                                before
                                                                                                appearing
                                                                                                in
                                                                                                search
                                                                                                results.
                                                                                                Verify
                                                                                                them
                                                                                                to
                                                                                                mark
                                                                                                as
                                                                                                approved.
                                                                                            </p>
                                                                                        </TooltipContent>
                                                                                    </Tooltip>
                                                                                )}
                                                                            </div>
                                                                        </div>
                                                                    </div>
                                                                </CollapsibleTrigger>
                                                            </div>
                                                        ) : (
                                                            <div
                                                                className="w-full focus-visible:outline-none cursor-pointer"
                                                                tabIndex={0}
                                                                onFocus={() => {
                                                                    // Sync Tab navigation with keyboard selection
                                                                    setSelectedIndex(index);
                                                                }}
                                                                onClick={() => {
                                                                    // Set selection when clicking on FAQ
                                                                    setSelectedIndex(index);
                                                                }}
                                                            >
                                                                <div className="flex items-start justify-between gap-3">
                                                                    {bulkSelectionMode && (
                                                                        <div className="flex items-start pt-1">
                                                                            <Checkbox
                                                                                checked={selectedFaqIds.has(
                                                                                    faq.id
                                                                                )}
                                                                                onCheckedChange={() =>
                                                                                    handleSelectFaq(
                                                                                        faq.id
                                                                                    )
                                                                                }
                                                                                disabled={
                                                                                    isSubmitting
                                                                                }
                                                                                aria-label={`Select FAQ: ${faq.question}`}
                                                                            />
                                                                        </div>
                                                                    )}
                                                                    <div className="flex-1 space-y-2">
                                                                        <div className="flex items-start gap-2">
                                                                            <h3 className="font-medium text-card-foreground text-[15px] leading-[1.4] tracking-tight flex-1">
                                                                                {faq.question}
                                                                            </h3>
                                                                            {hasFailed && (
                                                                                <Badge
                                                                                    variant="destructive"
                                                                                    className="text-[10px]"
                                                                                >
                                                                                    <AlertCircle className="h-3 w-3 mr-1" />
                                                                                    Failed
                                                                                </Badge>
                                                                            )}
                                                                        </div>

                                                                        <div className="flex items-center gap-4 text-[12px] text-muted-foreground">
                                                                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground font-medium text-[12px] tracking-[0.3px] uppercase">
                                                                                {faq.category}
                                                                            </span>
                                                                            <span className="font-medium tracking-[0.3px]">
                                                                                Source: {faq.source}
                                                                            </span>
                                                                            {/* Protocol badge - US-003 */}
                                                                            <Badge
                                                                                variant="outline"
                                                                                data-testid="protocol-badge"
                                                                                className={`text-[11px] ${
                                                                                    faq.protocol ===
                                                                                    "multisig_v1"
                                                                                        ? "bg-blue-50 text-blue-700 border-blue-300"
                                                                                        : faq.protocol ===
                                                                                            "bisq_easy"
                                                                                          ? "bg-green-50 text-green-700 border-green-300"
                                                                                          : faq.protocol ===
                                                                                              "musig"
                                                                                            ? "bg-orange-50 text-orange-700 border-orange-300"
                                                                                            : "bg-purple-50 text-purple-700 border-purple-300"
                                                                                }`}
                                                                            >
                                                                                {faq.protocol ===
                                                                                "multisig_v1"
                                                                                    ? "Multisig"
                                                                                    : faq.protocol ===
                                                                                        "bisq_easy"
                                                                                      ? "Bisq Easy"
                                                                                      : faq.protocol ===
                                                                                          "musig"
                                                                                        ? "MuSig"
                                                                                        : "All"}
                                                                            </Badge>
                                                                            <Tooltip>
                                                                                <TooltipTrigger
                                                                                    asChild
                                                                                >
                                                                                    <span
                                                                                        className="inline-flex items-center gap-1 text-amber-600 cursor-help"
                                                                                        aria-label="Unverified FAQ - Needs Review"
                                                                                    >
                                                                                        <AlertCircle
                                                                                            className="h-4 w-4"
                                                                                            aria-hidden="true"
                                                                                        />
                                                                                        <span className="text-xs font-medium">
                                                                                            Needs
                                                                                            Review
                                                                                        </span>
                                                                                    </span>
                                                                                </TooltipTrigger>
                                                                                <TooltipContent className="max-w-xs">
                                                                                    <p className="text-sm">
                                                                                        Unverified
                                                                                        FAQs need
                                                                                        review
                                                                                        before
                                                                                        appearing in
                                                                                        search
                                                                                        results.
                                                                                        Verify them
                                                                                        to mark as
                                                                                        approved.
                                                                                    </p>
                                                                                </TooltipContent>
                                                                            </Tooltip>
                                                                        </div>
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        )}

                                                        <CollapsibleContent className="pt-3 data-[state=open]:animate-slide-down data-[state=closed]:animate-slide-up overflow-hidden">
                                                            <div className="flex items-start justify-between gap-4">
                                                                <div className="flex-1 space-y-3">
                                                                    <div>
                                                                        <p className="text-muted-foreground text-[14px] leading-[1.6] whitespace-pre-wrap">
                                                                            {faq.answer}
                                                                        </p>
                                                                    </div>

                                                                    {/* Timestamp Information - Compact with Progressive Disclosure */}
                                                                    <div className="pt-2 border-t border-border/40">
                                                                        <Tooltip>
                                                                            <TooltipTrigger asChild>
                                                                                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground cursor-help">
                                                                                    <Clock className="h-3 w-3" />
                                                                                    <span>
                                                                                        {formatTimestamp(
                                                                                            faq.verified_at ||
                                                                                                faq.updated_at ||
                                                                                                faq.created_at
                                                                                        )}
                                                                                    </span>
                                                                                </div>
                                                                            </TooltipTrigger>
                                                                            <TooltipContent
                                                                                side="bottom"
                                                                                align="start"
                                                                                className="text-xs"
                                                                            >
                                                                                <div className="space-y-1">
                                                                                    <div className="flex items-center justify-between gap-3">
                                                                                        <span className="font-medium opacity-70">
                                                                                            Created:
                                                                                        </span>
                                                                                        <span>
                                                                                            {formatTimestamp(
                                                                                                faq.created_at
                                                                                            )}
                                                                                        </span>
                                                                                    </div>
                                                                                    {faq.updated_at &&
                                                                                        faq.updated_at !==
                                                                                            faq.created_at && (
                                                                                            <div className="flex items-center justify-between gap-3">
                                                                                                <span className="font-medium opacity-70">
                                                                                                    Updated:
                                                                                                </span>
                                                                                                <span>
                                                                                                    {formatTimestamp(
                                                                                                        faq.updated_at
                                                                                                    )}
                                                                                                </span>
                                                                                            </div>
                                                                                        )}
                                                                                    {faq.verified_at && (
                                                                                        <div className="flex items-center justify-between gap-3">
                                                                                            <span className="font-medium opacity-70">
                                                                                                Verified:
                                                                                            </span>
                                                                                            <span>
                                                                                                {formatTimestamp(
                                                                                                    faq.verified_at
                                                                                                )}
                                                                                            </span>
                                                                                        </div>
                                                                                    )}
                                                                                </div>
                                                                            </TooltipContent>
                                                                        </Tooltip>
                                                                    </div>
                                                                </div>

                                                                <div
                                                                    className={`flex items-center gap-1 ml-4 transition-opacity duration-200 ${isSelected || "opacity-0 group-hover:opacity-100"}`}
                                                                >
                                                                    {!faq.verified &&
                                                                        (skipVerifyConfirmation ? (
                                                                            <Button
                                                                                variant="outline"
                                                                                size="sm"
                                                                                disabled={
                                                                                    isSubmitting
                                                                                }
                                                                                onClick={() =>
                                                                                    handleVerifyFaq(
                                                                                        faq
                                                                                    )
                                                                                }
                                                                                aria-label={`Verify FAQ: ${faq.question}`}
                                                                            >
                                                                                <BadgeCheck className="h-4 w-4 mr-2" />
                                                                                Verify FAQ
                                                                            </Button>
                                                                        ) : (
                                                                            <AlertDialog>
                                                                                <AlertDialogTrigger
                                                                                    asChild
                                                                                >
                                                                                    <Button
                                                                                        variant="outline"
                                                                                        size="sm"
                                                                                        disabled={
                                                                                            isSubmitting
                                                                                        }
                                                                                        aria-label={`Verify FAQ: ${faq.question}`}
                                                                                    >
                                                                                        <BadgeCheck className="h-4 w-4 mr-2" />
                                                                                        Verify FAQ
                                                                                    </Button>
                                                                                </AlertDialogTrigger>
                                                                                <AlertDialogContent>
                                                                                    <AlertDialogHeader>
                                                                                        <AlertDialogTitle>
                                                                                            Verify
                                                                                            this
                                                                                            FAQ?
                                                                                        </AlertDialogTitle>
                                                                                        <AlertDialogDescription>
                                                                                            This
                                                                                            will
                                                                                            mark
                                                                                            this FAQ
                                                                                            as
                                                                                            verified,
                                                                                            indicating
                                                                                            it has
                                                                                            been
                                                                                            reviewed
                                                                                            and
                                                                                            approved
                                                                                            by a
                                                                                            Bisq
                                                                                            Support
                                                                                            Admin.
                                                                                            This
                                                                                            action
                                                                                            is
                                                                                            irreversible.
                                                                                        </AlertDialogDescription>
                                                                                    </AlertDialogHeader>
                                                                                    <div className="flex items-center space-x-2 px-6 pb-4">
                                                                                        <Checkbox
                                                                                            id={`do-not-show-again-${faq.id}`}
                                                                                            checked={
                                                                                                doNotShowAgain
                                                                                            }
                                                                                            onCheckedChange={(
                                                                                                checked
                                                                                            ) =>
                                                                                                setDoNotShowAgain(
                                                                                                    checked ===
                                                                                                        true
                                                                                                )
                                                                                            }
                                                                                        />
                                                                                        <Label
                                                                                            htmlFor={`do-not-show-again-${faq.id}`}
                                                                                            className="text-sm font-normal cursor-pointer"
                                                                                        >
                                                                                            Do not
                                                                                            show
                                                                                            this
                                                                                            confirmation
                                                                                            again
                                                                                        </Label>
                                                                                    </div>
                                                                                    <AlertDialogFooter>
                                                                                        <AlertDialogCancel
                                                                                            onClick={() =>
                                                                                                setDoNotShowAgain(
                                                                                                    false
                                                                                                )
                                                                                            }
                                                                                        >
                                                                                            Cancel
                                                                                        </AlertDialogCancel>
                                                                                        <AlertDialogAction
                                                                                            onClick={() => {
                                                                                                if (
                                                                                                    doNotShowAgain
                                                                                                ) {
                                                                                                    localStorage.setItem(
                                                                                                        "skipVerifyFaqConfirmation",
                                                                                                        "true"
                                                                                                    );
                                                                                                    setSkipVerifyConfirmation(
                                                                                                        true
                                                                                                    );
                                                                                                }
                                                                                                setDoNotShowAgain(
                                                                                                    false
                                                                                                );
                                                                                                handleVerifyFaq(
                                                                                                    faq
                                                                                                );
                                                                                            }}
                                                                                            className="!bg-green-600 hover:!bg-green-700"
                                                                                            disabled={
                                                                                                isSubmitting
                                                                                            }
                                                                                            aria-label={`Verify FAQ: ${faq.question}`}
                                                                                        >
                                                                                            {isSubmitting ? (
                                                                                                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                                                                            ) : null}
                                                                                            Verify
                                                                                            FAQ
                                                                                        </AlertDialogAction>
                                                                                    </AlertDialogFooter>
                                                                                </AlertDialogContent>
                                                                            </AlertDialog>
                                                                        ))}
                                                                    <Button
                                                                        variant="ghost"
                                                                        size="icon"
                                                                        onClick={() =>
                                                                            enterEditMode(faq)
                                                                        }
                                                                        className="h-8 w-8"
                                                                        data-testid="edit-faq-button"
                                                                    >
                                                                        <Pencil className="h-4 w-4" />
                                                                    </Button>
                                                                    <AlertDialog>
                                                                        <AlertDialogTrigger asChild>
                                                                            <Button
                                                                                variant="ghost"
                                                                                size="icon"
                                                                                disabled={
                                                                                    isSubmitting
                                                                                }
                                                                                className="h-8 w-8"
                                                                                data-testid="delete-faq-button"
                                                                            >
                                                                                <Trash2 className="h-4 w-4 text-red-500" />
                                                                            </Button>
                                                                        </AlertDialogTrigger>
                                                                        <AlertDialogContent>
                                                                            <AlertDialogHeader>
                                                                                <AlertDialogTitle>
                                                                                    Are you
                                                                                    absolutely sure?
                                                                                </AlertDialogTitle>
                                                                                <AlertDialogDescription>
                                                                                    This action
                                                                                    cannot be
                                                                                    undone. This
                                                                                    will permanently
                                                                                    delete this FAQ.
                                                                                </AlertDialogDescription>
                                                                            </AlertDialogHeader>
                                                                            <AlertDialogFooter>
                                                                                <AlertDialogCancel>
                                                                                    Cancel
                                                                                </AlertDialogCancel>
                                                                                <AlertDialogAction
                                                                                    onClick={() =>
                                                                                        handleDelete(
                                                                                            faq.id
                                                                                        )
                                                                                    }
                                                                                >
                                                                                    Continue
                                                                                </AlertDialogAction>
                                                                            </AlertDialogFooter>
                                                                        </AlertDialogContent>
                                                                    </AlertDialog>
                                                                </div>
                                                            </div>
                                                        </CollapsibleContent>
                                                    </div>
                                                </Collapsible>
                                            </motion.div>
                                        );
                                    })}
                                </div>
                            )}

                            {/* Empty State */}
                            {displayFaqs && displayFaqs.faqs.length === 0 && !isLoading && (
                                <div className="flex flex-col items-center justify-center py-16 px-4">
                                    <div className="w-24 h-24 rounded-full bg-muted flex items-center justify-center mb-4">
                                        <FileQuestion className="w-12 h-12 text-muted-foreground" />
                                    </div>
                                    <h3 className="text-xl font-semibold mb-2">No FAQs found</h3>
                                    <p className="text-muted-foreground text-center max-w-sm mb-6">
                                        {filters.search_text ||
                                        filters.categories.length > 0 ||
                                        filters.source
                                            ? "No FAQs match your current filters. Try adjusting your search criteria."
                                            : "Get started by creating your first FAQ. You can add questions manually or import them from support chats."}
                                    </p>
                                    <div className="flex gap-3">
                                        <Button onClick={openNewFaqForm}>
                                            <PlusCircle className="mr-2 h-4 w-4" />
                                            Create FAQ
                                        </Button>
                                        {(filters.search_text ||
                                            filters.categories.length > 0 ||
                                            filters.source) && (
                                            <Button variant="outline" onClick={clearAllFilters}>
                                                <RotateCcw className="mr-2 h-4 w-4" />
                                                Clear Filters
                                            </Button>
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Pagination Controls */}
                            {displayFaqs && displayFaqs.faqs.length > 0 && (
                                <div className="flex items-center justify-between px-2 py-4">
                                    <div className="flex items-center space-x-6 lg:space-x-8">
                                        <div className="flex items-center space-x-2">
                                            <p className="text-sm font-medium">
                                                Showing{" "}
                                                {(faqData!.page - 1) * faqData!.page_size + 1} to{" "}
                                                {Math.min(
                                                    faqData!.page * faqData!.page_size,
                                                    faqData!.total_count
                                                )}{" "}
                                                of {faqData!.total_count} entries
                                            </p>
                                        </div>
                                    </div>
                                    {/* Show pagination controls when there are multiple pages */}
                                    {faqData && faqData.total_pages > 1 && (
                                        <div className="flex items-center space-x-2">
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => handlePageChange(currentPage - 1)}
                                                disabled={currentPage <= 1}
                                            >
                                                Previous
                                            </Button>
                                            <div className="flex items-center space-x-1">
                                                {Array.from(
                                                    { length: Math.min(5, faqData.total_pages) },
                                                    (_, i) => {
                                                        const pageNum =
                                                            Math.max(
                                                                1,
                                                                Math.min(
                                                                    faqData.total_pages - 4,
                                                                    currentPage - 2
                                                                )
                                                            ) + i;
                                                        if (pageNum > faqData.total_pages)
                                                            return null;
                                                        return (
                                                            <Button
                                                                key={pageNum}
                                                                variant={
                                                                    pageNum === currentPage
                                                                        ? "default"
                                                                        : "outline"
                                                                }
                                                                size="sm"
                                                                onClick={() =>
                                                                    handlePageChange(pageNum)
                                                                }
                                                                className="w-8 h-8 p-0"
                                                            >
                                                                {pageNum}
                                                            </Button>
                                                        );
                                                    }
                                                )}
                                            </div>
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                onClick={() => handlePageChange(currentPage + 1)}
                                                disabled={currentPage >= faqData.total_pages}
                                            >
                                                Next
                                            </Button>
                                        </div>
                                    )}
                                </div>
                            )}
                        </CardContent>
                    </Card>

                    {/* Command Palette */}
                    <CommandDialog open={commandPaletteOpen} onOpenChange={setCommandPaletteOpen}>
                        <CommandInput placeholder="Type a command or search..." />
                        <CommandList>
                            <CommandEmpty>No results found.</CommandEmpty>
                            <CommandGroup heading="Actions">
                                <CommandItem
                                    onSelect={() => {
                                        openNewFaqForm();
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <PlusCircle className="mr-2 h-4 w-4" />
                                    <span>Add New FAQ</span>
                                    <CommandShortcut>N</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        setBulkSelectionMode(!bulkSelectionMode);
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <CheckSquare className="mr-2 h-4 w-4" />
                                    <span>
                                        {bulkSelectionMode ? "Exit" : "Enable"} Bulk Selection
                                    </span>
                                    <CommandShortcut>B</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        searchInputRef.current?.focus();
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <Search className="mr-2 h-4 w-4" />
                                    <span>Focus Search</span>
                                    <CommandShortcut>/</CommandShortcut>
                                </CommandItem>
                            </CommandGroup>
                            <CommandSeparator />
                            <CommandGroup heading="Filters">
                                <CommandItem
                                    onSelect={() => {
                                        setFilters((prev) => ({
                                            ...prev,
                                            categories: [],
                                            source: "",
                                        }));
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <X className="mr-2 h-4 w-4" />
                                    <span>Reset All Filters</span>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        setFilters((prev) => ({
                                            ...prev,
                                            categories: ["general"],
                                        }));
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <span>Filter: General</span>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        setFilters((prev) => ({
                                            ...prev,
                                            categories: ["technical"],
                                        }));
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <span>Filter: Technical</span>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        setFilters((prev) => ({
                                            ...prev,
                                            categories: ["trading"],
                                        }));
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <span>Filter: Trading</span>
                                </CommandItem>
                            </CommandGroup>
                            <CommandSeparator />
                            <CommandGroup heading="FAQ Navigation">
                                <CommandItem disabled>
                                    <span>Navigate Down</span>
                                    <CommandShortcut>J</CommandShortcut>
                                </CommandItem>
                                <CommandItem disabled>
                                    <span>Navigate Up</span>
                                    <CommandShortcut>K</CommandShortcut>
                                </CommandItem>
                                <CommandItem disabled>
                                    <span>Expand/Collapse Selected</span>
                                    <CommandShortcut>Enter</CommandShortcut>
                                </CommandItem>
                            </CommandGroup>
                            <CommandSeparator />
                            <CommandGroup heading="FAQ Actions">
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            enterEditMode(displayFaqs.faqs[selectedIndex]);
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <Pencil className="mr-2 h-4 w-4" />
                                    <span>Edit Selected FAQ</span>
                                    <CommandShortcut>Enter</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            const selectedFaq = displayFaqs.faqs[selectedIndex];
                                            setFaqToDelete(selectedFaq);
                                            setShowDeleteConfirmDialog(true);
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <Trash2 className="mr-2 h-4 w-4" />
                                    <span>Delete Selected FAQ</span>
                                    <CommandShortcut>D</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            const selectedFaq = displayFaqs.faqs[selectedIndex];
                                            if (!selectedFaq.verified) {
                                                if (skipVerifyConfirmation) {
                                                    handleVerifyFaq(selectedFaq);
                                                } else {
                                                    const verifyButton = document.querySelector(
                                                        `button[aria-label="Verify FAQ: ${selectedFaq.question}"]`
                                                    ) as HTMLButtonElement;
                                                    if (verifyButton) {
                                                        verifyButton.click();
                                                    }
                                                }
                                            }
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <BadgeCheck className="mr-2 h-4 w-4" />
                                    <span>Verify Selected FAQ</span>
                                    <CommandShortcut>V</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        setSelectedIndex(-1);
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <X className="mr-2 h-4 w-4" />
                                    <span>Clear Selection</span>
                                    <CommandShortcut>Esc</CommandShortcut>
                                </CommandItem>
                            </CommandGroup>
                            <CommandSeparator />
                            <CommandGroup heading="Set Protocol">
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            handleSetProtocol(
                                                displayFaqs.faqs[selectedIndex],
                                                "bisq_easy"
                                            );
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <Badge
                                        variant="outline"
                                        className="mr-2 h-4 border-emerald-500/50 bg-emerald-500/10 text-emerald-500 text-[10px] px-1"
                                    >
                                        Easy
                                    </Badge>
                                    <span>Bisq Easy</span>
                                    <CommandShortcut>E</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            handleSetProtocol(
                                                displayFaqs.faqs[selectedIndex],
                                                "multisig_v1"
                                            );
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <Badge
                                        variant="outline"
                                        className="mr-2 h-4 border-blue-500/50 bg-blue-500/10 text-blue-500 text-[10px] px-1"
                                    >
                                        Multisig
                                    </Badge>
                                    <span>Multisig</span>
                                    <CommandShortcut>1</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            handleSetProtocol(
                                                displayFaqs.faqs[selectedIndex],
                                                "musig"
                                            );
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <Badge
                                        variant="outline"
                                        className="mr-2 h-4 border-purple-500/50 bg-purple-500/10 text-purple-500 text-[10px] px-1"
                                    >
                                        MuSig
                                    </Badge>
                                    <span>MuSig</span>
                                    <CommandShortcut>M</CommandShortcut>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        if (
                                            selectedIndex >= 0 &&
                                            displayFaqs?.faqs[selectedIndex]
                                        ) {
                                            handleSetProtocol(
                                                displayFaqs.faqs[selectedIndex],
                                                "all"
                                            );
                                        }
                                        setCommandPaletteOpen(false);
                                    }}
                                    disabled={selectedIndex < 0}
                                >
                                    <Badge
                                        variant="outline"
                                        className="mr-2 h-4 border-blue-500/50 bg-blue-500/10 text-blue-500 text-[10px] px-1"
                                    >
                                        All
                                    </Badge>
                                    <span>All Protocols</span>
                                    <CommandShortcut>0</CommandShortcut>
                                </CommandItem>
                            </CommandGroup>
                            <CommandSeparator />
                            <CommandGroup heading="Navigation">
                                <CommandItem
                                    onSelect={() => {
                                        window.location.href = "/admin/dashboard";
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <span>Go to Dashboard</span>
                                </CommandItem>
                                <CommandItem
                                    onSelect={() => {
                                        window.location.href = "/admin/feedback";
                                        setCommandPaletteOpen(false);
                                    }}
                                >
                                    <span>Go to Feedback</span>
                                </CommandItem>
                            </CommandGroup>
                        </CommandList>
                    </CommandDialog>

                    {/* Shared Delete Confirmation Dialog (for keyboard shortcut) */}
                    <AlertDialog
                        open={showDeleteConfirmDialog}
                        onOpenChange={setShowDeleteConfirmDialog}
                    >
                        <AlertDialogContent>
                            <AlertDialogHeader>
                                <AlertDialogTitle>Are you absolutely sure?</AlertDialogTitle>
                                <AlertDialogDescription>
                                    This action cannot be undone. This will permanently delete this
                                    FAQ.
                                </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                                <AlertDialogCancel onClick={() => setFaqToDelete(null)}>
                                    Cancel
                                </AlertDialogCancel>
                                <AlertDialogAction
                                    onClick={async () => {
                                        if (faqToDelete) {
                                            setShowDeleteConfirmDialog(false);
                                            // Find the index for smart selection
                                            const index = displayFaqs?.faqs.findIndex(
                                                (f) => f.id === faqToDelete.id
                                            );
                                            if (index !== undefined && index >= 0) {
                                                await handleDeleteWithSmartSelection(index);
                                            }
                                            setFaqToDelete(null);
                                        }
                                    }}
                                >
                                    Continue
                                </AlertDialogAction>
                            </AlertDialogFooter>
                        </AlertDialogContent>
                    </AlertDialog>
                </div>
            </div>
        </TooltipProvider>
    );
}
