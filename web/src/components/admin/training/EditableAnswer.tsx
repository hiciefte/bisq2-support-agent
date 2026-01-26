"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { Pencil, Check, X } from "lucide-react";

// Note: "View Original Staff Answer" removed - now consolidated in "Original Conversation"
// section at the top of TrainingReviewItem for better review flow (Think in Flows principle)

interface EditableAnswerProps {
  answer: string;
  editedAnswer: string | null;
  isEditing: boolean;
  onEditStart: () => void;
  onEditSave: (newAnswer: string) => Promise<void>;
  onEditCancel: () => void;
  label: string;
  icon: React.ReactNode;
  isSaving?: boolean;
}

export function EditableAnswer({
  answer,
  editedAnswer,
  isEditing,
  onEditStart,
  onEditSave,
  onEditCancel,
  label,
  icon,
  isSaving = false,
}: EditableAnswerProps) {
  // Use edited answer if available, otherwise use original
  const displayAnswer = editedAnswer ?? answer;
  const [editValue, setEditValue] = useState(displayAnswer);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const isModified = editedAnswer !== null && editedAnswer !== answer;

  // Auto-focus and resize on edit mode
  useEffect(() => {
    if (isEditing && textareaRef.current) {
      textareaRef.current.focus();
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
    }
  }, [isEditing]);

  // Reset edit value when answer changes
  useEffect(() => {
    setEditValue(displayAnswer);
  }, [displayAnswer]);

  const handleSave = useCallback(async () => {
    await onEditSave(editValue);
  }, [editValue, onEditSave]);

  const handleCancel = useCallback(() => {
    setEditValue(displayAnswer);
    onEditCancel();
  }, [displayAnswer, onEditCancel]);

  const hasChanges = editValue !== displayAnswer;

  // Keyboard shortcuts for edit mode
  useEffect(() => {
    if (!isEditing) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      // Escape to cancel
      if (e.key === "Escape") {
        e.preventDefault();
        handleCancel();
        return;
      }

      // Cmd/Ctrl + Enter to save
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && hasChanges) {
        e.preventDefault();
        handleSave();
        return;
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isEditing, hasChanges, handleSave, handleCancel]);

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          {icon}
          <span className="font-medium text-sm">
            {label}
            {isEditing && (
              <span className="text-muted-foreground ml-1">(Editing)</span>
            )}
          </span>
          {isModified && !isEditing && (
            <Badge
              variant="outline"
              className="text-muted-foreground gap-1"
            >
              <Pencil className="h-3 w-3" />
              Edited
            </Badge>
          )}
        </div>
        {!isEditing && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onEditStart}
            className="h-7 text-xs"
          >
            <Pencil className="h-3 w-3 mr-1" />
            Edit
          </Button>
        )}
      </div>

      {/* Content - Clean, minimal style */}
      <div
        className={cn(
          "p-4 rounded-lg border min-h-[120px] transition-all",
          isEditing
            ? "bg-background border-primary ring-1 ring-primary"
            : "bg-muted/30 border-border"
        )}
      >
        {isEditing ? (
          <Textarea
            ref={textareaRef}
            value={editValue}
            onChange={(e) => {
              setEditValue(e.target.value);
              // Auto-resize
              e.target.style.height = "auto";
              e.target.style.height = `${e.target.scrollHeight}px`;
            }}
            className="min-h-[100px] resize-none border-0 p-0 focus-visible:ring-0 bg-transparent"
            placeholder="Enter the corrected answer..."
          />
        ) : (
          <p className="text-sm whitespace-pre-wrap">{displayAnswer}</p>
        )}
      </div>

      {/* Edit Mode Actions */}
      {isEditing && (
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" onClick={handleSave} disabled={!hasChanges || isSaving}>
            {isSaving ? (
              <>Saving...</>
            ) : (
              <>
                <Check className="h-4 w-4 mr-1" />
                Save Changes
              </>
            )}
          </Button>
          <Button variant="outline" size="sm" onClick={handleCancel} disabled={isSaving}>
            <X className="h-4 w-4 mr-1" />
            Cancel
          </Button>
          {hasChanges && (
            <span className="text-xs text-muted-foreground">
              Press <kbd className="px-1 py-0.5 bg-muted rounded text-xs">⌘↵</kbd> to save
            </span>
          )}
        </div>
      )}

      {/* Modified indicator */}
      {isModified && !isEditing && (
        <p className="text-xs text-muted-foreground mt-2">
          This answer has been modified from the original staff response.
        </p>
      )}

      {/* Original answer viewing now consolidated in "Original Conversation" section
          at top of TrainingReviewItem - removed here per Speed Through Subtraction principle */}
    </div>
  );
}
