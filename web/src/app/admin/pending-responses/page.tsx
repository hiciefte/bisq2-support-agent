/**
 * Pending Moderator Review Queue Page
 *
 * Displays pending responses awaiting moderator approval.
 *
 * Design Principles Applied:
 * - Speed Through Subtraction: Simple queue counter, no stats dashboard
 * - Spatial Consistency: Predictable layout with fixed search position
 * - Progressive Disclosure: Minimal initial view, details in cards
 * - Feedback Immediacy: Optimistic UI updates with rollback on error
 */

'use client';

import { useState, useEffect, useCallback } from 'react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { PendingResponseCard } from '@/components/admin/PendingResponseCard';
import { EditAnswerModal } from '@/components/admin/EditAnswerModal';
import { toast } from 'sonner';
import { useDebouncedValue } from '@/hooks/useDebouncedValue';
import type { PendingResponse } from '@/types/pending-response';
import { API_BASE_URL } from '@/lib/config';

export function PendingReviewQueuePage() {
  const [responses, setResponses] = useState<PendingResponse[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [editingResponse, setEditingResponse] = useState<PendingResponse | null>(null);
  const [removingIds, setRemovingIds] = useState<Set<string>>(new Set());

  // Debounce search query (300ms)
  const debouncedSearch = useDebouncedValue(searchQuery, 300);

  // Fetch pending responses
  const fetchResponses = useCallback(async () => {
    try {
      setError(null);
      const response = await fetch(`${API_BASE_URL}/admin/pending`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to fetch pending responses');
      }

      const data = await response.json();
      setResponses(data.responses || []);
      setIsLoading(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load pending responses');
      setIsLoading(false);
    }
  }, []);

  // Initial fetch and polling (30s interval)
  useEffect(() => {
    fetchResponses();

    const pollInterval = setInterval(() => {
      fetchResponses();
    }, 30000); // 30 seconds

    return () => clearInterval(pollInterval);
  }, [fetchResponses]);

  // Client-side search filter
  const filteredResponses = responses.filter((response) => {
    if (!debouncedSearch) return true;

    const searchLower = debouncedSearch.toLowerCase();
    const questionMatch = response.question.toLowerCase().includes(searchLower);
    const answerMatch = response.answer.toLowerCase().includes(searchLower);

    return questionMatch || answerMatch;
  });

  // Approve response
  const handleApprove = async (responseId: string) => {
    // Optimistic UI update
    setRemovingIds((prev) => new Set(prev).add(responseId));
    const originalResponses = [...responses];

    setTimeout(() => {
      setResponses((prev) => prev.filter((r) => r.id !== responseId));
    }, 200); // Wait for fade-out animation

    try {
      const response = await fetch(`${API_BASE_URL}/admin/pending/${responseId}/approve`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to approve response');
      }

      toast.success('✓ Response approved and sent');
    } catch (err) {
      // Rollback on error
      setResponses(originalResponses);
      setRemovingIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(responseId);
        return newSet;
      });
      toast.error('⚠️ Failed to approve response');
    }
  };

  // Reject response
  const handleReject = async (responseId: string) => {
    // Optimistic UI update
    setRemovingIds((prev) => new Set(prev).add(responseId));
    const originalResponses = [...responses];

    setTimeout(() => {
      setResponses((prev) => prev.filter((r) => r.id !== responseId));
    }, 200);

    try {
      const response = await fetch(`${API_BASE_URL}/admin/pending/${responseId}/reject`, {
        method: 'POST',
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('Failed to reject response');
      }

      toast.success('Response rejected');
    } catch (err) {
      // Rollback on error
      setResponses(originalResponses);
      setRemovingIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(responseId);
        return newSet;
      });
      toast.error('⚠️ Failed to reject response');
    }
  };

  // Open edit modal
  const handleEdit = (response: PendingResponse) => {
    setEditingResponse(response);
  };

  // Save edited answer and approve
  const handleSaveEdit = async (responseId: string, editedAnswer: string) => {
    // Optimistic UI update
    setRemovingIds((prev) => new Set(prev).add(responseId));
    const originalResponses = [...responses];

    setTimeout(() => {
      setResponses((prev) => prev.filter((r) => r.id !== responseId));
    }, 200);

    try {
      const response = await fetch(`${API_BASE_URL}/admin/pending/${responseId}/edit`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answer: editedAnswer }),
      });

      if (!response.ok) {
        throw new Error('Failed to save edited response');
      }

      toast.success('✓ Answer saved and approved');
      setEditingResponse(null);
    } catch (err) {
      // Rollback on error
      setResponses(originalResponses);
      setRemovingIds((prev) => {
        const newSet = new Set(prev);
        newSet.delete(responseId);
        return newSet;
      });
      toast.error('⚠️ Failed to save edited answer');
    }
  };

  // Loading state
  if (isLoading) {
    return (
      <div className="container mx-auto py-8">
        <div className="text-center text-muted-foreground">Loading pending responses...</div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="container mx-auto py-8">
        <div className="text-center">
          <p className="text-red-500 mb-4">Failed to load pending responses</p>
          <Button onClick={() => fetchResponses()}>Retry</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-8 px-4 max-w-4xl">
      {/* Header with Queue Counter */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h1 className="text-3xl font-bold">Pending Moderator Review</h1>
          <span className="text-lg text-muted-foreground">
            Queue: {filteredResponses.length}
          </span>
        </div>

        {/* Search Input */}
        <Input
          type="text"
          placeholder="Search questions or answers..."
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          className="max-w-md"
        />
      </div>

      {/* Response Cards */}
      {filteredResponses.length === 0 ? (
        <div className="text-center text-muted-foreground py-12">
          {debouncedSearch ? 'No responses found matching your search' : 'No pending responses'}
        </div>
      ) : (
        <div className="space-y-4">
          {filteredResponses.map((response) => (
            <PendingResponseCard
              key={response.id}
              response={response}
              onApprove={() => handleApprove(response.id)}
              onEdit={() => handleEdit(response)}
              onReject={() => handleReject(response.id)}
              isRemoving={removingIds.has(response.id)}
            />
          ))}
        </div>
      )}

      {/* Edit Modal */}
      {editingResponse && (
        <EditAnswerModal
          response={editingResponse}
          onSave={(editedAnswer) => handleSaveEdit(editingResponse.id, editedAnswer)}
          onCancel={() => setEditingResponse(null)}
        />
      )}
    </div>
  );
}

export default PendingReviewQueuePage;
