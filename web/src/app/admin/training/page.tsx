"use client"

import dynamic from "next/dynamic";
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { AlertCircle, BarChart3, Eye, LayoutGrid, List, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import { makeAuthenticatedRequest } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import { CalibrationBanner } from '@/components/admin/training/CalibrationBanner';
import { AdminQueueShell } from '@/components/admin/queue/AdminQueueShell';
import { QueuePageHeader } from '@/components/admin/queue/QueuePageHeader';
import { QueueTabs } from '@/components/admin/queue/QueueTabs';
import { QueueCommandBar } from '@/components/admin/queue/QueueCommandBar';
import { useAdminPollingQuery } from '@/hooks/useAdminPollingQuery';
import { useTrainingKeyboard } from '@/hooks/useTrainingKeyboard';
import type {
  CalibrationStatus,
  ProtocolType,
  QueueCounts,
  RoutingCategory,
  SimilarFAQ,
  UnifiedCandidate,
} from '@/components/admin/training/types';

const TrainingReviewItem = dynamic(
  () => import('@/components/admin/training/TrainingReviewItem').then((m) => m.TrainingReviewItem),
  {
    loading: () => (
      <div className="rounded-lg border border-border bg-card/50 p-8 text-sm text-muted-foreground">
        Loading review item...
      </div>
    ),
  },
);

const EmptyQueueState = dynamic(
  () => import('@/components/admin/training/EmptyQueueState').then((m) => m.EmptyQueueState),
);

const BatchReviewList = dynamic(
  () => import('@/components/admin/training/BatchReviewList').then((m) => m.BatchReviewList),
  {
    loading: () => (
      <div className="rounded-lg border border-border bg-card/50 p-8 text-sm text-muted-foreground">
        Loading batch candidates...
      </div>
    ),
  },
);

const DuplicateFAQDialog = dynamic(
  () => import('@/components/admin/training/DuplicateFAQDialog').then((m) => m.DuplicateFAQDialog),
);

const ROUTING_LABELS: Record<RoutingCategory, string> = {
  FULL_REVIEW: 'Knowledge Gap',
  SPOT_CHECK: 'Minor Gap',
  AUTO_APPROVE: 'Calibration',
};

const TRAINING_SHORTCUT_HINTS = [
  { keyCombo: 'A', label: 'Approve' },
  { keyCombo: 'R', label: 'Reject' },
  { keyCombo: 'S', label: 'Skip' },
  { keyCombo: 'E', label: 'Edit Q&A' },
  { keyCombo: 'C', label: 'Toggle conversation' },
];

function formatTimeAgo(date: Date): string {
  const diffMs = Date.now() - date.getTime();
  const diffMinutes = Math.floor(diffMs / 60000);
  if (diffMinutes < 1) return 'just now';
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

export default function TrainingPage() {
  // State - Using unified pipeline types
  const [calibrationStatus, setCalibrationStatus] = useState<CalibrationStatus | null>(null);
  const [queueCounts, setQueueCounts] = useState<QueueCounts | null>(null);
  const [currentItem, setCurrentItem] = useState<UnifiedCandidate | null>(null);
  const [selectedRouting, setSelectedRouting] = useState<RoutingCategory>('FULL_REVIEW');
  const [isLoading, setIsLoading] = useState(true);
  const [isActionLoading, setIsActionLoading] = useState(false);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [openRejectMenuSignal, setOpenRejectMenuSignal] = useState(0);
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
  const calibrationRequestId = useRef(0);
  const queueCountRequestId = useRef(0);
  const currentItemRequestId = useRef(0);
  const batchRequestId = useRef(0);

  // Batch mode state (for AUTO_APPROVE queue)
  const [isBatchMode, setIsBatchMode] = useState(false);
  const [batchItems, setBatchItems] = useState<UnifiedCandidate[]>([]);
  const [isBatchLoading, setIsBatchLoading] = useState(false);

  // Fetch calibration status - unified endpoint
  const fetchCalibrationStatus = useCallback(async () => {
    const requestId = ++calibrationRequestId.current;
    try {
      const response = await makeAuthenticatedRequest('/admin/training/unified/calibration/status');
      if (requestId !== calibrationRequestId.current) return;

      if (response.ok) {
        const data = await response.json();
        setCalibrationStatus(data);
      }
    } catch (err) {
      if (requestId !== calibrationRequestId.current) return;
      console.error('Failed to fetch calibration status:', err);
    }
  }, []);

  // Fetch queue counts - unified endpoint
  const fetchQueueCounts = useCallback(async () => {
    const requestId = ++queueCountRequestId.current;
    try {
      const response = await makeAuthenticatedRequest('/admin/training/unified/queue/counts');
      if (requestId !== queueCountRequestId.current) return;

      if (response.ok) {
        const data = await response.json();
        setQueueCounts(data);
        setLastUpdatedAt(new Date());
      }
    } catch (err) {
      if (requestId !== queueCountRequestId.current) return;
      console.error('Failed to fetch queue counts:', err);
    }
  }, []);

  // Fetch current item for review - unified endpoint
  const fetchCurrentItem = useCallback(async () => {
    const requestId = ++currentItemRequestId.current;
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/unified/queue/current?routing=${selectedRouting}`
      );
      if (requestId !== currentItemRequestId.current) return;

      if (response.ok) {
        const data = await response.json();
        // Unified API returns UnifiedCandidate directly (or null)
        setCurrentItem(data);
        setLastUpdatedAt(new Date());
      } else if (response.status === 404) {
        setCurrentItem(null);
        setLastUpdatedAt(new Date());
      }
    } catch (err) {
      if (requestId !== currentItemRequestId.current) return;
      console.error('Failed to fetch current item:', err);
      setCurrentItem(null);
    }
  }, [selectedRouting]);

  // Fetch all data
  const fetchData = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) {
      setIsLoading(true);
    }
    setIsRefreshing(true);
    setError(null);
    try {
      await Promise.all([
        fetchCalibrationStatus(),
        fetchQueueCounts(),
        fetchCurrentItem()
      ]);
      setLastUpdatedAt(new Date());
    } catch (err) {
      setError('Failed to load training data');
      console.error(err);
    } finally {
      if (!options?.silent) {
        setIsLoading(false);
      }
      setIsRefreshing(false);
    }
  }, [fetchCalibrationStatus, fetchQueueCounts, fetchCurrentItem]);

  // Fetch batch items for batch mode
  const fetchBatchItems = useCallback(async () => {
    const requestId = ++batchRequestId.current;
    setIsBatchLoading(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/unified/queue/batch?routing=${selectedRouting}&limit=10`
      );
      if (requestId !== batchRequestId.current) return;

      if (response.ok) {
        const data = await response.json();
        setBatchItems(data.items || []);
      }
    } catch (err) {
      if (requestId !== batchRequestId.current) return;
      console.error('Failed to fetch batch items:', err);
      setBatchItems([]);
    } finally {
      if (requestId === batchRequestId.current) {
        setIsBatchLoading(false);
      }
    }
  }, [selectedRouting]);

  // Initial load
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Refetch when routing changes
  useEffect(() => {
    if (selectedRouting === 'AUTO_APPROVE' && isBatchMode) {
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
        // Refresh data after action
        await Promise.all([fetchQueueCounts(), fetchCurrentItem()]);
        if (calibrationStatus && !calibrationStatus.is_complete) {
          await fetchCalibrationStatus();
        }
      } else if (response.status === 409) {
        // Handle duplicate FAQ conflict - detail is an object with similar_faqs
        const errorData = await response.json();
        const detail = errorData.detail;
        if (detail?.similar_faqs && detail.similar_faqs.length > 0) {
          setDuplicateFaqs(detail.similar_faqs);
          setDuplicateCandidateQuestion(currentItem.question_text);
          setShowDuplicateDialog(true);
        } else {
          setError(typeof detail === 'string' ? detail : detail?.message || 'Similar FAQ already exists');
        }
      } else {
        const errorData = await response.json();
        const detail = errorData.detail;
        setError(typeof detail === 'string' ? detail : 'Failed to approve');
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

  // Handle routing change
  const handleRoutingChange = (routing: RoutingCategory) => {
    if (routing !== 'AUTO_APPROVE' && isBatchMode) {
      setIsBatchMode(false);
    }
    setSelectedRouting(routing);
  };

  // Handle update candidate (edited question, answer, or category)
  const handleUpdateCandidate = async (updates: { edited_staff_answer?: string; edited_question_text?: string; category?: string }) => {
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

  // Handle force approve despite similar FAQs
  const handleForceApprove = async () => {
    if (!currentItem) return;

    setShowDuplicateDialog(false);
    setDuplicateFaqs([]);
    setDuplicateCandidateQuestion('');

    const candidateId = currentItem.id;
    setIsActionLoading(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${currentItem.id}/approve`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reviewer: 'admin', force: true })
        }
      );

      if (response.ok) {
        const result = await response.json();
        setSessionReviewCount(prev => prev + 1);
        setLastAction({
          type: 'approve',
          candidateId,
          faqId: result.faq_id,
          timestamp: Date.now()
        });
        if (undoTimeoutRef.current) {
          clearTimeout(undoTimeoutRef.current);
        }
        undoTimeoutRef.current = setTimeout(() => {
          setLastAction(null);
        }, 5000);
        toast.success('FAQ created (similar FAQ exists)', {
          description: `Candidate #${candidateId} force-approved`,
          duration: 5000,
          action: {
            label: 'Undo',
            onClick: () => handleUndoAction(candidateId, 'approve', result.faq_id)
          }
        });
        await Promise.all([fetchQueueCounts(), fetchCurrentItem()]);
        if (calibrationStatus && !calibrationStatus.is_complete) {
          await fetchCalibrationStatus();
        }
      } else {
        const errorData = await response.json();
        const detail = errorData.detail;
        setError(typeof detail === 'string' ? detail : 'Failed to force approve');
      }
    } catch (err) {
      setError('Failed to force approve candidate');
      console.error(err);
    } finally {
      setIsActionLoading(false);
    }
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
    onReject: () => setOpenRejectMenuSignal(prev => prev + 1),
    onSkip: handleSkip,
    enabled: !!currentItem && !isActionLoading
  });

  const lastUpdatedLabel = useMemo(
    () => (lastUpdatedAt ? `Updated ${formatTimeAgo(lastUpdatedAt)}` : null),
    [lastUpdatedAt],
  );

  const routingTabs = useMemo(
    () => [
      {
        key: 'FULL_REVIEW' as const,
        label: 'Knowledge Gap',
        count: queueCounts?.FULL_REVIEW ?? 0,
        icon: AlertCircle,
      },
      {
        key: 'SPOT_CHECK' as const,
        label: 'Minor Gap',
        count: queueCounts?.SPOT_CHECK ?? 0,
        icon: Eye,
      },
      {
        key: 'AUTO_APPROVE' as const,
        label: 'Calibration',
        count: queueCounts?.AUTO_APPROVE ?? 0,
        icon: BarChart3,
      },
    ],
    [queueCounts],
  );

  const activeFilterPills = useMemo(() => {
    if (isBatchMode && selectedRouting === 'AUTO_APPROVE') {
      return ['Mode: Batch review'];
    }
    return [];
  }, [isBatchMode, selectedRouting]);

  useAdminPollingQuery<number, readonly unknown[]>({
    queryKey: ['admin', 'training', 'poll', selectedRouting, isBatchMode] as const,
    queryFn: async () => {
      await fetchData({ silent: true });
      return Date.now();
    },
    enabled: !isLoading && !isActionLoading,
    refetchIntervalMs: 30_000,
  });

  if (isLoading) {
    return (
      <AdminQueueShell showVectorStoreBanner shortcutHints={TRAINING_SHORTCUT_HINTS}>
        <div className="flex items-center justify-center min-h-[400px]">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </AdminQueueShell>
    );
  }

  return (
    <AdminQueueShell showVectorStoreBanner shortcutHints={TRAINING_SHORTCUT_HINTS}>
      <QueuePageHeader
        title="Training Pipeline"
        description="Review and approve training pairs for automatic FAQ generation."
        lastUpdatedLabel={lastUpdatedLabel}
        isRefreshing={isRefreshing}
        onRefresh={() => { void fetchData({ silent: true }); }}
      />

      {/* Error Display */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 text-red-400 px-4 py-3 rounded-lg relative" role="alert">
          <strong className="font-semibold">Error: </strong>
          <span className="text-sm">{error}</span>
          <button
            className="absolute top-2 right-2 p-1 text-red-400/70 hover:text-red-400"
            type="button"
            onClick={() => setError(null)}
          >
            <span className="sr-only">Dismiss</span>
            <span aria-hidden="true">×</span>
          </button>
        </div>
      )}

      {/* Calibration Banner */}
      {calibrationStatus && (
        <CalibrationBanner status={calibrationStatus} />
      )}

      <QueueTabs
        tabs={routingTabs}
        activeTab={selectedRouting}
        onTabChange={handleRoutingChange}
      />

      <QueueCommandBar activeFilterPills={activeFilterPills}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          {queueCounts && (
            <div className="flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
              <span>
                <span className="font-medium text-foreground">{queueCounts[selectedRouting]}</span> pending in {ROUTING_LABELS[selectedRouting]}
              </span>
              <span className="text-border">•</span>
              <span>
                <span className="font-medium text-foreground">{sessionReviewCount}</span> reviewed this session
              </span>
            </div>
          )}
          {queueCounts && selectedRouting === 'AUTO_APPROVE' && queueCounts.AUTO_APPROVE > 1 && (
            <Button
              variant={isBatchMode ? "default" : "outline"}
              size="sm"
              onClick={() => {
                setIsBatchMode(!isBatchMode);
                if (!isBatchMode) {
                  void fetchBatchItems();
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
      </QueueCommandBar>

      {/* Batch Review Mode */}
      {isBatchMode && selectedRouting === 'AUTO_APPROVE' ? (
        <BatchReviewList
          candidates={batchItems}
          isLoading={isBatchLoading}
          onBatchApprove={handleBatchApprove}
          onExpandItem={handleExpandBatchItem}
        />
      ) : (
        <>
          {currentItem ? (
            <TrainingReviewItem
              key={`item-${currentItem.id}-${selectedRouting}`}
              pair={currentItem}
              onApprove={handleApprove}
              onReject={handleReject}
              onSkip={handleSkip}
              onUpdateCandidate={handleUpdateCandidate}
              onRegenerateAnswer={handleRegenerateAnswer}
              onRateGeneratedAnswer={handleRateGeneratedAnswer}
              openRejectMenuSignal={openRejectMenuSignal}
              isLoading={isActionLoading}
            />
          ) : (
            <EmptyQueueState
              key={`empty-${selectedRouting}`}
              routing={selectedRouting}
              onSwitchRouting={handleRoutingChange}
              queueCounts={queueCounts}
              sessionReviewCount={sessionReviewCount}
              sessionStartTime={sessionStartTime}
            />
          )}
        </>
      )}

      {/* Duplicate FAQ Dialog */}
      <DuplicateFAQDialog
        isOpen={showDuplicateDialog}
        onClose={closeDuplicateDialog}
        onRejectAsDuplicate={handleRejectAsDuplicate}
        onForceApprove={handleForceApprove}
        similarFaqs={duplicateFaqs}
        candidateQuestion={duplicateCandidateQuestion}
      />
    </AdminQueueShell>
  );
}
