"use client"

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { cn } from "@/lib/utils";
import {
  XCircle,
  SkipForward,
  Loader2,
  MessageSquare,
  Bot,
  User,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  MessagesSquare,
  PlusCircle,
  ThumbsUp,
  ThumbsDown,
  Pencil,
  Check,
  X,
} from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ScoreBreakdown } from './ScoreBreakdown';
import { ProtocolSelector, ProtocolType } from './ProtocolSelector';
import { EditableAnswer } from './EditableAnswer';
import { EditableQuestion } from './EditableQuestion';
import { CategorySelector } from './CategorySelector';
import { StickyActionFooter } from './StickyActionFooter';
import { SourceBadges } from '@/components/chat/components/source-badges';
import { ConfidenceBadge } from '@/components/chat/components/confidence-badge';
import { MarkdownContent } from '@/components/chat/components/markdown-content';
import type { Source } from '@/components/chat/types/chat.types';

// Unified FAQ Candidate type (from unified pipeline)
interface UnifiedCandidate {
  id: number;
  source: string;  // "bisq2" | "matrix"
  source_event_id: string;
  source_timestamp: string;
  question_text: string;
  staff_answer: string;
  generated_answer: string | null;
  staff_sender: string | null;
  embedding_similarity: number | null;
  factual_alignment: number | null;
  contradiction_score: number | null;
  completeness: number | null;
  hallucination_risk: number | null;
  final_score: number | null;
  generation_confidence: number | null;  // RAG's self-confidence in its answer
  llm_reasoning: string | null;
  routing: string;
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  faq_id: string | null;
  is_calibration_sample: boolean;
  created_at: string;
  updated_at: string | null;
  // Phase 8 fields for multi-turn conversation support
  conversation_context: string | null;  // JSON string of full conversation
  has_correction: boolean | null;
  is_multi_turn: boolean | null;
  message_count: number | null;
  needs_distillation: boolean | null;
  // Protocol selection and answer editing fields
  protocol: ProtocolType | null;
  edited_staff_answer: string | null;
  // Category field
  category: string | null;
  // RAG-generated answer sources for verification
  generated_answer_sources: Source[] | null;
  // Original conversational user question before LLM transformation
  original_user_question: string | null;
  // Original conversational staff answer before LLM transformation
  original_staff_answer: string | null;
  // User-edited version of question
  edited_question_text: string | null;
}

// Type for conversation context message
interface ConversationMessage {
  sender: string;
  content: string;
  timestamp?: string;
}

interface TrainingReviewItemProps {
  pair: UnifiedCandidate;
  onApprove: () => Promise<void>;
  onReject: (reason: string) => Promise<void>;
  onSkip: () => Promise<void>;
  onUpdateCandidate: (updates: { edited_staff_answer?: string; edited_question_text?: string; category?: string }) => Promise<void>;
  onRegenerateAnswer: (protocol: ProtocolType) => Promise<void>;
  onRateGeneratedAnswer?: (rating: 'good' | 'needs_improvement') => Promise<void>;
  isLoading: boolean;
}

const REJECT_REASONS = [
  { value: "incorrect", label: "Incorrect information" },
  { value: "outdated", label: "Outdated content" },
  { value: "too_vague", label: "Too vague" },
  { value: "off_topic", label: "Off-topic" },
  { value: "duplicate", label: "Duplicate FAQ exists" },
  { value: "other", label: "Other reason" },
];

// Hoisted helper functions outside component to prevent re-creation (Rule 6.3)
const getProtocolLabel = (protocol: ProtocolType | null): string => {
  switch (protocol) {
    case 'bisq_easy': return 'Bisq Easy';
    case 'multisig_v1': return 'Bisq 1';
    case 'musig': return 'MuSig';
    case 'all': return 'All';
    default: return '';
  }
};

// Protocol badge colors - subtle, muted style matching FAQ management
const getProtocolBadgeColor = (protocol: ProtocolType | null): string => {
  switch (protocol) {
    case 'bisq_easy':
      return 'bg-emerald-500/10 text-emerald-600 border border-emerald-500/20 dark:text-emerald-400';
    case 'multisig_v1':
      return 'bg-blue-500/10 text-blue-600 border border-blue-500/20 dark:text-blue-400';
    case 'musig':
      return 'bg-orange-500/10 text-orange-600 border border-orange-500/20 dark:text-orange-400';
    case 'all':
      return 'bg-purple-500/10 text-purple-600 border border-purple-500/20 dark:text-purple-400';
    default:
      return '';
  }
};

// Muted, subtle routing badge colors - minimal visual noise
// All routes use the same muted style for minimal visual noise
const getRoutingBadgeColor = (): string => {
  return 'bg-muted text-muted-foreground border border-border';
};

// Translate routing to user-friendly label
const getRoutingLabel = (routing: string): string => {
  switch (routing) {
    case 'FULL_REVIEW':
      return 'KNOWLEDGE GAP';
    case 'SPOT_CHECK':
      return 'MINOR GAP';
    case 'AUTO_APPROVE':
      return 'CALIBRATION';
    default:
      return routing.replace('_', ' ');
  }
};

// All sources use the same muted style
const getSourceBadgeColor = (): string => {
  return 'bg-muted text-foreground border border-border';
};

// Date formatting options - hoisted to prevent recreation
const DATE_FORMAT_OPTIONS: Intl.DateTimeFormatOptions = {
  year: 'numeric',
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit'
};

const formatDate = (dateStr: string): string => {
  return new Date(dateStr).toLocaleDateString('en-US', DATE_FORMAT_OPTIONS);
};

export function TrainingReviewItem({
  pair,
  onApprove,
  onReject,
  onSkip,
  onUpdateCandidate,
  onRegenerateAnswer,
  onRateGeneratedAnswer,
  isLoading
}: TrainingReviewItemProps) {
  const [showRejectSelect, setShowRejectSelect] = useState(false);
  // Smart conversation auto-expand: Show when critical context exists (Progressive Disclosure)
  const shouldAutoExpandConversation = Boolean(
    pair.conversation_context && (
      pair.has_correction ||  // Corrections need visibility
      (pair.is_multi_turn && (pair.message_count || 0) > 3) ||  // Complex multi-turn
      pair.routing === 'FULL_REVIEW'  // Full review needs full context
    )
  );
  const [showConversation, setShowConversation] = useState(shouldAutoExpandConversation);
  // Unified edit mode: single state for editing both Q&A together (UX improvement)
  const [isEditing, setIsEditing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [currentProtocol, setCurrentProtocol] = useState<ProtocolType | null>(pair.protocol);
  const [currentCategory, setCurrentCategory] = useState<string | null>(pair.category);
  const [isSavingCategory, setIsSavingCategory] = useState(false);
  const [answerRating, setAnswerRating] = useState<'good' | 'needs_improvement' | null>(null);
  const [isRatingAnswer, setIsRatingAnswer] = useState(false);
  // P3: Confirmation dialog state for reject action
  const [pendingRejectReason, setPendingRejectReason] = useState<string | null>(null);

  // Sticky footer visibility state
  const [showStickyFooter, setShowStickyFooter] = useState(false);
  const footerRef = useRef<HTMLDivElement>(null);

  // Intersection Observer for sticky footer
  useEffect(() => {
    const footer = footerRef.current;
    if (!footer) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        // Show sticky footer when original footer is not visible
        setShowStickyFooter(!entry.isIntersecting);
      },
      {
        root: null,
        rootMargin: '0px',
        threshold: 0.1,
      }
    );

    observer.observe(footer);
    return () => observer.disconnect();
  }, []);

  // Sync protocol when pair changes
  useEffect(() => {
    setCurrentProtocol(pair.protocol);
  }, [pair.protocol]);

  // Sync category when pair changes
  useEffect(() => {
    setCurrentCategory(pair.category);
  }, [pair.category]);

  // Reset answer rating when candidate changes OR answer regenerates (P1 + Cycle 21 fix)
  useEffect(() => {
    setAnswerRating(null);
  }, [pair.id, pair.generated_answer]);

  // Reset conversation view based on smart auto-expand logic when candidate changes
  useEffect(() => {
    const shouldExpand = Boolean(
      pair.conversation_context && (
        pair.has_correction ||
        (pair.is_multi_turn && (pair.message_count || 0) > 3) ||
        pair.routing === 'FULL_REVIEW'
      )
    );
    setShowConversation(shouldExpand);
  }, [pair.id, pair.has_correction, pair.is_multi_turn, pair.message_count, pair.routing, pair.conversation_context]);

  // Memoized handlers to prevent unnecessary re-renders (Rule 5.5)
  // Streamlined reject: Direct rejection for standard reasons (no confirmation dialog)
  // Only "Other" reason shows confirmation dialog for custom input
  const handleDirectReject = useCallback((reason: string) => {
    if (reason === 'other') {
      // Show confirmation dialog only for "Other" reason
      setPendingRejectReason(reason);
    } else {
      // Direct rejection for standard reasons (Speed Through Subtraction principle)
      onReject(reason);
      setShowRejectSelect(false);
    }
  }, [onReject]);

  // Confirm rejection for "Other" reason
  const handleConfirmReject = useCallback(() => {
    if (pendingRejectReason) {
      onReject(pendingRejectReason);
      setPendingRejectReason(null);
      setShowRejectSelect(false);
    }
  }, [pendingRejectReason, onReject]);

  // Cancel rejection - clear pending state
  const handleCancelReject = useCallback(() => {
    setPendingRejectReason(null);
    setShowRejectSelect(false);
  }, []);

  // Handle protocol change - intentionally does NOT update currentProtocol
  // This allows ProtocolSelector to detect that protocol has changed (selectedProtocol !== currentProtocol)
  // and show the green Regenerate button. currentProtocol is only updated when:
  // 1. A new candidate is loaded (pair.protocol changes)
  // 2. After successful regeneration (when pair.protocol is updated from backend)
  // Note: Using no-op function since ProtocolSelector manages its own selectedProtocol state
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const handleProtocolChange = (protocol: ProtocolType) => {
    // No-op: The parent's currentProtocol stays at pair.protocol until regeneration
  };

  // Handle regenerate answer with protocol (Rule 5.5)
  const handleRegenerateAnswer = useCallback(async (protocol: ProtocolType) => {
    setIsRegenerating(true);
    try {
      await onRegenerateAnswer(protocol);
    } finally {
      setIsRegenerating(false);
    }
  }, [onRegenerateAnswer]);

  // Unified edit mode: refs to track edited values
  const editedQuestionRef = useRef<string | null>(null);
  const editedAnswerRef = useRef<string | null>(null);

  // Handle unified save (both Q&A together) (Rule 5.5)
  const handleUnifiedSave = useCallback(async () => {
    setIsSaving(true);
    try {
      const updates: { edited_question_text?: string; edited_staff_answer?: string } = {};
      if (editedQuestionRef.current !== null) {
        updates.edited_question_text = editedQuestionRef.current;
      }
      if (editedAnswerRef.current !== null) {
        updates.edited_staff_answer = editedAnswerRef.current;
      }
      if (Object.keys(updates).length > 0) {
        await onUpdateCandidate(updates);
      }
      setIsEditing(false);
      editedQuestionRef.current = null;
      editedAnswerRef.current = null;
    } finally {
      setIsSaving(false);
    }
  }, [onUpdateCandidate]);

  // Handle unified cancel (exit edit mode without saving)
  const handleUnifiedCancel = useCallback(() => {
    setIsEditing(false);
    editedQuestionRef.current = null;
    editedAnswerRef.current = null;
  }, []);

  // Keyboard shortcuts - must be after unified handlers are defined
  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      // Don't trigger if typing in an input or editing
      const target = e.target as HTMLElement;
      if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
        return;
      }

      // Only trigger if no modifier keys
      if (e.ctrlKey || e.metaKey || e.altKey) {
        return;
      }

      // 'C' to toggle conversation view
      if (e.key === 'c' && pair.conversation_context) {
        e.preventDefault();
        setShowConversation(prev => !prev);
      }

      // 'E' to enter unified edit mode for both Q&A (UX improvement: single edit flow)
      if (e.key === 'e' && !isEditing) {
        e.preventDefault();
        setIsEditing(true);
      }
    };

    // Separate handler for edit mode specific shortcuts (needs modifier key support)
    const handleEditModeKeyDown = (e: KeyboardEvent) => {
      if (!isEditing) return;

      // 'Escape' to exit unified edit mode
      if (e.key === 'Escape') {
        e.preventDefault();
        handleUnifiedCancel();
        return;
      }

      // Cmd/Ctrl + Enter to save unified changes
      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
        e.preventDefault();
        handleUnifiedSave();
        return;
      }
    };

    window.addEventListener('keydown', handleKeyPress);
    window.addEventListener('keydown', handleEditModeKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyPress);
      window.removeEventListener('keydown', handleEditModeKeyDown);
    };
  }, [pair.conversation_context, isEditing, handleUnifiedCancel, handleUnifiedSave]);

  // Track question changes during edit
  const handleQuestionChange = useCallback((newQuestion: string) => {
    editedQuestionRef.current = newQuestion;
  }, []);

  // Track answer changes during edit
  const handleAnswerChange = useCallback((newAnswer: string) => {
    editedAnswerRef.current = newAnswer;
  }, []);

  // Handle category change (local state only) (Rule 5.5)
  const handleCategoryChange = useCallback((category: string) => {
    setCurrentCategory(category);
  }, []);

  // Handle save category to backend (Rule 5.5)
  const handleSaveCategory = useCallback(async (category: string) => {
    setIsSavingCategory(true);
    try {
      await onUpdateCandidate({ category });
    } finally {
      setIsSavingCategory(false);
    }
  }, [onUpdateCandidate]);

  // Handle rating the generated answer quality for LearningEngine training (Rule 5.5)
  const handleRateGeneratedAnswer = useCallback(async (rating: 'good' | 'needs_improvement') => {
    if (!onRateGeneratedAnswer) return;

    setIsRatingAnswer(true);
    try {
      await onRateGeneratedAnswer(rating);
      setAnswerRating(rating);
    } finally {
      setIsRatingAnswer(false);
    }
  }, [onRateGeneratedAnswer]);

  // Memoized conversation parsing - expensive JSON.parse operation (Rule 7.4)
  const conversationMessages = useMemo<ConversationMessage[]>(() => {
    if (!pair.conversation_context) return [];
    try {
      return JSON.parse(pair.conversation_context);
    } catch (e) {
      console.error('Failed to parse conversation_context:', e);
      return [];
    }
  }, [pair.conversation_context]);

  // Memoized correction detection - expensive pattern matching (Rule 7.4)
  const correctionIndex = useMemo(() => {
    const CORRECTION_PATTERNS = ['wait', 'actually', 'correction', 'sorry', 'i meant', 'my mistake', 'scratch that'];
    // Search from end to find the last correction
    for (let i = conversationMessages.length - 1; i >= 0; i--) {
      const content = conversationMessages[i].content.toLowerCase();
      for (const pattern of CORRECTION_PATTERNS) {
        if (content.includes(pattern)) {
          return i;
        }
      }
    }
    return -1;
  }, [conversationMessages]);

  // Memoized derived values to avoid recalculation (Rule 7.4)
  // Check if this is a calibration queue item (primary action is rating, not approval)
  const isCalibrationItem = pair.routing === 'AUTO_APPROVE';

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="flex items-center gap-2">
            <MessageSquare className="h-5 w-5" />
            FAQ Candidate #{pair.id}
          </CardTitle>
          <div className="flex items-center gap-2 flex-wrap">
            {/* Show protocol badge when available, fall back to source only when no protocol is set */}
            {pair.protocol ? (
              <Badge className={cn(getProtocolBadgeColor(pair.protocol))}>
                {getProtocolLabel(pair.protocol)}
              </Badge>
            ) : (
              <Badge variant="outline" className={cn(getSourceBadgeColor())}>
                {pair.source === 'bisq2' ? 'Bisq 2 Support Chat' : 'Matrix'}
              </Badge>
            )}
            {/* Always show routing badge with user-friendly label */}
            <Badge variant="outline" className={cn(getRoutingBadgeColor())}>
              {getRoutingLabel(pair.routing)}
            </Badge>
            {pair.is_multi_turn && (
              <Badge variant="outline" className="gap-1 text-muted-foreground">
                <MessagesSquare className="h-3 w-3" />
                {pair.message_count} messages
              </Badge>
            )}
            {pair.has_correction && (
              <Badge variant="outline" className="gap-1 text-muted-foreground">
                <AlertTriangle className="h-3 w-3" />
                Correction
              </Badge>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2 text-sm text-muted-foreground flex-wrap">
          {/* Source channel */}
          <span>{pair.source === 'bisq2' ? 'Bisq 2 Support Chat' : pair.source === 'matrix' ? 'Matrix' : pair.source}</span>
          {/* Staff sender - prominent display (single source of truth) */}
          {pair.staff_sender && (
            <>
              <span className="text-border">•</span>
              <Badge variant="outline" className="text-xs font-normal gap-1 py-0 h-5 text-emerald-700 dark:text-emerald-400 border-emerald-500/30">
                <User className="h-3 w-3" />
                {pair.staff_sender}
              </Badge>
            </>
          )}
          <span className="text-border">|</span>
          <span>{formatDate(pair.source_timestamp)}</span>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Original Conversation - FIRST for context (Think in Flows principle) */}
        {/* Shows pre-LLM transformation content to help reviewer understand context */}
        {(pair.original_user_question || pair.original_staff_answer) && (
          <Collapsible defaultOpen={false}>
            <CollapsibleTrigger asChild>
              <button className="w-full flex items-center justify-between p-3 hover:bg-muted/50 rounded-lg transition-colors border border-transparent hover:border-border">
                <div className="flex items-center gap-2">
                  <MessageSquare className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium text-sm">Original Conversation</span>
                  <Badge variant="outline" className="text-xs text-muted-foreground">
                    Before LLM cleanup
                  </Badge>
                </div>
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="space-y-3 px-3 pb-3">
                {pair.original_user_question && (
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <User className="h-3 w-3 text-muted-foreground" />
                      <span className="text-xs font-medium text-muted-foreground">Original User Question</span>
                    </div>
                    <div className="p-3 rounded-md bg-muted/30 border border-border/50">
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap">{pair.original_user_question}</p>
                    </div>
                  </div>
                )}
                {pair.original_staff_answer && (
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <User className="h-3 w-3 text-emerald-600 dark:text-emerald-400" />
                      <span className="text-xs font-medium text-muted-foreground">Original Staff Answer</span>
                    </div>
                    <div className="p-3 rounded-md bg-muted/30 border border-border/50">
                      <p className="text-sm text-muted-foreground whitespace-pre-wrap">{pair.original_staff_answer}</p>
                    </div>
                  </div>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Unified FAQ Edit Section */}
        {/* Single Edit button triggers unified mode for both Q&A (UX improvement) */}
        <div className="space-y-4">
          {/* Header with unified Edit button */}
          {!isEditing && (
            <div className="flex items-center justify-between">
              <span className="font-medium text-sm">FAQ Content</span>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsEditing(true)}
                className="h-7 text-xs"
              >
                <Pencil className="h-3 w-3 mr-1" />
                Edit
              </Button>
            </div>
          )}

          {/* Question Display - Editable */}
          <EditableQuestion
            question={pair.question_text}
            editedQuestion={pair.edited_question_text}
            isEditing={isEditing}
            onEditStart={() => setIsEditing(true)}
            onEditSave={async (q) => { handleQuestionChange(q); }}
            onEditCancel={handleUnifiedCancel}
            label="FAQ Question"
            icon={<User className="h-4 w-4 text-muted-foreground" />}
            isSaving={isSaving}
            hideEditButton={true}
            hideSaveCancel={true}
            onValueChange={handleQuestionChange}
          />

          {/* Answer Comparison */}
          <div className="grid md:grid-cols-2 gap-4">
            {/* Staff Answer - Editable */}
            {/* Staff sender shown in header - no duplication here (Speed Through Subtraction) */}
            <EditableAnswer
              answer={pair.staff_answer}
              editedAnswer={pair.edited_staff_answer}
              isEditing={isEditing}
              onEditStart={() => setIsEditing(true)}
              onEditSave={async (a) => { handleAnswerChange(a); }}
              onEditCancel={handleUnifiedCancel}
              label="FAQ Answer"
              icon={<User className="h-4 w-4 text-emerald-600 dark:text-emerald-400" />}
              isSaving={isSaving}
              hideEditButton={true}
              hideSaveCancel={true}
              onValueChange={handleAnswerChange}
            />

          {/* Generated Answer - Clean, minimal style */}
          <div>
            <div className="flex items-center gap-2 mb-2">
              <Bot className="h-4 w-4 text-muted-foreground" />
              <span className="font-medium text-sm">Suggested Answer</span>
              {pair.generation_confidence !== null && (
                <Badge variant="outline" className="text-xs">
                  {Math.round(pair.generation_confidence * 100)}% confidence
                </Badge>
              )}
              {/* P6: Show "Protocol Required" badge when no protocol is set */}
              {!pair.protocol && (
                <Badge variant="outline" className="text-xs text-amber-600 dark:text-amber-400 border-amber-500/30">
                  <AlertTriangle className="h-3 w-3 mr-1" />
                  Protocol Required
                </Badge>
              )}
              {isRegenerating && (
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>
            <div className={cn(
              "p-4 rounded-lg border min-h-[120px] bg-muted/30 border-border",
              isRegenerating && "animate-pulse"
            )}>
              {pair.generated_answer ? (
                <>
                  <MarkdownContent content={pair.generated_answer} className="text-sm" />
                  {/* Sources and Confidence */}
                  {(pair.generated_answer_sources?.length > 0 || pair.generation_confidence !== null) && (
                    <div className="mt-3 pt-3 border-t border-border/50 flex flex-wrap items-center gap-3">
                      {pair.generated_answer_sources && pair.generated_answer_sources.length > 0 && (
                        <SourceBadges sources={pair.generated_answer_sources} />
                      )}
                      {pair.generation_confidence !== null && (
                        <ConfidenceBadge confidence={pair.generation_confidence} />
                      )}
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">
                  No generated answer available. Select a protocol above to generate one.
                </p>
              )}
            </div>

            {/* Answer Quality Rating for LearningEngine - only show when protocol is set
                For Calibration queue: This is the PRIMARY action (prominent styling)
                For other queues: Secondary action (subtle styling) */}
            {pair.generated_answer && onRateGeneratedAnswer && pair.protocol && (
              <div className={cn(
                "mt-3 flex items-center justify-between p-3 rounded-lg",
                isCalibrationItem
                  ? "bg-primary/5 border-2 border-primary/20"  // Prominent for calibration
                  : "bg-muted/20 border border-dashed border-border"  // Subtle for others
              )}>
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "text-sm",
                    isCalibrationItem ? "text-foreground font-medium" : "text-muted-foreground"
                  )}>
                    {isCalibrationItem
                      ? "Rate this answer for auto-send calibration:"
                      : "Would this answer be good enough to auto-send?"}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {answerRating ? (
                    <div className="flex items-center gap-2" role="status" aria-live="polite">
                      {answerRating === 'good' ? (
                        <ThumbsUp className="h-4 w-4 text-green-500" aria-hidden="true" />
                      ) : (
                        <ThumbsDown className="h-4 w-4 text-amber-500" aria-hidden="true" />
                      )}
                      <span className={cn(
                        "text-sm font-medium",
                        answerRating === 'good' ? "text-green-600 dark:text-green-400" : "text-amber-600 dark:text-amber-400"
                      )}>
                        {answerRating === 'good' ? 'Rated: Good' : 'Rated: Needs Improvement'}
                      </span>
                    </div>
                  ) : (
                    <>
                      <Button
                        variant={isCalibrationItem ? "outline" : "outline"}
                        size={isCalibrationItem ? "default" : "sm"}
                        onClick={() => handleRateGeneratedAnswer('needs_improvement')}
                        disabled={isRatingAnswer || isLoading}
                        className={cn(
                          "text-amber-600 hover:text-amber-700 hover:bg-amber-50 dark:text-amber-400 dark:hover:bg-amber-950",
                          isCalibrationItem && "border-amber-300 dark:border-amber-700"
                        )}
                        aria-label="Rate this generated answer as needs improvement - not suitable for auto-send"
                      >
                        {isRatingAnswer ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        ) : (
                          <ThumbsDown className={cn("mr-1", isCalibrationItem ? "h-5 w-5" : "h-4 w-4")} aria-hidden="true" />
                        )}
                        Needs Work
                      </Button>
                      <Button
                        variant={isCalibrationItem ? "outline" : "outline"}
                        size={isCalibrationItem ? "default" : "sm"}
                        onClick={() => handleRateGeneratedAnswer('good')}
                        disabled={isRatingAnswer || isLoading}
                        className={cn(
                          "text-green-600 hover:text-green-700 hover:bg-green-50 dark:text-green-400 dark:hover:bg-green-950",
                          isCalibrationItem && "border-green-300 dark:border-green-700"
                        )}
                        aria-label="Rate this generated answer as good - suitable for auto-send"
                      >
                        {isRatingAnswer ? (
                          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                        ) : (
                          <ThumbsUp className={cn("mr-1", isCalibrationItem ? "h-5 w-5" : "h-4 w-4")} aria-hidden="true" />
                        )}
                        Good Answer
                      </Button>
                    </>
                  )}
                </div>
              </div>
            )}
          </div>
        </div>

          {/* Unified Edit Mode Action Bar */}
          {isEditing && (
            <div className="mt-3 flex items-center gap-2 p-3 rounded-lg bg-muted/30 border border-border">
              <Button size="sm" onClick={handleUnifiedSave} disabled={isSaving}>
                {isSaving ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Check className="h-4 w-4 mr-1" />
                    Save Changes
                  </>
                )}
              </Button>
              <Button variant="outline" size="sm" onClick={handleUnifiedCancel} disabled={isSaving}>
                <X className="h-4 w-4 mr-1" />
                Cancel
              </Button>
              <span className="text-xs text-muted-foreground ml-2">
                Press <kbd className="px-1 py-0.5 bg-muted rounded text-xs">⌘↵</kbd> to save |{" "}
                <kbd className="px-1 py-0.5 bg-muted rounded text-xs">Esc</kbd> to cancel
              </span>
            </div>
          )}
        </div>

        {/* Category and Protocol - grouped in combining frame */}
        <div className="p-4 rounded-lg bg-muted/30 border border-border">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <CategorySelector
              currentCategory={currentCategory}
              suggestedCategory={pair.category}
              onCategoryChange={handleCategoryChange}
              onSaveCategory={handleSaveCategory}
              isSaving={isSavingCategory}
            />
            <ProtocolSelector
              currentProtocol={currentProtocol}
              onProtocolChange={handleProtocolChange}
              onRegenerateAnswer={handleRegenerateAnswer}
              isRegenerating={isRegenerating}
              showRegeneratePrompt={!pair.generated_answer}
            />
          </div>
        </div>

        {/* Score Breakdown - P6: Hide when no protocol is set (score is meaningless without protocol context) */}
        {/* Progressive Disclosure: Auto-expand for FULL_REVIEW items (critical decision info) */}
        {pair.protocol && (
          <ScoreBreakdown
            embeddingSimilarity={pair.embedding_similarity}
            factualAlignment={pair.factual_alignment}
            contradictionScore={pair.contradiction_score}
            completeness={pair.completeness}
            hallucinationRisk={pair.hallucination_risk}
            finalScore={pair.final_score}
            generationConfidence={pair.generation_confidence}
            defaultCollapsed={pair.routing !== 'FULL_REVIEW'}
          />
        )}

        {/* LLM Reasoning - Collapsible - P6: Hide when no protocol is set */}
        {pair.llm_reasoning && pair.protocol && (
          <Collapsible defaultOpen={false}>
            <CollapsibleTrigger asChild>
              <button className="w-full flex items-center justify-between p-3 hover:bg-muted/50 rounded-lg transition-colors border border-transparent hover:border-border">
                <div className="flex items-center gap-2">
                  <Bot className="h-4 w-4 text-muted-foreground" />
                  <div className="flex flex-col items-start">
                    <span className="font-medium text-sm">LLM Analysis</span>
                    <span className="text-xs text-muted-foreground">AI explanation of how the answers compare</span>
                  </div>
                </div>
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              </button>
            </CollapsibleTrigger>
            <CollapsibleContent>
              <div className="px-3 pb-3">
                <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                  {pair.llm_reasoning}
                </p>
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Collapsible Full Conversation Context (multi-turn messages) */}
        {conversationMessages.length > 0 && (
          <Collapsible open={showConversation} onOpenChange={setShowConversation}>
            <CollapsibleTrigger asChild>
              <Button variant="ghost" className="w-full justify-between hover:bg-muted">
                <span className="flex items-center gap-2">
                  <MessagesSquare className="h-4 w-4" />
                  {showConversation ? 'Hide' : 'View'} full conversation
                  ({conversationMessages.length} messages)
                </span>
                {showConversation ? (
                  <ChevronUp className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="mt-3">
              <div className="space-y-2 p-4 bg-muted/50 rounded-lg max-h-[400px] overflow-y-auto">
                {conversationMessages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={cn(
                      "p-3 rounded-lg",
                      msg.sender === pair.staff_sender || msg.sender.toLowerCase().includes('staff')
                        ? "bg-muted/50 ml-4 border-l-2 border-muted-foreground/30"
                        : "bg-background mr-4 border-l-2 border-border",
                      idx === correctionIndex && "ring-1 ring-muted-foreground/30"
                    )}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-xs font-medium text-muted-foreground">
                        {msg.sender}
                      </span>
                      {msg.timestamp && (
                        <span className="text-xs text-muted-foreground">
                          {formatDate(msg.timestamp)}
                        </span>
                      )}
                      {idx === correctionIndex && (
                        <Badge variant="outline" className="text-xs h-5 text-muted-foreground">
                          <AlertTriangle className="h-3 w-3 mr-1" />
                          Correction
                        </Badge>
                      )}
                    </div>
                    <p className={cn(
                      "text-sm whitespace-pre-wrap",
                      idx < correctionIndex && correctionIndex !== -1 && msg.sender === pair.staff_sender
                        ? "opacity-60 line-through"
                        : ""
                    )}>
                      {msg.content}
                    </p>
                  </div>
                ))}
              </div>
              <p className="text-xs text-muted-foreground mt-2 text-center">
                Press <kbd className="px-1 py-0.5 bg-muted rounded text-xs">C</kbd> to toggle conversation view
              </p>
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>

      <CardFooter ref={footerRef} className="flex justify-between border-t pt-4">
        <div className="text-xs text-muted-foreground">
          {isCalibrationItem ? (
            // Calibration queue: Primary action is rating, Skip to move to next
            <>
              Primary: Rate answer quality above | {" "}
              <kbd className="px-1 py-0.5 bg-muted rounded text-xs">S</kbd> Next
            </>
          ) : (
            // Knowledge/Minor Gap queues: Standard approve/reject/skip
            <>
              Press: <kbd className="px-1 py-0.5 bg-muted rounded text-xs">A</kbd> Approve |{" "}
              <kbd className="px-1 py-0.5 bg-muted rounded text-xs">R</kbd> Reject |{" "}
              <kbd className="px-1 py-0.5 bg-muted rounded text-xs">S</kbd> Skip |{" "}
              <kbd className="px-1 py-0.5 bg-muted rounded text-xs">E</kbd> Edit
              {pair.conversation_context && (
                <> | <kbd className="px-1 py-0.5 bg-muted rounded text-xs">C</kbd> Conversation</>
              )}
            </>
          )}
        </div>

        <TooltipProvider delayDuration={300}>
          <div className="flex items-center gap-2">
            {isCalibrationItem ? (
              // Calibration queue: Skip is primary (move to next after rating)
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      onClick={onSkip}
                      disabled={isLoading}
                      className="bg-primary hover:bg-primary/90"
                      aria-label="Move to next candidate after rating"
                    >
                      <SkipForward className="h-4 w-4 mr-2" />
                      Next
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>Move to next candidate (rating saved)</p>
                  </TooltipContent>
                </Tooltip>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      onClick={onApprove}
                      disabled={isLoading}
                      aria-label="Optionally create FAQ from this candidate"
                    >
                      {isLoading ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <PlusCircle className="h-4 w-4 mr-2" />
                      )}
                      Create FAQ
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>Optional: Also create FAQ from this</p>
                  </TooltipContent>
                </Tooltip>
              </>
            ) : (
              // Knowledge/Minor Gap queues: Standard actions
              <>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant="outline"
                      onClick={onSkip}
                      disabled={isLoading}
                      aria-label="Skip this candidate and move to the next one"
                    >
                      <SkipForward className="h-4 w-4 mr-2" />
                      Skip
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>Skip for later review</p>
                  </TooltipContent>
                </Tooltip>

                {showRejectSelect ? (
                  <div className="flex items-center gap-1 flex-wrap animate-in fade-in slide-in-from-right-2 duration-200">
                    {REJECT_REASONS.map((reason) => (
                      <Button
                        key={reason.value}
                        variant={reason.value === 'other' ? 'outline' : 'destructive'}
                        size="sm"
                        onClick={() => handleDirectReject(reason.value)}
                        disabled={isLoading}
                        className={reason.value === 'other' ? 'text-destructive border-destructive/50 hover:bg-destructive/10' : ''}
                      >
                        {reason.label}
                      </Button>
                    ))}
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowRejectSelect(false)}
                    >
                      Cancel
                    </Button>
                  </div>
                ) : (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <Button
                        variant="destructive"
                        onClick={() => setShowRejectSelect(true)}
                        disabled={isLoading}
                        aria-label="Reject this FAQ candidate"
                      >
                        <XCircle className="h-4 w-4 mr-2" />
                        Reject
                      </Button>
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <p>Discard this FAQ candidate</p>
                    </TooltipContent>
                  </Tooltip>
                )}

                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      onClick={onApprove}
                      disabled={isLoading}
                      className="bg-green-600 hover:bg-green-700"
                      aria-label="Approve this candidate and create a new FAQ entry"
                    >
                      {isLoading ? (
                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                      ) : (
                        <PlusCircle className="h-4 w-4 mr-2" />
                      )}
                      Approve & Create FAQ
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="top">
                    <p>Fill this gap in knowledge by creating an FAQ</p>
                  </TooltipContent>
                </Tooltip>
              </>
            )}
          </div>
        </TooltipProvider>
      </CardFooter>

      {/* Reject Confirmation Dialog - Only for "Other" reason */}
      <AlertDialog open={pendingRejectReason === 'other'} onOpenChange={(open) => !open && handleCancelReject()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Reject with &quot;Other&quot; Reason</AlertDialogTitle>
            <AlertDialogDescription>
              You selected &quot;Other&quot; as the rejection reason. This will reject the FAQ candidate with a generic reason.
              <span className="block mt-2 text-muted-foreground text-xs">
                Tip: If possible, use a specific reason like &quot;Incorrect information&quot; or &quot;Outdated content&quot; for better tracking.
              </span>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={handleCancelReject}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleConfirmReject}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Reject FAQ
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Sticky Action Footer - appears when original footer scrolls out of view */}
      <StickyActionFooter
        isVisible={showStickyFooter}
        candidateId={pair.id}
        score={pair.final_score}
        category={pair.category}
        routing={pair.routing}
        isLoading={isLoading}
        onApprove={onApprove}
        onReject={() => setShowRejectSelect(true)}
        onSkip={onSkip}
      />
    </Card>
  );
}
