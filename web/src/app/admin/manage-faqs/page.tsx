"use client";

import { useState, useEffect, useRef, FormEvent, useMemo, memo, useCallback } from "react";
import { motion } from "framer-motion";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { VectorStoreStatusBanner } from "@/components/admin/VectorStoreStatusBanner";
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
import { format } from "date-fns";
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
    bisq_version?: "Bisq 1" | "Bisq 2" | "General";
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
    }: InlineEditFAQProps) => {
        const draft = draftEdits.get(faq.id);
        const currentValues = draft ? { ...faq, ...draft } : faq;
        const [isSubmitting, setIsSubmitting] = useState(false);
        const questionInputRef = useRef<HTMLInputElement>(null);

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
                        onChange={(e) => updateDraft({ question: e.target.value })}
                        placeholder="Question"
                        className="text-lg font-semibold"
                    />
                </CardHeader>
                <CardContent className="space-y-4">
                    <Textarea
                        value={currentValues.answer}
                        onChange={(e) => updateDraft({ answer: e.target.value })}
                        placeholder="Answer"
                        rows={6}
                    />

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
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
                    </div>

                    <div className="flex gap-2">
                        <Button
                            onClick={handleSubmit}
                            disabled={isSubmitting}
                            className="min-w-[80px]"
                        >
                            {isSubmitting ? (
                                <>
                                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    Saving
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
        bisq_version: "Bisq 2" as "Bisq 1" | "Bisq 2" | "General",
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
        bisq_version: "",
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

    // Enter edit mode (e key)
    useHotkeys(
        "e",
        (e) => {
            e.preventDefault();
            if (!editingFaqId && selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                enterEditMode(displayFaqs.faqs[selectedIndex]);
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

    // Toggle expand/collapse with Enter
    useHotkeys(
        "enter",
        (e) => {
            if (selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                e.preventDefault();
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                if (selectedFaq.verified) {
                    setExpandedIds((prev) => {
                        const newSet = new Set(prev);
                        if (newSet.has(selectedFaq.id)) {
                            newSet.delete(selectedFaq.id);
                        } else {
                            newSet.add(selectedFaq.id);
                        }
                        return newSet;
                    });
                }
            }
        },
        { enableOnFormTags: false },
        [selectedIndex, displayFaqs]
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

                if (filters.bisq_version && filters.bisq_version.trim()) {
                    params.append("bisq_version", filters.bisq_version.trim());
                }

                if (filters.verified_from) {
                    // Set to start of day in UTC (00:00:00)
                    const startOfDay = new Date(filters.verified_from);
                    startOfDay.setUTCHours(0, 0, 0, 0);
                    params.append("verified_from", format(startOfDay, "yyyy-MM-dd'T'HH:mm:ss'Z'"));
                }

                if (filters.verified_to) {
                    // Set to end of day in UTC (23:59:59)
                    const endOfDay = new Date(filters.verified_to);
                    endOfDay.setUTCHours(23, 59, 59, 999);
                    params.append("verified_to", format(endOfDay, "yyyy-MM-dd'T'HH:mm:ss'Z'"));
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
                    bisq_version: "Bisq 2",
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
            bisq_version: "Bisq 2",
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

            // Move to next FAQ
            const currentIdx =
                displayFaqs?.faqs.findIndex((f) => f.id === updatedFaqFromApi.id) ?? -1;
            if (currentIdx >= 0 && displayFaqs) {
                const nextIndex = Math.min(currentIdx + 1, displayFaqs.faqs.length - 1);
                setSelectedIndex(nextIndex);
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
            bisq_version: "",
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
        filters.bisq_version ||
        filters.verified_from ||
        filters.verified_to;

    return (
        <TooltipProvider>
            <div className="min-h-screen bg-background">
                {/* Persistent banner at top */}
                <VectorStoreStatusBanner />

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

                                    {/* Bisq Version */}
                                    <div className="space-y-2">
                                        <Label htmlFor="bisq-version-filter">Bisq Version</Label>
                                        <Select
                                            value={filters.bisq_version || "all"}
                                            onValueChange={(value) => {
                                                setFilters({
                                                    ...filters,
                                                    bisq_version: value === "all" ? "" : value,
                                                });
                                                setCurrentPage(1);
                                            }}
                                        >
                                            <SelectTrigger id="bisq-version-filter">
                                                <SelectValue placeholder="All Versions" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="all">All Versions</SelectItem>
                                                <SelectItem value="Bisq 1">Bisq 1</SelectItem>
                                                <SelectItem value="Bisq 2">Bisq 2</SelectItem>
                                                <SelectItem value="General">General</SelectItem>
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
                                                disabled={false}
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
                                                disabled={false}
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
                                                        filters.bisq_version &&
                                                        filters.bisq_version.trim()
                                                    ) {
                                                        params.append(
                                                            "bisq_version",
                                                            filters.bisq_version.trim()
                                                        );
                                                    }

                                                    if (filters.verified_from) {
                                                        // Set to start of day in UTC (00:00:00)
                                                        const startOfDay = new Date(
                                                            filters.verified_from
                                                        );
                                                        startOfDay.setUTCHours(0, 0, 0, 0);
                                                        params.append(
                                                            "verified_from",
                                                            format(
                                                                startOfDay,
                                                                "yyyy-MM-dd'T'HH:mm:ss'Z'"
                                                            )
                                                        );
                                                    }

                                                    if (filters.verified_to) {
                                                        // Set to end of day in UTC (23:59:59)
                                                        const endOfDay = new Date(
                                                            filters.verified_to
                                                        );
                                                        endOfDay.setUTCHours(23, 59, 59, 999);
                                                        params.append(
                                                            "verified_to",
                                                            format(
                                                                endOfDay,
                                                                "yyyy-MM-dd'T'HH:mm:ss'Z'"
                                                            )
                                                        );
                                                    }

                                                    // Fetch CSV via server-side streaming endpoint
                                                    // Authentication handled via cookies in makeAuthenticatedRequest
                                                    const exportUrl = `${API_BASE_URL}/admin/faqs/export?${params.toString()}`;
                                                    const response =
                                                        await makeAuthenticatedRequest(exportUrl);

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
                                                    filters.bisq_version && "Bisq version",
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
                                            required
                                        />
                                    </div>
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
                                        <Label htmlFor="bisq-version">Bisq Version</Label>
                                        <Select
                                            value={formData.bisq_version}
                                            onValueChange={(value) =>
                                                setFormData({
                                                    ...formData,
                                                    bisq_version: value as
                                                        | "Bisq 1"
                                                        | "Bisq 2"
                                                        | "General",
                                                })
                                            }
                                        >
                                            <SelectTrigger id="bisq-version">
                                                <SelectValue placeholder="Select version" />
                                            </SelectTrigger>
                                            <SelectContent>
                                                <SelectItem value="Bisq 2">
                                                    Bisq 2 (Default)
                                                </SelectItem>
                                                <SelectItem value="Bisq 1">Bisq 1</SelectItem>
                                                <SelectItem value="General">
                                                    General (All Versions)
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
                                                                                {faq.bisq_version && (
                                                                                    <Badge
                                                                                        variant="outline"
                                                                                        className={`text-[11px] ${
                                                                                            faq.bisq_version ===
                                                                                            "Bisq 1"
                                                                                                ? "bg-blue-50 text-blue-700 border-blue-300"
                                                                                                : faq.bisq_version ===
                                                                                                    "Bisq 2"
                                                                                                  ? "bg-green-50 text-green-700 border-green-300"
                                                                                                  : faq.bisq_version ===
                                                                                                      "Both"
                                                                                                    ? "bg-purple-50 text-purple-700 border-purple-300"
                                                                                                    : "bg-gray-50 text-gray-700 border-gray-300"
                                                                                        }`}
                                                                                    >
                                                                                        {
                                                                                            faq.bisq_version
                                                                                        }
                                                                                    </Badge>
                                                                                )}
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
                                                                            {faq.bisq_version && (
                                                                                <Badge
                                                                                    variant="outline"
                                                                                    className={`text-[11px] ${
                                                                                        faq.bisq_version ===
                                                                                        "Bisq 1"
                                                                                            ? "bg-blue-50 text-blue-700 border-blue-300"
                                                                                            : faq.bisq_version ===
                                                                                                "Bisq 2"
                                                                                              ? "bg-green-50 text-green-700 border-green-300"
                                                                                              : faq.bisq_version ===
                                                                                                  "Both"
                                                                                                ? "bg-purple-50 text-purple-700 border-purple-300"
                                                                                                : "bg-gray-50 text-gray-700 border-gray-300"
                                                                                    }`}
                                                                                >
                                                                                    {
                                                                                        faq.bisq_version
                                                                                    }
                                                                                </Badge>
                                                                            )}
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
                                <CommandItem disabled>
                                    <span>Edit Selected FAQ</span>
                                    <CommandShortcut>E</CommandShortcut>
                                </CommandItem>
                                <CommandItem disabled>
                                    <span>Delete Selected FAQ</span>
                                    <CommandShortcut>D</CommandShortcut>
                                </CommandItem>
                                <CommandItem disabled>
                                    <span>Verify Selected FAQ</span>
                                    <CommandShortcut>V</CommandShortcut>
                                </CommandItem>
                                <CommandItem disabled>
                                    <span>Clear Selection</span>
                                    <CommandShortcut>Esc</CommandShortcut>
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
