import { useState } from 'react';
import { makeAuthenticatedRequest } from '@/lib/auth';

export interface FeedbackItem {
  message_id: string;
  [key: string]: any;
}

export function useFeedbackDeletion(onSuccess: () => void) {
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [feedbackToDelete, setFeedbackToDelete] = useState<FeedbackItem | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [error, setError] = useState<string>('');

  const openDeleteConfirmation = (feedback: FeedbackItem) => {
    setFeedbackToDelete(feedback);
    setShowDeleteConfirm(true);
    setError('');
  };

  const closeDeleteConfirmation = () => {
    setShowDeleteConfirm(false);
    setFeedbackToDelete(null);
    setError('');
  };

  const handleDelete = async () => {
    if (!feedbackToDelete) return;

    setIsDeleting(true);
    setError('');

    try {
      const response = await makeAuthenticatedRequest(
        `/admin/feedback/${feedbackToDelete.message_id}`,
        {
          method: 'DELETE',
        }
      );

      if (response.ok) {
        closeDeleteConfirmation();
        onSuccess();
      } else {
        const errorText = `Failed to delete feedback. Status: ${response.status}`;
        setError(errorText);
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'An unknown error occurred';
      setError(`Error deleting feedback: ${errorMessage}`);
    } finally {
      setIsDeleting(false);
    }
  };

  return {
    showDeleteConfirm,
    feedbackToDelete,
    isDeleting,
    error,
    openDeleteConfirmation,
    closeDeleteConfirmation,
    handleDelete,
  };
}
