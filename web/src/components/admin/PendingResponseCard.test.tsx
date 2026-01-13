/**
 * Unit tests for PendingResponseCard component
 *
 * TDD Implementation: Tests written BEFORE component implementation
 * Following design principles:
 * - Speed Through Subtraction (minimal UI)
 * - Spatial Consistency (fixed button positions)
 * - Progressive Disclosure (sources expand on demand)
 * - Feedback Immediacy (optimistic UI updates)
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { PendingResponseCard } from './PendingResponseCard';
import type { PendingResponse } from '@/types/pending-response';

// Mock data matching E2E test expectations
const mockResponse: PendingResponse = {
  id: 'test-response-1',
  question: 'How do I restore my wallet in Bisq 2?',
  answer: 'To restore your wallet in Bisq 2, go to Settings > Backup/Restore...',
  confidence: 0.75,
  detected_version: 'Bisq 2',
  sources: [
    { title: 'Bisq 2 Wallet Guide', url: 'https://bisq.wiki/Bisq_2_Wallet' },
    { title: 'Backup Best Practices', url: 'https://bisq.wiki/Backup' },
  ],
  created_at: new Date(Date.now() - 2 * 60 * 1000).toISOString(), // 2 minutes ago
};

const mockHandlers = {
  onApprove: jest.fn(),
  onEdit: jest.fn(),
  onReject: jest.fn(),
};

describe('PendingResponseCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering and Data Display', () => {
    test('should render card with data-testid attribute', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const card = screen.getByTestId('pending-response-card');
      expect(card).toBeInTheDocument();
    });

    test('should display question text', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      expect(screen.getByTestId('question-text')).toHaveTextContent(
        'How do I restore my wallet in Bisq 2?'
      );
    });

    test('should display answer text', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      expect(screen.getByTestId('answer-text')).toHaveTextContent(
        'To restore your wallet in Bisq 2, go to Settings > Backup/Restore...'
      );
    });

    test('should display time ago in human-readable format', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      expect(screen.getByTestId('time-ago')).toHaveTextContent('2 min ago');
    });
  });

  describe('Confidence Badge', () => {
    test('should display confidence badge with percentage', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const badge = screen.getByTestId('confidence-badge');
      expect(badge).toHaveTextContent('75% Medium');
    });

    test('should use green color for high confidence (≥80%)', () => {
      const highConfidenceResponse = { ...mockResponse, confidence: 0.85 };
      render(<PendingResponseCard response={highConfidenceResponse} {...mockHandlers} />);

      const badge = screen.getByTestId('confidence-badge');
      expect(badge).toHaveClass('bg-green-500');
    });

    test('should use yellow color for medium confidence (50-79%)', () => {
      const mediumConfidenceResponse = { ...mockResponse, confidence: 0.65 };
      render(<PendingResponseCard response={mediumConfidenceResponse} {...mockHandlers} />);

      const badge = screen.getByTestId('confidence-badge');
      expect(badge).toHaveClass('bg-yellow-500');
    });

    test('should use red color for low confidence (<50%)', () => {
      const lowConfidenceResponse = { ...mockResponse, confidence: 0.35 };
      render(<PendingResponseCard response={lowConfidenceResponse} {...mockHandlers} />);

      const badge = screen.getByTestId('confidence-badge');
      expect(badge).toHaveClass('bg-red-500');
    });

    test('should display confidence level text (High/Medium/Low)', () => {
      const testCases = [
        { confidence: 0.85, expected: '85% High' },
        { confidence: 0.65, expected: '65% Medium' },
        { confidence: 0.35, expected: '35% Low' },
      ];

      testCases.forEach(({ confidence, expected }) => {
        const { rerender } = render(
          <PendingResponseCard response={{ ...mockResponse, confidence }} {...mockHandlers} />
        );
        expect(screen.getByTestId('confidence-badge')).toHaveTextContent(expected);
        rerender(<div />); // Clear between tests
      });
    });
  });

  describe('Version Badge', () => {
    test('should display version badge for Bisq 2', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const badge = screen.getByTestId('version-badge');
      expect(badge).toHaveTextContent('Bisq 2');
    });

    test('should display version badge for Bisq 1', () => {
      const bisq1Response = { ...mockResponse, detected_version: 'Bisq 1' };
      render(<PendingResponseCard response={bisq1Response} {...mockHandlers} />);

      expect(screen.getByTestId('version-badge')).toHaveTextContent('Bisq 1');
    });

    test('should display version badge for General', () => {
      const generalResponse = { ...mockResponse, detected_version: 'General' };
      render(<PendingResponseCard response={generalResponse} {...mockHandlers} />);

      expect(screen.getByTestId('version-badge')).toHaveTextContent('General');
    });
  });

  describe('Action Buttons', () => {
    test('should render Approve button with correct text', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const approveButton = screen.getByRole('button', { name: /approve/i });
      expect(approveButton).toBeInTheDocument();
    });

    test('should render Edit button with correct text', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const editButton = screen.getByRole('button', { name: /edit/i });
      expect(editButton).toBeInTheDocument();
    });

    test('should render Reject button with correct text', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const rejectButton = screen.getByRole('button', { name: /reject/i });
      expect(rejectButton).toBeInTheDocument();
    });

    test('should call onApprove handler when Approve button clicked', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const approveButton = screen.getByRole('button', { name: /approve/i });
      fireEvent.click(approveButton);

      expect(mockHandlers.onApprove).toHaveBeenCalledTimes(1);
    });

    test('should call onEdit handler when Edit button clicked', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const editButton = screen.getByRole('button', { name: /edit/i });
      fireEvent.click(editButton);

      expect(mockHandlers.onEdit).toHaveBeenCalledTimes(1);
    });

    test('should call onReject handler when Reject button clicked', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const rejectButton = screen.getByRole('button', { name: /reject/i });
      fireEvent.click(rejectButton);

      expect(mockHandlers.onReject).toHaveBeenCalledTimes(1);
    });

    test('should have ARIA labels for accessibility', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const approveButton = screen.getByRole('button', { name: /approve/i });
      expect(approveButton).toHaveAttribute('aria-label');

      const editButton = screen.getByRole('button', { name: /edit/i });
      expect(editButton).toHaveAttribute('aria-label');

      const rejectButton = screen.getByRole('button', { name: /reject/i });
      expect(rejectButton).toHaveAttribute('aria-label');
    });
  });

  describe('Progressive Disclosure - Sources', () => {
    test('should initially hide sources', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      // Sources should not be visible initially
      expect(screen.queryByText('Bisq 2 Wallet Guide')).not.toBeInTheDocument();
      expect(screen.queryByText('Backup Best Practices')).not.toBeInTheDocument();
    });

    test('should display "View X sources" button', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const sourcesButton = screen.getByRole('button', { name: /view 2 sources/i });
      expect(sourcesButton).toBeInTheDocument();
    });

    test('should expand sources when button clicked', async () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const sourcesButton = screen.getByRole('button', { name: /view 2 sources/i });
      fireEvent.click(sourcesButton);

      // Sources should become visible
      await waitFor(() => {
        expect(screen.getByText('Bisq 2 Wallet Guide')).toBeInTheDocument();
        expect(screen.getByText('Backup Best Practices')).toBeInTheDocument();
      });
    });

    test('should rotate chevron icon when sources expanded', () => {
      const { container } = render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const sourcesButton = screen.getByRole('button', { name: /view 2 sources/i });
      const chevron = container.querySelector('svg');

      // Initially no rotation
      expect(chevron).not.toHaveClass('rotate-180');

      fireEvent.click(sourcesButton);

      // After click, chevron should rotate
      expect(chevron).toHaveClass('rotate-180');
    });

    test('should collapse sources when button clicked again', async () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const sourcesButton = screen.getByRole('button', { name: /view 2 sources/i });

      // Expand
      fireEvent.click(sourcesButton);
      await waitFor(() => {
        expect(screen.getByText('Bisq 2 Wallet Guide')).toBeInTheDocument();
      });

      // Collapse
      fireEvent.click(sourcesButton);
      await waitFor(() => {
        expect(screen.queryByText('Bisq 2 Wallet Guide')).not.toBeInTheDocument();
      });
    });
  });

  describe('Hover Effects', () => {
    test('should have hover shadow transition class', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} />);

      const card = screen.getByTestId('pending-response-card');
      expect(card).toHaveClass('transition-all', 'duration-200', 'hover:shadow-md');
    });
  });

  describe('Optimistic UI State', () => {
    test('should support isRemoving state for fade-out animation', () => {
      const { rerender } = render(
        <PendingResponseCard response={mockResponse} {...mockHandlers} isRemoving={false} />
      );

      const card = screen.getByTestId('pending-response-card');
      expect(card).not.toHaveClass('opacity-0');

      // Simulate optimistic removal
      rerender(
        <PendingResponseCard response={mockResponse} {...mockHandlers} isRemoving={true} />
      );

      expect(card).toHaveClass('opacity-0');
    });

    test('should disable buttons during removal', () => {
      render(<PendingResponseCard response={mockResponse} {...mockHandlers} isRemoving={true} />);

      const approveButton = screen.getByRole('button', { name: /approve/i });
      const editButton = screen.getByRole('button', { name: /edit/i });
      const rejectButton = screen.getByRole('button', { name: /reject/i });

      expect(approveButton).toBeDisabled();
      expect(editButton).toBeDisabled();
      expect(rejectButton).toBeDisabled();
    });
  });

  describe('Edge Cases', () => {
    test('should handle response with no sources', () => {
      const noSourcesResponse = { ...mockResponse, sources: [] };
      render(<PendingResponseCard response={noSourcesResponse} {...mockHandlers} />);

      // "View 0 sources" button should not be rendered
      expect(screen.queryByRole('button', { name: /view.*sources/i })).not.toBeInTheDocument();
    });

    test('should handle very long question text', () => {
      const longQuestion = 'A'.repeat(500);
      const longQuestionResponse = { ...mockResponse, question: longQuestion };

      render(<PendingResponseCard response={longQuestionResponse} {...mockHandlers} />);

      const questionText = screen.getByTestId('question-text');
      expect(questionText).toHaveTextContent(longQuestion);
    });

    test('should handle very recent timestamp (< 1 minute)', () => {
      const recentResponse = {
        ...mockResponse,
        created_at: new Date(Date.now() - 30 * 1000).toISOString(), // 30 seconds ago
      };

      render(<PendingResponseCard response={recentResponse} {...mockHandlers} />);

      expect(screen.getByTestId('time-ago')).toHaveTextContent('just now');
    });

    test('should handle old timestamp (hours ago)', () => {
      const oldResponse = {
        ...mockResponse,
        created_at: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(), // 2 hours ago
      };

      render(<PendingResponseCard response={oldResponse} {...mockHandlers} />);

      expect(screen.getByTestId('time-ago')).toHaveTextContent('2 hours ago');
    });
  });
});
