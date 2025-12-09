/**
 * EditAnswerModal Component
 *
 * Modal dialog for editing response answers before approval.
 *
 * Design Principles Applied:
 * - Speed Through Subtraction: Minimal modal, focus on editing only
 * - Feedback Immediacy: Keyboard shortcuts (Cmd+Enter, Escape)
 * - Spatial Consistency: Predictable button layout (Cancel left, Save right)
 */

'use client';

import { useState, useEffect, useRef } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { PendingResponse } from '@/types/pending-response';

interface EditAnswerModalProps {
  response: PendingResponse;
  onSave: (editedAnswer: string) => void;
  onCancel: () => void;
}

export function EditAnswerModal({ response, onSave, onCancel }: EditAnswerModalProps) {
  const [editedAnswer, setEditedAnswer] = useState(response.answer);
  const [validationError, setValidationError] = useState('');
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Focus textarea when modal opens
  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  // Validation: answer cannot be empty
  const isValidAnswer = editedAnswer.trim().length > 0;

  // Handle save
  const handleSave = () => {
    const trimmedAnswer = editedAnswer.trim();

    if (!trimmedAnswer) {
      setValidationError('Answer cannot be empty');
      return;
    }

    setValidationError('');
    onSave(trimmedAnswer);
  };

  // Keyboard shortcuts
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Cmd+Enter or Ctrl+Enter to save
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      if (isValidAnswer) {
        handleSave();
      }
    }

    // Escape to cancel
    if (e.key === 'Escape') {
      e.preventDefault();
      onCancel();
    }
  };

  // Character count
  const charCount = editedAnswer.length;

  return (
    <Dialog open={true} onOpenChange={onCancel}>
      <DialogContent
        className="max-w-2xl"
        aria-label="Edit Answer"
        aria-modal="true"
      >
        <DialogHeader>
          <DialogTitle>Edit Answer</DialogTitle>
        </DialogHeader>

        <div className="space-y-4 py-4">
          {/* Question (read-only) */}
          <div>
            <Label className="text-sm font-medium text-muted-foreground">
              Question
            </Label>
            <p className="mt-1 text-base">{response.question}</p>
          </div>

          {/* Editable Answer */}
          <div>
            <Label htmlFor="edit-answer" className="text-sm font-medium">
              Your Answer
            </Label>
            <Textarea
              id="edit-answer"
              ref={textareaRef}
              value={editedAnswer}
              onChange={(e) => {
                setEditedAnswer(e.target.value);
                setValidationError('');
              }}
              onKeyDown={handleKeyDown}
              className="mt-1 min-h-[200px]"
              placeholder="Enter your answer..."
              aria-label="Your answer"
            />

            {/* Character count and validation error */}
            <div className="mt-1 flex items-center justify-between">
              <span className="text-sm text-muted-foreground">
                {charCount} characters
              </span>
              {validationError && (
                <span className="text-sm text-red-500">{validationError}</span>
              )}
            </div>
          </div>

          {/* Keyboard shortcuts hint */}
          <div className="text-sm text-muted-foreground">
            <kbd className="px-2 py-1 bg-muted rounded">⌘ Cmd+Enter</kbd> to save
            {' · '}
            <kbd className="px-2 py-1 bg-muted rounded">Esc</kbd> to cancel
          </div>
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            onClick={onCancel}
            aria-label="Cancel editing"
          >
            Cancel
          </Button>
          <Button
            onClick={handleSave}
            disabled={!isValidAnswer}
            aria-label="Save edited answer and approve"
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
