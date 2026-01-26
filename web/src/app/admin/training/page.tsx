"use client"

import { useState, useEffect, useCallback, useRef } from 'react';
import { Loader2, LayoutGrid, List } from 'lucide-react';
import { toast } from 'sonner';
import { AnimatePresence, motion } from 'framer-motion';
import { makeAuthenticatedRequest } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import { CalibrationBanner } from '@/components/admin/training/CalibrationBanner';
import { QueueStatus } from '@/components/admin/training/QueueStatus';
import { TrainingReviewItem } from '@/components/admin/training/TrainingReviewItem';
import { EmptyQueueState } from '@/components/admin/training/EmptyQueueState';
import { BatchReviewList } from '@/components/admin/training/BatchReviewList';
import { DuplicateFAQDialog } from '@/components/admin/training/DuplicateFAQDialog';
import { useTrainingKeyboard } from '@/hooks/useTrainingKeyboard';
import type { Source } from '@/components/chat/types/chat.types';

// Type for similar FAQ from 409 response
interface SimilarFAQ {
  id: number;
  question: string;
  answer: string;
  similarity: number;
  category?: string | null;
}

// Types - Updated for Unified Pipeline
interface CalibrationStatus {
  samples_collected: number;
  samples_required: number;
  is_complete: boolean;
  auto_approve_threshold: number;
  spot_check_threshold: number;
}

interface QueueCounts {
  FULL_REVIEW: number;
  SPOT_CHECK: number;
  AUTO_APPROVE: number;
}

// Protocol type for RAG generation
type ProtocolType = 'bisq_easy' | 'multisig_v1' | 'musig' | 'all';

// Unified FAQ Candidate type
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
  generation_confidence: number | null;  // RAG's self-assessed confidence
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
  conversation_context: string | null;
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
  // Original conversational staff answer before LLM transformation
  original_staff_answer: string | null;
}

export type RoutingCategory = 'FULL_REVIEW' | 'SPOT_CHECK' | 'AUTO_APPROVE';

// Priority order for queues (higher = higher priority)
const QUEUE_PRIORITY: Record<RoutingCategory, number> = {
  'FULL_REVIEW': 3,
  'SPOT_CHECK': 2,
  'AUTO_APPROVE': 1,
};

// Animation variants for queue transitions
const cardVariants = {
  // Initial state based on direction
  initial: (direction: 'left' | 'right' | 'none') => ({
    opacity: 0,
    x: direction === 'left' ? -60 : direction === 'right' ? 60 : 0,
    scale: direction === 'none' ? 0.98 : 1,
  }),
  // Animate to center
  animate: {
    opacity: 1,
    x: 0,
    scale: 1,
    transition: {
      type: 'spring',
      stiffness: 300,
      damping: 30,
      duration: 0.25,
    },
  },
  // Exit in opposite direction
  exit: (direction: 'left' | 'right' | 'none') => ({
    opacity: 0,
    x: direction === 'left' ? 60 : direction === 'right' ? -60 : 0,
    scale: direction === 'none' ? 0.98 : 1,
    transition: {
      duration: 0.2,
    },
  }),
};

export default function TrainingPage() {
  // State - Using unified pipeline types
  const [calibrationStatus, setCalibrationStatus] = useState<CalibrationStatus | null>(null);
  const [queueCounts, setQueueCounts] = useState<QueueCounts | null>(null);
  const [currentItem, setCurrentItem] = useState<UnifiedCandidate | null>(null);
  const [selectedRouting, setSelectedRouting] = useState<RoutingCategory>('FULL_REVIEW');
  const [isLoading, setIsLoading] = useState(true);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Duplicate FAQ dialog state
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false);
  const [duplicateFaqs, setDuplicateFaqs] = useState<SimilarFAQ[]>([]);
  const [duplicateCandidateQuestion, setDuplicateCandidateQuestion] = useState<string>('');

  // Session tracking for progress indicator and celebration
  const [sessionReviewCount, setSessionReviewCount] = useState(0);
  const [sessionStartTime] = useState(() => Date.now());

  // Undo action state (stores last action for potential future use in undo timeout)
  const [, setLastAction] = useState<{
    type: 'approve' | 'reject' | 'skip';
    candidateId: number;
    faqId?: string;
    timestamp: number;
  } | null>(null);
  const undoTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Animation direction state
  const [animationDirection, setAnimationDirection] = useState<'left' | 'right' | 'none'>('none');
  const previousRoutingRef = useRef<RoutingCategory>(selectedRouting);

  // Batch mode state (for AUTO_APPROVE queue)
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [batchItems, setBatchItems] = useState<UnifiedCandidate[]>([]);
  const [isBatchLoading, setIsBatchLoading] = useState(false);

  // Fetch calibration status - unified endpoint
  const fetchCalibrationStatus = useCallback(async () => {
    try {
      const response = await makeAuthenticatedRequest('/admin/training/unified/calibration/status');
      if (response.ok) {
        const data = await response.json();
        setCalibrationStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch calibration status:', err);
    }
  }, []);

  // Fetch queue counts - unified endpoint
  const fetchQueueCounts = useCallback(async () => {
    try {
      const response = await makeAuthenticatedRequest('/admin/training/unified/queue/counts');
      if (response.ok) {
        const data = await response.json();
        setQueueCounts(data);
      }
    } catch (err) {
      console.error('Failed to fetch queue counts:', err);
    }
  }, []);

  // Fetch current item for review - unified endpoint
  const fetchCurrentItem = useCallback(async () => {
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/unified/queue/current?routing=${selectedRouting}`
      );
      if (response.ok) {
        const data = await response.json();
        // Unified API returns UnifiedCandidate directly (or null)
        setCurrentItem(data);
      } else if (response.status === 404) {
        setCurrentItem(null);
      }
    } catch (err) {
      console.error('Failed to fetch current item:', err);
      setCurrentItem(null);
    }
  }, [selectedRouting]);

  // Fetch all data
  const fetchData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      await Promise.all([
        fetchCalibrationStatus(),
        fetchQueueCounts(),
        fetchCurrentItem()
      ]);
    } catch (err) {
      setError('Failed to load training data');
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, [fetchCalibrationStatus, fetchQueueCounts, fetchCurrentItem]);

  // Fetch batch items for batch mode
  const fetchBatchItems = useCallback(async () => {
    setIsBatchLoading(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/unified/queue/batch?routing=${selectedRouting}&limit=10`
      );
      if (response.ok) {
        const data = await response.json();
        setBatchItems(data.items || []);
      }
    } catch (err) {
      console.error('Failed to fetch batch items:', err);
      setBatchItems([]);
    } finally {
      setIsBatchLoading(false);
    }
  }, [selectedRouting]);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Refetch when routing changes
  useEffect(() => {
    if (isBatchMode) {
      fetchBatchItems();
    } else {
      fetchCurrentItem();
    }
  }, [selectedRouting, isBatchMode, fetchCurrentItem, fetchBatchItems]);

  // Handle batch approve
  const handleBatchApprove = async (ids: number[]) => {
    try {
      const response = await makeAuthenticatedRequest(
        '/admin/training/candidates/batch-approve',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ candidate_ids: ids, reviewer: 'admin' })
        }
      );

      if (response.ok) {
        const result = await response.json();
        // Track session progress
        setSessionReviewCount(prev => prev + result.approved_count);

        // Show success toast
        toast.success(`Approved ${result.approved_count} items`, {
          description: result.failed_ids.length > 0
            ? `${result.failed_ids.length} items failed`
            : undefined,
          duration: 3000,
        });

        // Refresh data
        await Promise.all([fetchQueueCounts(), fetchBatchItems()]);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to batch approve');
      }
    } catch (err) {
      setError('Failed to batch approve candidates');
      console.error(err);
    }
  };

  // Handle expand item from batch view
  const handleExpandBatchItem = (candidate: UnifiedCandidate) => {
    setIsBatchMode(false);
    setCurrentItem(candidate);
  };

  // Handle approve action - unified endpoint
  const handleApprove = async () => {
    if (!currentItem) return;

    const candidateId = currentItem.id;
    setIsActionLoading(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}/approve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reviewer: 'admin' })
        }
      );

      if (response.ok) {
        const result = await response.json();
        // Track session progress
        setSessionReviewCount(prev => prev + 1);
        // Store for undo
        setLastAction({
          type: 'approve',
          candidateId,
          faqId: result.faq_id,
          timestamp: Date.now()
        });
        // Clear any existing undo timeout
        if (undoTimeoutRef.current) {
          clearTimeout(undoTimeoutRef.current);
        }
        // Set undo timeout (5 seconds)
        undoTimeoutRef.current = setTimeout(() => {
          setLastAction(null);
        }, 5000);
        // Show success toast with undo option
        toast.success('FAQ created successfully', {
          description: `Candidate #${candidateId} approved`,
          duration: 5000,
          action: {
            label: 'Undo',
            onClick: () => handleUndoAction(candidateId, 'approve', result.faq_id)
          }
        });
        // Reset animation direction for same-queue navigation
        setAnimationDirection('none');
        // Refresh data after action
        await Promise.all([fetchQueueCounts(), fetchCurrentItem()]);
        if (calibrationStatus && !calibrationStatus.is_complete) {
          await fetchCalibrationStatus();
        }
      } else if (response.status === 409) {
        // Handle duplicate FAQ conflict
        const errorData = await response.json();
        if (errorData.similar_faqs && errorData.similar_faqs.length > 0) {
          setDuplicateFaqs(errorData.similar_faqs);
          setDuplicateCandidateQuestion(currentItem.question_text);
          setShowDuplicateDialog(true);
        } else {
          setError(errorData.detail || 'Similar FAQ already exists');
        }
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to approve');
      }
    } catch (err) {
      setError('Failed to approve candidate');
      console.error(err);
    } finally {
      setIsActionLoading(false);
    }
  };

  // Handle reject action - unified endpoint
  const handleReject = async (reason: string) => {
    if (!currentItem) return;

    const candidateId = currentItem.id;
    setIsActionLoading(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}/reject`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reviewer: 'admin', reason })
        }
      );

      if (response.ok) {
        // Track session progress
        setSessionReviewCount(prev => prev + 1);
        // Store for undo
        setLastAction({
          type: 'reject',
          candidateId,
          timestamp: Date.now()
        });
        // Clear any existing undo timeout
        if (undoTimeoutRef.current) {
          clearTimeout(undoTimeoutRef.current);
        }
        // Set undo timeout (5 seconds)
        undoTimeoutRef.current = setTimeout(() => {
          setLastAction(null);
        }, 5000);
        // Show toast with undo option
        toast('Candidate rejected', {
          description: `Reason: ${reason}`,
          duration: 5000,
          action: {
            label: 'Undo',
            onClick: () => handleUndoAction(candidateId, 'reject')
          }
        });
        // Reset animation direction for same-queue navigation
        setAnimationDirection('none');
        await Promise.all([fetchQueueCounts(), fetchCurrentItem()]);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to reject');
      }
    } catch (err) {
      setError('Failed to reject candidate');
      console.error(err);
    } finally {
      setIsActionLoading(false);
    }
  };

  // Handle skip action - unified endpoint
  const handleSkip = async () => {
    if (!currentItem) return;

    setIsActionLoading(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}/skip`,
        { method: 'POST' }
      );

      if (response.ok) {
        // Show skip toast (no undo for skip - it just reorders)
        toast('Skipped for later', {
          description: 'Item moved to end of queue',
          duration: 2000
        });
        // Reset animation direction for same-queue navigation
        setAnimationDirection('none');
        await fetchCurrentItem();
      }
    } catch (err) {
      console.error('Failed to skip:', err);
    } finally {
      setIsActionLoading(false);
    }
  };

  // Handle undo action
  const handleUndoAction = async (candidateId: number, actionType: 'approve' | 'reject', faqId?: string) => {
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${candidateId}/undo`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action_type: actionType, faq_id: faqId })
        }
      );

      if (response.ok) {
        // Decrement session count
        setSessionReviewCount(prev => Math.max(0, prev - 1));
        // Clear last action
        setLastAction(null);
        if (undoTimeoutRef.current) {
          clearTimeout(undoTimeoutRef.current);
        }
        toast.success('Action undone', {
          description: `Candidate #${candidateId} restored to queue`,
          duration: 3000
        });
        // Refresh data
        await Promise.all([fetchQueueCounts(), fetchCurrentItem()]);
      } else {
        toast.error('Failed to undo', {
          description: 'The action could not be undone',
          duration: 3000
        });
      }
    } catch (err) {
      console.error('Failed to undo:', err);
      toast.error('Failed to undo', {
        description: 'Network error',
        duration: 3000
      });
    }
  };

  // Handle routing change with animation direction
  const handleRoutingChange = (routing: RoutingCategory) => {
    const currentPriority = QUEUE_PRIORITY[previousRoutingRef.current];
    const newPriority = QUEUE_PRIORITY[routing];

    // Determine animation direction based on priority
    // Moving to higher priority = slide from left
    // Moving to lower priority = slide from right
    if (newPriority > currentPriority) {
      setAnimationDirection('left');
    } else if (newPriority < currentPriority) {
      setAnimationDirection('right');
    } else {
      setAnimationDirection('none');
    }

    previousRoutingRef.current = routing;
    setSelectedRouting(routing);
  };

  // Handle update candidate (edited answer or category)
  const handleUpdateCandidate = async (updates: { edited_staff_answer?: string; category?: string }) => {
    if (!currentItem) return;

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}`,
        {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updates)
        }
      );

      if (response.ok) {
        const updatedCandidate = await response.json();
        setCurrentItem(updatedCandidate);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to update candidate');
      }
    } catch (err) {
      setError('Failed to update candidate');
      console.error(err);
    }
  };

  // Handle regenerate answer with protocol
  const handleRegenerateAnswer = async (protocol: ProtocolType) => {
    if (!currentItem) return;

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}/regenerate`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ protocol })
        }
      );

      if (response.ok) {
        const updatedCandidate = await response.json();
        setCurrentItem(updatedCandidate);
      } else {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to regenerate answer');
      }
    } catch (err) {
      setError('Failed to regenerate answer');
      console.error(err);
    }
  };

  // Handle rating the generated answer quality for LearningEngine training
  const handleRateGeneratedAnswer = async (rating: 'good' | 'needs_improvement') => {
    if (!currentItem) return;

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}/rate-answer`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ rating, reviewer: 'admin' })
        }
      );

      if (!response.ok) {
        const errorData = await response.json();
        setError(errorData.detail || 'Failed to rate answer');
      }
    } catch (err) {
      setError('Failed to rate answer');
      console.error(err);
    }
  };

  // Handle reject as duplicate from dialog
  const handleRejectAsDuplicate = async () => {
    setShowDuplicateDialog(false);
    await handleReject('Duplicate of existing FAQ');
  };

  // Close duplicate dialog
  const closeDuplicateDialog = () => {
    setShowDuplicateDialog(false);
    setDuplicateFaqs([]);
    setDuplicateCandidateQuestion('');
  };

  // Keyboard shortcuts
  useTrainingKeyboard({
    onApprove: handleApprove,
    onReject: () => {
      // Trigger reject with default reason - UI will prompt for specific reason
      if (currentItem) {
        handleReject('other');
      }
    },
    onSkip: handleSkip,
    enabled: !!currentItem && !isActionLoading
  });

  if (isLoading) {
    return (
      <div className="p-4 md:p-8 pt-16 lg:pt-8 flex items-center justify-center min-h-[400px]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 space-y-6 pt-16 lg:pt-8">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold">Training Pipeline</h1>
        <p className="text-muted-foreground">
          Review and approve training pairs for automatic FAQ generation
        </p>
      </div>

      {/* Error Display */}
      {error && (
        <div className="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative" role="alert">
          <strong className="font-bold">Error: </strong>
          <span className="block sm:inline">{error}</span>
          <button
            className="absolute top-0 bottom-0 right-0 px-4 py-3"
            onClick={() => setError(null)}
          >
            <span className="sr-only">Dismiss</span>
            <span aria-hidden="true">&times;</span>
          </button>
        </div>
      )}

      {/* Calibration Banner */}
      {calibrationStatus && (
        <CalibrationBanner status={calibrationStatus} />
      )}

      {/* Queue Status */}
      {queueCounts && (
        <QueueStatus
          counts={queueCounts}
          selectedRouting={selectedRouting}
          onRoutingChange={handleRoutingChange}
        />
      )}

      {/* Session Progress Indicator with Batch Mode Toggle */}
      {queueCounts && (
        <div className="flex items-center justify-between text-sm text-muted-foreground bg-muted/30 px-4 py-2 rounded-lg border border-border">
          <span>
            <span className="font-medium text-foreground">{sessionReviewCount}</span> reviewed this session
          </span>
          <div className="flex items-center gap-4">
            <span>
              <span className="font-medium text-foreground">{queueCounts[selectedRouting]}</span> remaining in {
                selectedRouting === 'FULL_REVIEW' ? 'knowledge gap' :
                selectedRouting === 'SPOT_CHECK' ? 'minor gap' : 'calibration'
              }
            </span>
            {/* Batch mode toggle - only shown for AUTO_APPROVE queue */}
            {selectedRouting === 'AUTO_APPROVE' && queueCounts.AUTO_APPROVE > 1 && (
              <Button
                variant={isBatchMode ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  setIsBatchMode(!isBatchMode);
                  if (!isBatchMode) {
                    fetchBatchItems();
                  }
                }}
                className="gap-2"
              >
                {isBatchMode ? (
                  <>
                    <List className="h-4 w-4" />
                    Single View
                  </>
                ) : (
                  <>
                    <LayoutGrid className="h-4 w-4" />
                    Batch Mode
                  </>
                )}
              </Button>
            )}
          </div>
        </div>
      )}

      {/* Batch Review Mode */}
      {isBatchMode && selectedRouting === 'AUTO_APPROVE' ? (
        <BatchReviewList
          candidates={batchItems}
          isLoading={isBatchLoading}
          onBatchApprove={handleBatchApprove}
          onExpandItem={handleExpandBatchItem}
        />
      ) : (
        /* Training Review Item or Empty State with animations */
        <AnimatePresence mode="wait" custom={animationDirection}>
          {currentItem ? (
            <motion.div
              key={`item-${currentItem.id}-${selectedRouting}`}
              custom={animationDirection}
              variants={cardVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              <TrainingReviewItem
                pair={currentItem}
                onApprove={handleApprove}
                onReject={handleReject}
                onSkip={handleSkip}
                onUpdateCandidate={handleUpdateCandidate}
                onRegenerateAnswer={handleRegenerateAnswer}
                onRateGeneratedAnswer={handleRateGeneratedAnswer}
                isLoading={isActionLoading}
              />
            </motion.div>
          ) : (
            <motion.div
              key={`empty-${selectedRouting}`}
              custom={animationDirection}
              variants={cardVariants}
              initial="initial"
              animate="animate"
              exit="exit"
            >
              <EmptyQueueState
                routing={selectedRouting}
                onSwitchRouting={handleRoutingChange}
                queueCounts={queueCounts}
                sessionReviewCount={sessionReviewCount}
                sessionStartTime={sessionStartTime}
              />
            </motion.div>
          )}
        </AnimatePresence>
      )}

      {/* Duplicate FAQ Dialog */}
      <DuplicateFAQDialog
        isOpen={showDuplicateDialog}
        onClose={closeDuplicateDialog}
        onRejectAsDuplicate={handleRejectAsDuplicate}
        similarFaqs={duplicateFaqs}
        candidateQuestion={duplicateCandidateQuestion}
      />
    </div>
  );
}
