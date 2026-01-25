"use client";

import { useHotkeys } from "react-hotkeys-hook";
import { RefObject } from "react";

interface FAQ {
    id: string;
    question: string;
    verified: boolean;
    protocol: "multisig_v1" | "bisq_easy" | "musig" | "all";
}

interface UseManageFaqsKeyboardOptions {
    // Data
    displayFaqs: { faqs: FAQ[] } | null;
    selectedIndex: number;
    editingFaqId: string | null;
    bulkSelectionMode: boolean;
    selectedFaqIds: Set<string>;
    isFormOpen: boolean;
    skipVerifyConfirmation: boolean;

    // Setters
    setSelectedIndex: React.Dispatch<React.SetStateAction<number>>;
    setCommandPaletteOpen: React.Dispatch<React.SetStateAction<boolean>>;
    setBulkSelectionMode: React.Dispatch<React.SetStateAction<boolean>>;
    setSelectedFaqIds: React.Dispatch<React.SetStateAction<Set<string>>>;
    setIsFormOpen: React.Dispatch<React.SetStateAction<boolean>>;
    setFaqToDelete: React.Dispatch<React.SetStateAction<FAQ | null>>;
    setShowDeleteConfirmDialog: React.Dispatch<React.SetStateAction<boolean>>;

    // Refs
    searchInputRef: RefObject<HTMLInputElement | null>;

    // Handlers
    openNewFaqForm: () => void;
    enterEditMode: (faq: FAQ) => void;
    handleCancelEdit: (faqId: string) => void;
    handleSetProtocol: (faq: FAQ, protocol: FAQ["protocol"]) => Promise<void>;
    handleVerifyFaq: (faq: FAQ) => Promise<void>;
    handleBulkDelete: () => Promise<void>;
    handleBulkVerify: () => Promise<void>;

    // Toast
    toast: (opts: { title: string; description: string }) => void;
}

/**
 * Keyboard shortcuts for FAQ management page.
 *
 * Shortcuts:
 * - Cmd/Ctrl+K: Open command palette
 * - /: Focus search
 * - j/k: Navigate down/up
 * - Enter: Enter edit mode
 * - Escape: Exit edit mode or clear selection
 * - e: Set protocol to Bisq Easy
 * - 1: Set protocol to Multisig v1
 * - m: Set protocol to MuSig
 * - 0: Set protocol to All
 * - d: Delete FAQ
 * - v: Verify FAQ
 * - n: New FAQ
 * - b: Toggle bulk selection mode
 * - a: Select all (in bulk mode)
 */
export function useManageFaqsKeyboard({
    displayFaqs,
    selectedIndex,
    editingFaqId,
    bulkSelectionMode,
    selectedFaqIds,
    isFormOpen,
    skipVerifyConfirmation,
    setSelectedIndex,
    setCommandPaletteOpen,
    setBulkSelectionMode,
    setSelectedFaqIds,
    setIsFormOpen,
    setFaqToDelete,
    setShowDeleteConfirmDialog,
    searchInputRef,
    openNewFaqForm,
    enterEditMode,
    handleCancelEdit,
    handleSetProtocol,
    handleVerifyFaq,
    handleBulkDelete,
    handleBulkVerify,
    toast,
}: UseManageFaqsKeyboardOptions) {
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

    // Set protocol to Bisq Easy (e key)
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

    // Set protocol to Multisig v1 (1 key)
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

    // Set protocol to MuSig (m key)
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

    // Set protocol to All (0 key)
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

    // Enter edit mode (Enter key)
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
    useHotkeys(
        "d",
        (e) => {
            e.preventDefault();
            if (bulkSelectionMode && selectedFaqIds.size > 0) {
                handleBulkDelete();
            } else if (selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
                const selectedFaq = displayFaqs.faqs[selectedIndex];
                setFaqToDelete(selectedFaq);
                setShowDeleteConfirmDialog(true);
            }
        },
        { enableOnFormTags: false },
        [selectedIndex, displayFaqs, bulkSelectionMode, selectedFaqIds]
    );

    // Verify FAQ (v key)
    useHotkeys(
        "v",
        (e) => {
            e.preventDefault();
            if (bulkSelectionMode && selectedFaqIds.size > 0) {
                handleBulkVerify();
            } else if (selectedIndex >= 0 && displayFaqs?.faqs[selectedIndex]) {
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
}
