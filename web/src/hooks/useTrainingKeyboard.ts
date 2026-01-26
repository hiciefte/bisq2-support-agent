"use client"

import { useEffect, useCallback } from 'react';

interface UseTrainingKeyboardOptions {
  onApprove: () => void;
  onReject: () => void;
  onSkip: () => void;
  enabled?: boolean;
}

/**
 * Hook to enable keyboard shortcuts for training review.
 *
 * Shortcuts:
 * - A: Approve current item
 * - R: Reject current item (opens reason selector)
 * - S: Skip to next item
 *
 * @param options - Callback functions and enabled state
 */
export function useTrainingKeyboard({
  onApprove,
  onReject,
  onSkip,
  enabled = true
}: UseTrainingKeyboardOptions) {
  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    // Ignore if typing in an input field
    if (
      event.target instanceof HTMLInputElement ||
      event.target instanceof HTMLTextAreaElement ||
      event.target instanceof HTMLSelectElement
    ) {
      return;
    }

    // Ignore if modifier keys are pressed
    if (event.ctrlKey || event.metaKey || event.altKey) {
      return;
    }

    const key = event.key.toLowerCase();

    switch (key) {
      case 'a':
        event.preventDefault();
        onApprove();
        break;
      case 'r':
        event.preventDefault();
        onReject();
        break;
      case 's':
        event.preventDefault();
        onSkip();
        break;
    }
  }, [onApprove, onReject, onSkip]);

  useEffect(() => {
    if (!enabled) return;

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown, enabled]);
}
