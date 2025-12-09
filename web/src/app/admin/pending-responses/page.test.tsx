/**
 * Unit tests for PendingReviewQueue page component
 *
 * TDD Implementation: Tests written BEFORE page implementation
 * Following design principles:
 * - Speed Through Subtraction (simple queue counter, no stats dashboard)
 * - Spatial Consistency (predictable layout)
 * - Progressive Disclosure (minimal initial view)
 * - Feedback Immediacy (optimistic UI updates with rollback)
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PendingReviewQueuePage } from './page';

// Mock fetch for API calls
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock sonner toast
jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

// Mock data matching backend API response format
const mockPendingResponses = [
  {
    id: 'response-1',
    question: 'How do I restore my wallet in Bisq 2?',
    answer: 'To restore your wallet in Bisq 2, go to Settings > Backup/Restore...',
    confidence: 0.75,
    detected_version: 'Bisq 2',
    sources: [
      { title: 'Bisq 2 Wallet Guide', url: 'https://bisq.wiki/Bisq_2_Wallet' },
    ],
    created_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(),
  },
  {
    id: 'response-2',
    question: 'What are Bisq Easy trade limits?',
    answer: 'Bisq Easy has a $600 limit for reputation-based trades without security deposits.',
    confidence: 0.82,
    detected_version: 'Bisq 2',
    sources: [
      { title: 'Bisq Easy Guide', url: 'https://bisq.wiki/Bisq_Easy' },
    ],
    created_at: new Date(Date.now() - 5 * 60 * 1000).toISOString(),
  },
  {
    id: 'response-3',
    question: 'How does mediation work?',
    answer: 'Mediation is a dispute resolution process in Bisq 1 where a mediator helps...',
    confidence: 0.68,
    detected_version: 'Bisq 1',
    sources: [
      { title: 'Mediation Guide', url: 'https://bisq.wiki/Mediation' },
    ],
    created_at: new Date(Date.now() - 10 * 60 * 1000).toISOString(),
  },
];

describe('PendingReviewQueuePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ responses: mockPendingResponses }),
    });
  });

  describe('Initial Rendering', () => {
    test('should display page title "Pending Moderator Review"', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /pending moderator review/i })).toBeInTheDocument();
      });
    });

    test('should display queue counter with correct count', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByText(/queue: 3/i)).toBeInTheDocument();
      });
    });

    test('should display search input placeholder', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/search questions or answers/i)).toBeInTheDocument();
      });
    });

    test('should fetch pending responses on mount', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/admin/pending'),
          expect.any(Object)
        );
      });
    });

    test('should render all pending response cards', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        const cards = screen.getAllByTestId('pending-response-card');
        expect(cards).toHaveLength(3);
      });
    });
  });

  describe('Client-Side Search', () => {
    test('should filter responses by question text', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const searchInput = screen.getByPlaceholderText(/search questions or answers/i);
      fireEvent.change(searchInput, { target: { value: 'wallet' } });

      // Wait for debounce (300ms)
      await waitFor(() => {
        const visibleCards = screen.getAllByTestId('pending-response-card');
        expect(visibleCards).toHaveLength(1);
        expect(screen.getByText(/restore my wallet/i)).toBeInTheDocument();
      }, { timeout: 500 });
    });

    test('should filter responses by answer text', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const searchInput = screen.getByPlaceholderText(/search questions or answers/i);
      fireEvent.change(searchInput, { target: { value: 'mediation' } });

      await waitFor(() => {
        const visibleCards = screen.getAllByTestId('pending-response-card');
        expect(visibleCards).toHaveLength(1);
        expect(screen.getByText(/mediation work/i)).toBeInTheDocument();
      }, { timeout: 500 });
    });

    test('should show all responses when search cleared', async () => {
      render(<PendingReviewQueuePage />);

      const searchInput = screen.getByPlaceholderText(/search questions or answers/i);

      // Search
      fireEvent.change(searchInput, { target: { value: 'wallet' } });
      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(1);
      }, { timeout: 500 });

      // Clear search
      fireEvent.change(searchInput, { target: { value: '' } });
      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      }, { timeout: 500 });
    });

    test('should show "no results" message when search returns nothing', async () => {
      render(<PendingReviewQueuePage />);

      const searchInput = screen.getByPlaceholderText(/search questions or answers/i);
      fireEvent.change(searchInput, { target: { value: 'nonexistent query' } });

      await waitFor(() => {
        expect(screen.getByText(/no responses found/i)).toBeInTheDocument();
      }, { timeout: 500 });
    });

    test('should be case-insensitive', async () => {
      render(<PendingReviewQueuePage />);

      const searchInput = screen.getByPlaceholderText(/search questions or answers/i);
      fireEvent.change(searchInput, { target: { value: 'WALLET' } });

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(1);
      }, { timeout: 500 });
    });
  });

  describe('Approve Action', () => {
    test('should approve response with optimistic UI update', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ responses: mockPendingResponses }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true }),
        });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const approveButtons = screen.getAllByRole('button', { name: /approve/i });
      fireEvent.click(approveButtons[0]);

      // Card should disappear immediately (optimistic UI)
      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(2);
      });

      // Queue counter should update
      await waitFor(() => {
        expect(screen.getByText(/queue: 2/i)).toBeInTheDocument();
      });

      // API should be called
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/admin/pending/response-1/approve'),
          expect.objectContaining({ method: 'POST' })
        );
      });
    });

    test('should show success toast after approval', async () => {
      const { toast } = require('sonner');

      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ responses: mockPendingResponses }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true }),
        });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const approveButtons = screen.getAllByRole('button', { name: /approve/i });
      fireEvent.click(approveButtons[0]);

      await waitFor(() => {
        expect(toast.success).toHaveBeenCalledWith(expect.stringContaining('approved'));
      });
    });

    test('should rollback on API error', async () => {
      const { toast } = require('sonner');

      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ responses: mockPendingResponses }),
        })
        .mockResolvedValueOnce({
          ok: false,
          json: async () => ({ detail: 'Internal server error' }),
        });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const approveButtons = screen.getAllByRole('button', { name: /approve/i });
      fireEvent.click(approveButtons[0]);

      // Card should reappear (rollback)
      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      }, { timeout: 2000 });

      // Error toast should show
      await waitFor(() => {
        expect(toast.error).toHaveBeenCalledWith(expect.stringContaining('failed'));
      });
    });
  });

  describe('Reject Action', () => {
    test('should reject response with optimistic UI update', async () => {
      mockFetch
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ responses: mockPendingResponses }),
        })
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ success: true }),
        });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const rejectButtons = screen.getAllByRole('button', { name: /reject/i });
      fireEvent.click(rejectButtons[0]);

      // Card should disappear immediately
      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(2);
      });

      // API should be called
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/admin/pending/response-1/reject'),
          expect.objectContaining({ method: 'POST' })
        );
      });
    });
  });

  describe('Edit Action', () => {
    test('should open edit modal when Edit button clicked', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      fireEvent.click(editButtons[0]);

      // Edit modal should appear
      await waitFor(() => {
        expect(screen.getByRole('dialog', { name: /edit answer/i })).toBeInTheDocument();
      });
    });

    test('should pass response data to edit modal', async () => {
      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });

      const editButtons = screen.getAllByRole('button', { name: /edit/i });
      fireEvent.click(editButtons[0]);

      await waitFor(() => {
        const modal = screen.getByRole('dialog', { name: /edit answer/i });
        expect(modal).toBeInTheDocument();

        // Question should be displayed
        expect(screen.getByText(/restore my wallet/i)).toBeInTheDocument();
      });
    });
  });

  describe('Loading State', () => {
    test('should show loading indicator while fetching', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves

      render(<PendingReviewQueuePage />);

      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });

    test('should hide loading indicator after data loads', async () => {
      render(<PendingReviewQueuePage />);

      expect(screen.getByText(/loading/i)).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.queryByText(/loading/i)).not.toBeInTheDocument();
      });
    });
  });

  describe('Error State', () => {
    test('should display error message on fetch failure', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByText(/failed to load/i)).toBeInTheDocument();
      });
    });

    test('should show retry button on error', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });
    });

    test('should retry fetch when retry button clicked', async () => {
      mockFetch
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          ok: true,
          json: async () => ({ responses: mockPendingResponses }),
        });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /retry/i }));

      await waitFor(() => {
        expect(screen.getAllByTestId('pending-response-card')).toHaveLength(3);
      });
    });
  });

  describe('Empty State', () => {
    test('should show empty state when no responses', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ responses: [] }),
      });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByText(/no pending responses/i)).toBeInTheDocument();
      });
    });

    test('should show queue counter as 0', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({ responses: [] }),
      });

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(screen.getByText(/queue: 0/i)).toBeInTheDocument();
      });
    });
  });

  describe('Polling', () => {
    test('should poll for new responses every 30 seconds', async () => {
      jest.useFakeTimers();

      render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(1);
      });

      // Fast-forward 30 seconds
      jest.advanceTimersByTime(30000);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(2);
      });

      jest.useRealTimers();
    });

    test('should stop polling when component unmounts', async () => {
      jest.useFakeTimers();

      const { unmount } = render(<PendingReviewQueuePage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledTimes(1);
      });

      unmount();

      jest.advanceTimersByTime(30000);

      // Should not poll after unmount
      expect(mockFetch).toHaveBeenCalledTimes(1);

      jest.useRealTimers();
    });
  });
});
