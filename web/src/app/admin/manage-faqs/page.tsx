"use client";

import { useState, useEffect, useRef, FormEvent, useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    CardFooter,
    CardDescription,
} from "@/components/ui/card";
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
    ChevronDown,
    ChevronRight,
    AlertCircle,
    CheckSquare,
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
import {
    CommandDialog,
    CommandEmpty,
    CommandGroup,
    CommandInput,
    CommandItem,
    CommandList,
    CommandSeparator,
    CommandShortcut,
} from "@/components/ui/command";
import {
    Sheet,
    SheetContent,
    SheetDescription,
    SheetFooter,
    SheetHeader,
    SheetTitle,
} from "@/components/ui/sheet";
import { makeAuthenticatedRequest } from "@/lib/auth";
import debounce from "lodash.debounce";
import { useToast } from "@/hooks/use-toast";

interface FAQ {
    id: string;
    question: string;
    answer: string;
    category: string;
    source: string;
    verified: boolean;
}

interface FAQListResponse {
    faqs: FAQ[];
    total_count: number;
    page: number;
    page_size: number;
    total_pages: number;
}

export default function ManageFaqsPage() {
    const { toast } = useToast();
    const [faqData, setFaqData] = useState<FAQListResponse | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [isFormOpen, setIsFormOpen] = useState(false);
    const [editingFaq, setEditingFaq] = useState<FAQ | null>(null);
    const [formData, setFormData] = useState({
        question: "",
        answer: "",
        category: "",
        source: "Manual",
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
    });

    // Available categories and sources from the data
    const [availableCategories, setAvailableCategories] = useState<string[]>([]);
    const [availableSources, setAvailableSources] = useState<string[]>([]);

    // "Do not show again" state for verify FAQ confirmation
    const [skipVerifyConfirmation, setSkipVerifyConfirmation] = useState(false);
    const [doNotShowAgain, setDoNotShowAgain] = useState(false);

    // Collapsible state - track which FAQs are manually expanded
    const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());

    // Bulk selection state
    const [bulkSelectionMode, setBulkSelectionMode] = useState(false);
    const [selectedFaqIds, setSelectedFaqIds] = useState<Set<string>>(new Set());

    // Command Palette state
    const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);

    // Keyboard navigation state
    const [selectedIndex, setSelectedIndex] = useState<number>(-1);

    const currentPageRef = useRef(currentPage);
    const previousDataHashRef = useRef<string>("");
    const savedScrollPositionRef = useRef<number | null>(null);
    const searchInputRef = useRef<HTMLInputElement>(null);
    const faqRefs = useRef<Map<string, HTMLDivElement>>(new Map());

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
    }, []);

    // Re-fetch data when filters change
    useEffect(() => {
        setCurrentPage(1); // Reset to first page when filters change
        fetchFaqs(1);

        // Auto-refresh every 30 seconds (background refresh - no loading spinner)
        const intervalId = setInterval(() => {
            fetchFaqs(currentPageRef.current, true);
        }, 30000);

        // Cleanup interval on unmount
        return () => clearInterval(intervalId);
    }, [filters]);

    // Keyboard shortcuts (⌘K for Command Palette, /, N, B, j/k navigation, Enter, e/d/v, Escape)
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            const activeElement = document.activeElement;
            const isInputFocused =
                activeElement?.tagName === "INPUT" ||
                activeElement?.tagName === "TEXTAREA" ||
                activeElement?.getAttribute("contenteditable") === "true";

            // ⌘K / Ctrl+K - Open Command Palette (works everywhere)
            if ((e.metaKey || e.ctrlKey) && e.key === "k") {
                e.preventDefault();
                setCommandPaletteOpen(true);
                return;
            }

            // Skip other shortcuts if user is typing in an input field
            if (isInputFocused) return;

            const faqCount = faqData?.faqs.length || 0;

            switch (e.key.toLowerCase()) {
                case "/":
                    // / - Focus search
                    e.preventDefault();
                    searchInputRef.current?.focus();
                    break;

                case "j":
                    // j - Navigate down FAQ list (vim-style)
                    e.preventDefault();
                    if (faqCount > 0) {
                        setSelectedIndex((prev) => {
                            const next = prev < faqCount - 1 ? prev + 1 : prev;
                            return next;
                        });
                    }
                    break;

                case "k":
                    // k - Navigate up FAQ list (vim-style)
                    e.preventDefault();
                    if (faqCount > 0) {
                        setSelectedIndex((prev) => {
                            const next =
                                prev > 0 ? prev - 1 : prev === -1 && faqCount > 0 ? 0 : prev;
                            return next;
                        });
                    }
                    break;

                case "enter":
                    // Enter - Expand/collapse selected FAQ
                    if (selectedIndex >= 0 && selectedIndex < faqCount) {
                        e.preventDefault();
                        const selectedFaq = faqData?.faqs[selectedIndex];
                        if (selectedFaq && selectedFaq.verified) {
                            // Toggle expansion for verified FAQs
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
                    break;

                case "e":
                    // e - Edit selected FAQ
                    if (selectedIndex >= 0 && selectedIndex < faqCount) {
                        e.preventDefault();
                        const selectedFaq = faqData?.faqs[selectedIndex];
                        if (selectedFaq) {
                            handleEdit(selectedFaq);
                        }
                    }
                    break;

                case "d":
                    // d - Delete selected FAQ (with confirmation)
                    if (selectedIndex >= 0 && selectedIndex < faqCount) {
                        e.preventDefault();
                        const selectedFaq = faqData?.faqs[selectedIndex];
                        if (selectedFaq) {
                            handleDelete(selectedFaq);
                        }
                    }
                    break;

                case "v":
                    // v - Verify selected FAQ
                    if (selectedIndex >= 0 && selectedIndex < faqCount) {
                        e.preventDefault();
                        const selectedFaq = faqData?.faqs[selectedIndex];
                        if (selectedFaq && !selectedFaq.verified) {
                            handleVerifyFaq(selectedFaq);
                        }
                    }
                    break;

                case "n":
                    // N - Add new FAQ
                    e.preventDefault();
                    openNewFaqForm();
                    break;

                case "b":
                    // B - Toggle bulk selection mode
                    e.preventDefault();
                    setBulkSelectionMode(!bulkSelectionMode);
                    if (bulkSelectionMode) {
                        setSelectedFaqIds([]);
                    }
                    break;

                case "escape":
                    // Escape - Exit bulk selection mode or close forms or clear selection
                    if (bulkSelectionMode) {
                        e.preventDefault();
                        setBulkSelectionMode(false);
                        setSelectedFaqIds([]);
                    } else if (isFormOpen) {
                        e.preventDefault();
                        setIsFormOpen(false);
                        setEditingFaq(null);
                    } else if (selectedIndex >= 0) {
                        e.preventDefault();
                        setSelectedIndex(-1);
                    }
                    break;

                case "delete":
                case "backspace":
                    // Delete/Backspace - Delete selected FAQs in bulk mode
                    if (bulkSelectionMode && selectedFaqIds.length > 0) {
                        e.preventDefault();
                        handleBulkDelete();
                    }
                    break;
            }
        };

        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [
        bulkSelectionMode,
        selectedFaqIds,
        isFormOpen,
        editingFaq,
        selectedIndex,
        faqData,
        expandedIds,
    ]);

    // Scroll selected FAQ into view when selection changes
    useEffect(() => {
        if (selectedIndex >= 0 && faqData?.faqs[selectedIndex]) {
            const selectedFaq = faqData.faqs[selectedIndex];
            const element = faqRefs.current.get(selectedFaq.id);
            if (element) {
                element.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                });
            }
        }
    }, [selectedIndex, faqData]);

    // Reset selected index when FAQ data changes (pagination, filtering, etc.)
    useEffect(() => {
        setSelectedIndex(-1);
    }, [currentPage, filters]);

    const fetchFaqs = async (page = 1, isBackgroundRefresh = false) => {
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

            if (filters.search_text) {
                params.append("search_text", filters.search_text);
            }

            if (filters.categories.length > 0) {
                params.append("categories", filters.categories.join(","));
            }

            if (filters.source) {
                params.append("source", filters.source);
            }

            const response = await makeAuthenticatedRequest(`/admin/faqs?${params.toString()}`);
            if (response.ok) {
                const data = await response.json();

                // Calculate hash of new data for comparison
                const dataHash = JSON.stringify(data);

                // Only update state if data has actually changed
                if (dataHash !== previousDataHashRef.current) {
                    previousDataHashRef.current = dataHash;
                    setFaqData(data);
                    setError(null);

                    // Extract unique categories and sources for filter options
                    if (data.faqs) {
                        const categories = [
                            ...new Set(data.faqs.map((faq: FAQ) => faq.category).filter(Boolean)),
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
    };

    const handleFormSubmit = async (e: FormEvent) => {
        e.preventDefault();
        setIsSubmitting(true);
        const endpoint = editingFaq ? `/admin/faqs/${editingFaq.id}` : `/admin/faqs`;
        const method = editingFaq ? "PUT" : "POST";

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
                setEditingFaq(null);
                setFormData({ question: "", answer: "", category: "", source: "Manual" });
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

    const handleEdit = (faq: FAQ) => {
        setEditingFaq(faq);
        setFormData({
            question: faq.question,
            answer: faq.answer,
            category: faq.category,
            source: faq.source,
        });
        setIsFormOpen(true);
    };

    const handleDelete = async (id: string) => {
        setIsSubmitting(true);
        try {
            const response = await makeAuthenticatedRequest(`/admin/faqs/${id}`, {
                method: "DELETE",
            });

            if (response.ok) {
                await fetchFaqs(currentPage);
                setError(null);
            } else {
                const errorText = `Failed to delete FAQ. Status: ${response.status}`;
                console.error(errorText);
                setError(errorText);
            }
        } catch (error) {
            const errorText = "An unexpected error occurred while deleting the FAQ.";
            console.error(errorText, error);
            setError(errorText);
        } finally {
            setIsSubmitting(false);
        }
    };

    const handleVerifyFaq = async (faq: FAQ) => {
        setIsSubmitting(true);
        try {
            const response = await makeAuthenticatedRequest(`/admin/faqs/${faq.id}/verify`, {
                method: "PATCH",
            });

            if (response.ok) {
                await fetchFaqs(currentPage, true);
                setError(null);
            } else {
                const errorText = `Failed to verify FAQ. Status: ${response.status}`;
                console.error(errorText);
                setError(errorText);
            }
        } catch (error) {
            const errorText = "An unexpected error occurred while verifying FAQ.";
            console.error(errorText, error);
            setError(errorText);
        } finally {
            setIsSubmitting(false);
        }
    };

    // Bulk action handlers
    const handleSelectAll = () => {
        if (!faqData) return;
        if (selectedFaqIds.size === faqData.faqs.length) {
            setSelectedFaqIds(new Set());
        } else {
            setSelectedFaqIds(new Set(faqData.faqs.map((faq) => faq.id)));
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
        const deletedFaqs = faqData?.faqs.filter((faq) => selectedFaqIds.has(faq.id)) || [];

        // Show loading toast with vector store rebuild info
        toast({
            title: "Deleting FAQs...",
            description: `Removing ${deletingIds.length} FAQ${deletingIds.length > 1 ? "s" : ""}. The knowledge base will be rebuilt after deletion.`,
        });

        // Optimistic update: Remove FAQs from UI immediately
        setFaqData((prev) => {
            if (!prev) return prev;
            return {
                ...prev,
                faqs: prev.faqs.filter((faq) => !selectedFaqIds.has(faq.id)),
                total_count: prev.total_count - selectedFaqIds.size,
            };
        });
        setSelectedFaqIds(new Set());
        setIsSubmitting(true);

        try {
            // Use bulk delete endpoint with single vector store rebuild
            const response = await makeAuthenticatedRequest("/admin/faqs/bulk-delete", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ faq_ids: deletingIds }),
            });

            const result = await response.json();

            // Refresh data to get accurate count and any other changes
            await fetchFaqs(currentPage, true);
            setError(null);

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
        } finally {
            setIsSubmitting(false);
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
        setIsSubmitting(true);

        try {
            // Use bulk verify endpoint with single vector store rebuild
            const response = await makeAuthenticatedRequest("/admin/faqs/bulk-verify", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ faq_ids: verifyingIds }),
            });

            const result = await response.json();

            // Success - refresh data to get any other changes
            await fetchFaqs(currentPage, true);
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
        } finally {
            setIsSubmitting(false);
        }
    };

    const openNewFaqForm = () => {
        setEditingFaq(null);
        setFormData({ question: "", answer: "", category: "", source: "Manual" });
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
        });
        // Also clear the input field value
        if (searchInputRef.current) {
            searchInputRef.current.value = "";
        }
    };

    const hasActiveFilters = filters.search_text || filters.categories.length > 0 || filters.source;

    return (
        <div className="p-4 md:p-8 space-y-8 pt-16 lg:pt-8">
            {/* Header with persistent search */}
            <div className="flex flex-col gap-4">
                <div className="flex items-start justify-between">
                    <div>
                        <h1 className="text-3xl font-bold">FAQ Management</h1>
                        <p className="text-muted-foreground">
                            Create and manage frequently asked questions for the support system
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
                            placeholder="Search FAQs... (⌘K or /)"
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
                            value={filters.categories.length > 0 ? filters.categories[0] : "all"}
                            onValueChange={(value) => {
                                if (value === "all") {
                                    setFilters((prev) => ({ ...prev, categories: [] }));
                                } else {
                                    setFilters((prev) => ({ ...prev, categories: [value] }));
                                }
                            }}
                        >
                            <SelectTrigger className="h-8 w-auto gap-2 px-3 border-dashed">
                                <Badge variant="outline" className="px-0 border-0">
                                    {filters.categories.length > 0
                                        ? filters.categories[0]
                                        : "All Categories"}
                                </Badge>
                                <ChevronDown className="h-3 w-3 opacity-50" />
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

                        {/* Source Filter Chip */}
                        <Select value={filters.source || "all"} onValueChange={handleSourceChange}>
                            <SelectTrigger className="h-8 w-auto gap-2 px-3 border-dashed">
                                <Badge variant="outline" className="px-0 border-0">
                                    {filters.source || "All Sources"}
                                </Badge>
                                <ChevronDown className="h-3 w-3 opacity-50" />
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

                        {/* Active Filter Badges */}
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

                        {/* Legacy Filter Button (for backwards compatibility) */}
                        <Button
                            onClick={() => setShowFilters(!showFilters)}
                            variant="outline"
                            size="sm"
                            className="h-8 border-dashed ml-auto"
                        >
                            <Filter className="mr-2 h-4 w-4" />
                            Advanced
                        </Button>
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

                        {/* Source */}
                        <div className="space-y-2">
                            <Label htmlFor="source">Source</Label>
                            <Select
                                value={filters.source || "all"}
                                onValueChange={handleSourceChange}
                            >
                                <SelectTrigger>
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

                        {/* Filter Actions */}
                        <div className="flex justify-between pt-4 border-t">
                            <Button
                                variant="outline"
                                onClick={clearAllFilters}
                                disabled={!hasActiveFilters}
                                size="sm"
                            >
                                <RotateCcw className="mr-2 h-4 w-4" />
                                Reset Filters
                            </Button>
                            <div className="text-sm text-muted-foreground">
                                {hasActiveFilters && (
                                    <span>
                                        {[
                                            filters.search_text && "Text search",
                                            filters.categories.length > 0 &&
                                                `${filters.categories.length} categor${filters.categories.length === 1 ? "y" : "ies"}`,
                                            filters.source && "Source",
                                        ]
                                            .filter(Boolean)
                                            .join(", ")}{" "}
                                        applied
                                    </span>
                                )}
                            </div>
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
                            <SheetTitle>{editingFaq ? "Edit FAQ" : "Add New FAQ"}</SheetTitle>
                            <SheetDescription>
                                {editingFaq
                                    ? "Update the details for this FAQ."
                                    : "Fill out the form to add a new FAQ to the knowledge base."}
                            </SheetDescription>
                        </SheetHeader>
                        <div className="flex-1 space-y-4 py-6">
                            <div className="space-y-2">
                                <Label htmlFor="question">Question</Label>
                                <Input
                                    id="question"
                                    value={formData.question}
                                    onChange={(e) =>
                                        setFormData({ ...formData, question: e.target.value })
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
                                    <Input
                                        id="category"
                                        value={formData.category}
                                        onChange={(e) =>
                                            setFormData({ ...formData, category: e.target.value })
                                        }
                                        required
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label htmlFor="source">Source</Label>
                                    <Input
                                        id="source"
                                        value={formData.source}
                                        onChange={(e) =>
                                            setFormData({ ...formData, source: e.target.value })
                                        }
                                        disabled
                                    />
                                </div>
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
                                {editingFaq ? "Save Changes" : "Add FAQ"}
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
                        <CardDescription>View, edit, or delete existing FAQs.</CardDescription>
                    </div>
                    <div className="flex items-center gap-2">
                        {!isFormOpen && !bulkSelectionMode && (
                            <>
                                <Button
                                    variant="outline"
                                    onClick={() => {
                                        setBulkSelectionMode(true);
                                        setSelectedFaqIds(new Set());
                                    }}
                                >
                                    Bulk Select
                                </Button>
                                <Button onClick={openNewFaqForm}>
                                    <PlusCircle className="mr-2 h-4 w-4" /> Add New FAQ
                                </Button>
                            </>
                        )}
                    </div>
                </CardHeader>
                <CardContent>
                    {isLoading ? (
                        <div className="flex items-center justify-center py-12">
                            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                        </div>
                    ) : !faqData?.faqs || faqData.faqs.length === 0 ? (
                        isSubmitting ? (
                            <div className="flex flex-col items-center justify-center py-12 space-y-3">
                                <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                                <div className="text-center">
                                    <h3 className="text-lg font-semibold">Processing...</h3>
                                    <p className="text-muted-foreground mt-1">
                                        Updating knowledge base. This may take a few moments.
                                    </p>
                                </div>
                            </div>
                        ) : (
                            <div className="text-center py-12">
                                <h3 className="text-lg font-semibold">No FAQs Found</h3>
                                <p className="text-muted-foreground mt-1">
                                    Get started by adding a new FAQ.
                                </p>
                                {!isFormOpen && (
                                    <Button onClick={openNewFaqForm} className="mt-4">
                                        <PlusCircle className="mr-2 h-4 w-4" /> Add New FAQ
                                    </Button>
                                )}
                            </div>
                        )
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
                                                    faqData?.faqs.length > 0 &&
                                                    selectedFaqIds.size === faqData.faqs.length
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

                            {faqData?.faqs.map((faq, index) => {
                                // Smart expansion logic: verified FAQs can be collapsed, unverified FAQs always expanded
                                const isExpanded = !faq.verified || expandedIds.has(faq.id);
                                const isSelected = index === selectedIndex;

                                return (
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
                                        ref={(el) => {
                                            if (el) {
                                                faqRefs.current.set(
                                                    faq.id,
                                                    el as unknown as HTMLDivElement
                                                );
                                            }
                                        }}
                                        className={`
                                            bg-card border rounded-lg group
                                            transition-all duration-200 ease-out
                                            ${
                                                isSelected
                                                    ? "border-green-500 shadow-lg shadow-green-500/20 ring-2 ring-green-500/30 ring-offset-2 ring-offset-background"
                                                    : "border-border hover:shadow-sm hover:border-border/60"
                                            }
                                        `}
                                        tabIndex={-1}
                                        style={{
                                            outline: "none", // Remove default outline, we use custom ring
                                        }}
                                    >
                                        <div className="p-4">
                                            {faq.verified ? (
                                                <CollapsibleTrigger
                                                    className="w-full group/trigger focus-visible:outline-none"
                                                    onFocus={() => {
                                                        // Sync Tab navigation with keyboard selection
                                                        setSelectedIndex(index);
                                                    }}
                                                >
                                                    <div className="flex items-start justify-between gap-3 text-left">
                                                        {bulkSelectionMode && (
                                                            <div className="flex items-start pt-1">
                                                                <Checkbox
                                                                    checked={selectedFaqIds.has(
                                                                        faq.id
                                                                    )}
                                                                    onCheckedChange={() =>
                                                                        handleSelectFaq(faq.id)
                                                                    }
                                                                    onClick={(e) =>
                                                                        e.stopPropagation()
                                                                    }
                                                                    disabled={isSubmitting}
                                                                    aria-label={`Select FAQ: ${faq.question}`}
                                                                />
                                                            </div>
                                                        )}
                                                        <div className="flex-1 space-y-2">
                                                            <div className="flex items-start gap-2">
                                                                <h3 className="font-semibold text-card-foreground text-base leading-relaxed flex-1">
                                                                    {faq.question}
                                                                </h3>
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

                                                            <div className="flex items-center gap-4 text-sm text-muted-foreground">
                                                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground font-medium">
                                                                    {faq.category}
                                                                </span>
                                                                <span>Source: {faq.source}</span>
                                                                {faq.verified ? (
                                                                    <span
                                                                        className="inline-flex items-center gap-1 text-green-600"
                                                                        aria-label="Verified FAQ"
                                                                    >
                                                                        <BadgeCheck
                                                                            className="h-4 w-4"
                                                                            aria-hidden="true"
                                                                        />
                                                                        <span className="text-xs font-medium">
                                                                            Verified
                                                                        </span>
                                                                    </span>
                                                                ) : (
                                                                    <span
                                                                        className="inline-flex items-center gap-1 text-amber-600"
                                                                        aria-label="Unverified FAQ - Needs Review"
                                                                    >
                                                                        <AlertCircle
                                                                            className="h-4 w-4"
                                                                            aria-hidden="true"
                                                                        />
                                                                        <span className="text-xs font-medium">
                                                                            Needs Review
                                                                        </span>
                                                                    </span>
                                                                )}
                                                            </div>
                                                        </div>
                                                    </div>
                                                </CollapsibleTrigger>
                                            ) : (
                                                <div
                                                    className="w-full focus-visible:outline-none"
                                                    tabIndex={0}
                                                    onFocus={() => {
                                                        // Sync Tab navigation with keyboard selection
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
                                                                        handleSelectFaq(faq.id)
                                                                    }
                                                                    disabled={isSubmitting}
                                                                    aria-label={`Select FAQ: ${faq.question}`}
                                                                />
                                                            </div>
                                                        )}
                                                        <div className="flex-1 space-y-2">
                                                            <div className="flex items-start gap-2">
                                                                <h3 className="font-semibold text-card-foreground text-base leading-relaxed flex-1">
                                                                    {faq.question}
                                                                </h3>
                                                            </div>

                                                            <div className="flex items-center gap-4 text-sm text-muted-foreground">
                                                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full bg-secondary text-secondary-foreground font-medium">
                                                                    {faq.category}
                                                                </span>
                                                                <span>Source: {faq.source}</span>
                                                                <span
                                                                    className="inline-flex items-center gap-1 text-amber-600"
                                                                    aria-label="Unverified FAQ - Needs Review"
                                                                >
                                                                    <AlertCircle
                                                                        className="h-4 w-4"
                                                                        aria-hidden="true"
                                                                    />
                                                                    <span className="text-xs font-medium">
                                                                        Needs Review
                                                                    </span>
                                                                </span>
                                                            </div>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}

                                            <CollapsibleContent className="pt-3">
                                                <div className="flex items-start justify-between gap-4">
                                                    <div className="flex-1 space-y-3">
                                                        <div>
                                                            <p className="text-muted-foreground text-sm leading-relaxed whitespace-pre-wrap">
                                                                {faq.answer}
                                                            </p>
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
                                                                    disabled={isSubmitting}
                                                                    onClick={() =>
                                                                        handleVerifyFaq(faq)
                                                                    }
                                                                    aria-label={`Verify FAQ: ${faq.question}`}
                                                                >
                                                                    <BadgeCheck className="h-4 w-4 mr-2" />
                                                                    Verify FAQ
                                                                </Button>
                                                            ) : (
                                                                <AlertDialog>
                                                                    <AlertDialogTrigger asChild>
                                                                        <Button
                                                                            variant="outline"
                                                                            size="sm"
                                                                            disabled={isSubmitting}
                                                                        >
                                                                            <BadgeCheck className="h-4 w-4 mr-2" />
                                                                            Verify FAQ
                                                                        </Button>
                                                                    </AlertDialogTrigger>
                                                                    <AlertDialogContent>
                                                                        <AlertDialogHeader>
                                                                            <AlertDialogTitle>
                                                                                Verify this FAQ?
                                                                            </AlertDialogTitle>
                                                                            <AlertDialogDescription>
                                                                                This will mark this
                                                                                FAQ as verified,
                                                                                indicating it has
                                                                                been reviewed and
                                                                                approved by a Bisq
                                                                                Support Admin. This
                                                                                action is
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
                                                                                Do not show this
                                                                                confirmation again
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
                                                                                Verify FAQ
                                                                            </AlertDialogAction>
                                                                        </AlertDialogFooter>
                                                                    </AlertDialogContent>
                                                                </AlertDialog>
                                                            ))}
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            onClick={() => handleEdit(faq)}
                                                            className="h-8 w-8"
                                                        >
                                                            <Pencil className="h-4 w-4" />
                                                        </Button>
                                                        <AlertDialog>
                                                            <AlertDialogTrigger asChild>
                                                                <Button
                                                                    variant="ghost"
                                                                    size="icon"
                                                                    disabled={isSubmitting}
                                                                    className="h-8 w-8"
                                                                >
                                                                    <Trash2 className="h-4 w-4 text-red-500" />
                                                                </Button>
                                                            </AlertDialogTrigger>
                                                            <AlertDialogContent>
                                                                <AlertDialogHeader>
                                                                    <AlertDialogTitle>
                                                                        Are you absolutely sure?
                                                                    </AlertDialogTitle>
                                                                    <AlertDialogDescription>
                                                                        This action cannot be
                                                                        undone. This will
                                                                        permanently delete this FAQ.
                                                                    </AlertDialogDescription>
                                                                </AlertDialogHeader>
                                                                <AlertDialogFooter>
                                                                    <AlertDialogCancel>
                                                                        Cancel
                                                                    </AlertDialogCancel>
                                                                    <AlertDialogAction
                                                                        onClick={() =>
                                                                            handleDelete(faq.id)
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
                                );
                            })}
                        </div>
                    )}

                    {/* Pagination Controls */}
                    {faqData && faqData.total_pages > 1 && (
                        <div className="flex items-center justify-between px-2 py-4">
                            <div className="flex items-center space-x-6 lg:space-x-8">
                                <div className="flex items-center space-x-2">
                                    <p className="text-sm font-medium">
                                        Showing {(faqData.page - 1) * faqData.page_size + 1} to{" "}
                                        {Math.min(
                                            faqData.page * faqData.page_size,
                                            faqData.total_count
                                        )}{" "}
                                        of {faqData.total_count} entries
                                    </p>
                                </div>
                            </div>
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
                                            if (pageNum > faqData.total_pages) return null;
                                            return (
                                                <Button
                                                    key={pageNum}
                                                    variant={
                                                        pageNum === currentPage
                                                            ? "default"
                                                            : "outline"
                                                    }
                                                    size="sm"
                                                    onClick={() => handlePageChange(pageNum)}
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
                            <span>{bulkSelectionMode ? "Exit" : "Enable"} Bulk Selection</span>
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
                                setFilterCategory("");
                                setFilterSource("");
                                setCommandPaletteOpen(false);
                            }}
                        >
                            <X className="mr-2 h-4 w-4" />
                            <span>Reset All Filters</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => {
                                setFilterCategory("general");
                                setCommandPaletteOpen(false);
                            }}
                        >
                            <span>Filter: General</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => {
                                setFilterCategory("technical");
                                setCommandPaletteOpen(false);
                            }}
                        >
                            <span>Filter: Technical</span>
                        </CommandItem>
                        <CommandItem
                            onSelect={() => {
                                setFilterCategory("trading");
                                setCommandPaletteOpen(false);
                            }}
                        >
                            <span>Filter: Trading</span>
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
        </div>
    );
}
