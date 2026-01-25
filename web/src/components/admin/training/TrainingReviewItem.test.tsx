/**
 * Unit tests for TrainingReviewItem component
 *
 * TDD Implementation: Tests written BEFORE fixing the staff name display bug
 *
 * Bug: Staff name not displayed in FAQ Answer label
 * Expected: "FAQ Answer (Staff Source: strayorigin)"
 * Actual: "FAQ Answer (Staff Source)"
 */

import { render, screen } from '@testing-library/react';
import { TrainingReviewItem } from './TrainingReviewItem';

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  XCircle: () => <span data-testid="icon-x-circle" />,
  SkipForward: () => <span data-testid="icon-skip-forward" />,
  Loader2: () => <span data-testid="icon-loader" />,
  MessageSquare: () => <span data-testid="icon-message-square" />,
  Bot: () => <span data-testid="icon-bot" />,
  User: () => <span data-testid="icon-user" />,
  AlertTriangle: () => <span data-testid="icon-alert-triangle" />,
  ChevronDown: () => <span data-testid="icon-chevron-down" />,
  ChevronUp: () => <span data-testid="icon-chevron-up" />,
  MessagesSquare: () => <span data-testid="icon-messages-square" />,
  PlusCircle: () => <span data-testid="icon-plus-circle" />,
  Pencil: () => <span data-testid="icon-pencil" />,
  Check: () => <span data-testid="icon-check" />,
  X: () => <span data-testid="icon-x" />,
  ThumbsUp: () => <span data-testid="icon-thumbs-up" />,
  ThumbsDown: () => <span data-testid="icon-thumbs-down" />,
  CheckCircle2: () => <span data-testid="icon-check-circle" />,
}));

// Mock the EditableAnswer component to capture the label prop
jest.mock('./EditableAnswer', () => ({
  EditableAnswer: ({ label }: { label: string }) => (
    <div data-testid="editable-answer-label">{label}</div>
  ),
}));

// Mock the other components to simplify testing
jest.mock('./ScoreBreakdown', () => ({
  ScoreBreakdown: () => <div data-testid="score-breakdown" />,
}));

jest.mock('./ProtocolSelector', () => ({
  ProtocolSelector: () => <div data-testid="protocol-selector" />,
}));

jest.mock('./CategorySelector', () => ({
  CategorySelector: () => <div data-testid="category-selector" />,
}));

// Mock UI components
jest.mock('@/components/ui/card', () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardFooter: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, ...props }: { children: React.ReactNode }) => <button {...props}>{children}</button>,
}));

jest.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

jest.mock('@/components/ui/select', () => ({
  Select: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  SelectValue: () => <div />,
}));

jest.mock('@/components/ui/collapsible', () => ({
  Collapsible: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CollapsibleContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CollapsibleTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock('@/lib/utils', () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(' '),
}));

// Mock chat components used in TrainingReviewItem
jest.mock('@/components/chat/components/source-badges', () => ({
  SourceBadges: ({ sources }: { sources: Array<{ title: string }> }) => (
    <div data-testid="source-badges">{sources?.length || 0} sources</div>
  ),
}));

jest.mock('@/components/chat/components/confidence-badge', () => ({
  ConfidenceBadge: ({ confidence }: { confidence: number }) => (
    <div data-testid="confidence-badge">Confidence: {(confidence * 100).toFixed(0)}%</div>
  ),
}));

jest.mock('@/components/chat/components/markdown-content', () => ({
  MarkdownContent: ({ content }: { content: string }) => (
    <div data-testid="markdown-content">{content}</div>
  ),
}));

const createMockCandidate = (overrides = {}) => ({
  id: 1,
  source: 'bisq2',
  source_event_id: 'test-event-1',
  source_timestamp: '2024-01-15T10:00:00Z',
  question_text: 'How do I start a trade?',
  staff_answer: 'You can start a trade by clicking the "New Offer" button.',
  generated_answer: 'To start a trade, navigate to the trading section.',
  staff_sender: null,
  embedding_similarity: 0.85,
  factual_alignment: 0.9,
  contradiction_score: 0.1,
  completeness: 0.8,
  hallucination_risk: 0.1,
  final_score: 0.85,
  generation_confidence: 0.82,  // RAG's self-assessed confidence
  llm_reasoning: 'Good answer quality.',
  routing: 'FULL_REVIEW',
  review_status: 'pending',
  reviewed_by: null,
  reviewed_at: null,
  rejection_reason: null,
  faq_id: null,
  is_calibration_sample: false,
  created_at: '2024-01-15T10:00:00Z',
  updated_at: null,
  conversation_context: null,
  has_correction: false,
  is_multi_turn: false,
  message_count: 1,
  needs_distillation: false,
  protocol: null,
  edited_staff_answer: null,
  category: null,
  original_staff_answer: null,
  generated_answer_sources: null,
  ...overrides,
});

const mockHandlers = {
  onApprove: jest.fn().mockResolvedValue(undefined),
  onReject: jest.fn().mockResolvedValue(undefined),
  onSkip: jest.fn().mockResolvedValue(undefined),
  onUpdateCandidate: jest.fn().mockResolvedValue(undefined),
  onRegenerateAnswer: jest.fn().mockResolvedValue(undefined),
  onRateGeneratedAnswer: jest.fn().mockResolvedValue(undefined),
};

describe('TrainingReviewItem', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Staff Name Display', () => {
    test('should display staff name in header badge when staff_sender is provided', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: 'strayorigin',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Staff sender shown as badge in header (Speed Through Subtraction - no duplication)
      expect(screen.getByText('strayorigin')).toBeInTheDocument();

      // FAQ Answer label is now simplified (staff sender moved to header)
      const label = screen.getByTestId('editable-answer-label');
      expect(label.textContent).toBe('FAQ Answer');
    });

    test('should display simple FAQ Answer label when staff_sender is null', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: null,
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      const label = screen.getByTestId('editable-answer-label');

      // Simple label without staff info
      expect(label.textContent).toBe('FAQ Answer');
    });

    test('should display simple FAQ Answer label when staff_sender is empty string', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: '',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      const label = screen.getByTestId('editable-answer-label');

      // Empty string treated same as null
      expect(label.textContent).toBe('FAQ Answer');
    });

    test('should handle special characters in staff_sender badge', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: 'user@bisq.network',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Staff sender with special chars shown in header badge
      expect(screen.getByText('user@bisq.network')).toBeInTheDocument();
    });
  });

  describe('Source Info Display in Header (Being Clear principle)', () => {
    test('should show source and staff sender separately in header', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: 'strayorigin',
        source: 'bisq2',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Source shown (may appear in multiple places: badge when no protocol, and subtitle)
      const sourceElements = screen.getAllByText('Bisq 2 Support Chat');
      expect(sourceElements.length).toBeGreaterThanOrEqual(1);
      // Staff sender as prominent badge
      expect(screen.getByText('strayorigin')).toBeInTheDocument();
    });

    test('should show source without staff name when staff_sender is not available', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: null,
        source: 'bisq2',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Source should appear in header subtitle
      const sourceElements = screen.getAllByText(/Bisq 2 Support Chat/);
      expect(sourceElements.length).toBeGreaterThanOrEqual(1);
    });

    test('should show Matrix source and staff sender correctly', () => {
      const mockCandidate = createMockCandidate({
        staff_sender: 'moderator',
        source: 'matrix',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Matrix source shown (may appear in multiple places)
      const matrixElements = screen.getAllByText('Matrix');
      expect(matrixElements.length).toBeGreaterThanOrEqual(1);
      // Staff sender shown as badge
      expect(screen.getByText('moderator')).toBeInTheDocument();
    });
  });

  describe('Badge Display', () => {
    test('should NOT render Calibration badge even when is_calibration_sample is true', () => {
      const mockCandidate = createMockCandidate({
        is_calibration_sample: true,
        routing: 'FULL_REVIEW',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      expect(screen.queryByText('Calibration')).not.toBeInTheDocument();
      // New routing labels: FULL_REVIEW → "KNOWLEDGE GAP"
      expect(screen.getByText('KNOWLEDGE GAP')).toBeInTheDocument();
    });

    test('should display "Bisq 2 Support Chat" for bisq2 source without protocol', () => {
      const mockCandidate = createMockCandidate({
        source: 'bisq2',
        protocol: null,
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Source shown in both badge (no protocol) and subtitle
      const sourceElements = screen.getAllByText('Bisq 2 Support Chat');
      expect(sourceElements.length).toBeGreaterThanOrEqual(1);
    });

    test('should display "Matrix" for matrix source', () => {
      const mockCandidate = createMockCandidate({
        source: 'matrix',
        protocol: null,
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Matrix shown in badge (no protocol) and subtitle
      const matrixElements = screen.getAllByText('Matrix');
      expect(matrixElements.length).toBeGreaterThanOrEqual(1);
    });

    test('should show protocol badge when protocol is set (source still shown in subtitle)', () => {
      const mockCandidate = createMockCandidate({
        source: 'bisq2',
        protocol: 'bisq_easy',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Protocol badge should be shown
      expect(screen.getByText('Bisq Easy')).toBeInTheDocument();
      // Source is still shown in the subtitle for context (not as a badge)
      expect(screen.getByText('Bisq 2 Support Chat')).toBeInTheDocument();
    });
  });

  // P6: Protocol-based Score/Analysis visibility
  // Simpler, more reliable approach: if no protocol is set, hide score breakdown and LLM analysis
  describe('Protocol-Based Score Visibility', () => {
    test('should hide ScoreBreakdown when protocol is null (not detected)', () => {
      const mockCandidate = createMockCandidate({
        protocol: null,
        generated_answer: 'Which Bisq version are you asking about?',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // ScoreBreakdown should NOT be rendered when protocol is not set
      expect(screen.queryByTestId('score-breakdown')).not.toBeInTheDocument();
    });

    test('should show ScoreBreakdown when protocol is set', () => {
      const mockCandidate = createMockCandidate({
        protocol: 'bisq_easy',
        generated_answer: 'To start a trade in Bisq Easy, click New Offer.',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // ScoreBreakdown should be rendered when protocol is set
      expect(screen.getByTestId('score-breakdown')).toBeInTheDocument();
    });

    test('should show "Protocol Required" badge when protocol is null', () => {
      const mockCandidate = createMockCandidate({
        protocol: null,
        generated_answer: 'Which version are you using?',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Should show the "Protocol Required" badge
      expect(screen.getByText(/Protocol Required/i)).toBeInTheDocument();
    });

    test('should NOT show "Protocol Required" badge when protocol is set', () => {
      const mockCandidate = createMockCandidate({
        protocol: 'bisq1',
        generated_answer: 'In Bisq 1, you can verify by checking the signature.',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Should NOT show the badge when protocol is set
      expect(screen.queryByText(/Protocol Required/i)).not.toBeInTheDocument();
    });

    test('should hide LLM Analysis when protocol is null', () => {
      const mockCandidate = createMockCandidate({
        protocol: null,
        llm_reasoning: 'This is analysis that should be hidden',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // LLM Analysis section should not be rendered
      expect(screen.queryByText('LLM Analysis')).not.toBeInTheDocument();
    });

    test('should show LLM Analysis when protocol is set and has reasoning', () => {
      const mockCandidate = createMockCandidate({
        protocol: 'musig',
        llm_reasoning: 'This is valid analysis',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // LLM Analysis should be visible when protocol is set
      expect(screen.getByText('LLM Analysis')).toBeInTheDocument();
    });
  });

  describe('ARIA Accessibility for Interactive Elements (Cycle 15)', () => {
    test('approve button has accessible aria-label', () => {
      const mockCandidate = createMockCandidate({
        question_text: 'How do I verify my account?',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Approve button should have aria-label that describes its action
      const approveButton = screen.getByRole('button', { name: /approve/i });
      expect(approveButton).toBeInTheDocument();
    });

    test('skip button has accessible aria-label', () => {
      const mockCandidate = createMockCandidate({});

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Skip button should be accessible
      const skipButton = screen.getByRole('button', { name: /skip/i });
      expect(skipButton).toBeInTheDocument();
    });

    test('reject button has accessible aria-label', () => {
      const mockCandidate = createMockCandidate({});

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Reject button should be accessible with descriptive label
      const rejectButton = screen.getByRole('button', { name: /reject/i });
      expect(rejectButton).toBeInTheDocument();
      expect(rejectButton).toHaveAttribute('aria-label');
    });

    test('thumbs up/down rating buttons have accessible labels', () => {
      // Protocol is required for rating buttons to be visible (Cycle 20 fix)
      const mockCandidate = createMockCandidate({ protocol: 'bisq_easy' });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating buttons should have aria-labels (match by text since aria-label is different)
      expect(screen.getByText('Good Answer')).toBeInTheDocument();
      expect(screen.getByText('Needs Work')).toBeInTheDocument();

      // Verify the buttons have aria-label attributes
      const goodButton = screen.getByText('Good Answer').closest('button');
      const needsWorkButton = screen.getByText('Needs Work').closest('button');
      expect(goodButton).toHaveAttribute('aria-label');
      expect(needsWorkButton).toHaveAttribute('aria-label');
    });

    test('create FAQ button has accessible aria-label', () => {
      const mockCandidate = createMockCandidate({});

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Create FAQ (approve) button should have aria-label
      const createFaqButton = screen.getByRole('button', { name: /create faq|approve/i });
      expect(createFaqButton).toBeInTheDocument();
      expect(createFaqButton).toHaveAttribute('aria-label');
    });
  });

  // Cycle 20: Rating Section Visibility When No Protocol
  describe('Rating Section Protocol Visibility (Cycle 20)', () => {
    test('should hide rating section when protocol is null', () => {
      const mockCandidate = createMockCandidate({
        protocol: null,
        generated_answer: 'Are you using Bisq 1 or Bisq Easy?',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating section text should NOT be visible when protocol is null
      expect(screen.queryByText(/Would this answer be good enough to auto-send/)).not.toBeInTheDocument();
    });

    test('should show rating section when protocol is set', () => {
      const mockCandidate = createMockCandidate({
        protocol: 'bisq_easy',
        generated_answer: 'In Bisq Easy, click the New Offer button to start.',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating section should be visible when protocol is set
      expect(screen.getByText(/Would this answer be good enough to auto-send/)).toBeInTheDocument();
    });

    test('should hide rating buttons when protocol is null even with generated answer', () => {
      const mockCandidate = createMockCandidate({
        protocol: null,
        generated_answer: 'Which Bisq version are you using?',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating buttons should NOT be visible
      expect(screen.queryByRole('button', { name: /good answer/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /needs work/i })).not.toBeInTheDocument();
    });
  });

  // Cycle 21: Rating Reset After Regeneration
  describe('Rating Reset After Regeneration (Cycle 21)', () => {
    test('should reset rating when generated_answer changes (after regeneration)', () => {
      const initialCandidate = createMockCandidate({
        id: 1,
        protocol: 'bisq_easy',
        generated_answer: 'Initial answer about Bisq Easy.',
      });

      const { rerender } = render(
        <TrainingReviewItem
          pair={initialCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating buttons should be visible initially (search by visible text)
      expect(screen.getByText('Good Answer')).toBeInTheDocument();

      // Simulate regeneration (same id, different answer)
      const regeneratedCandidate = createMockCandidate({
        id: 1,
        protocol: 'multisig_v1',
        generated_answer: 'Regenerated answer for Bisq 1 Multisig.',
      });

      rerender(
        <TrainingReviewItem
          pair={regeneratedCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating buttons should still be visible (reset state, not showing "Rated: X")
      expect(screen.getByText('Good Answer')).toBeInTheDocument();
      expect(screen.getByText('Needs Work')).toBeInTheDocument();
    });

    test('should maintain rating when only protocol changes without regeneration', () => {
      const candidate = createMockCandidate({
        id: 1,
        protocol: 'bisq_easy',
        generated_answer: 'Same answer content.',
      });

      const { rerender } = render(
        <TrainingReviewItem
          pair={candidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Initial state - buttons visible (search by visible text)
      expect(screen.getByText('Good Answer')).toBeInTheDocument();

      // Rerender with same answer but different protocol (no regeneration happened)
      const sameAnswerCandidate = createMockCandidate({
        id: 1,
        protocol: 'multisig_v1',
        generated_answer: 'Same answer content.', // Same answer
      });

      rerender(
        <TrainingReviewItem
          pair={sameAnswerCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Rating state should be preserved since answer didn't change
      expect(screen.getByText('Good Answer')).toBeInTheDocument();
    });
  });

  // Calibration Queue Behavior (Phase: Queue Semantic Redesign)
  describe('Calibration Queue Behavior', () => {
    test('should show "Next" button instead of "Skip" for AUTO_APPROVE (calibration) items', () => {
      const mockCandidate = createMockCandidate({
        routing: 'AUTO_APPROVE',
        protocol: 'bisq_easy',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Calibration items should show "Next" as primary action
      expect(screen.getByRole('button', { name: /next/i })).toBeInTheDocument();
      // Should NOT show "Skip" button
      expect(screen.queryByRole('button', { name: /skip/i })).not.toBeInTheDocument();
    });

    test('should show "Create FAQ" as secondary action for calibration items', () => {
      const mockCandidate = createMockCandidate({
        routing: 'AUTO_APPROVE',
        protocol: 'bisq_easy',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Should have "Create FAQ" option (for exceptional cases where admin wants to add)
      expect(screen.getByRole('button', { name: /create faq/i })).toBeInTheDocument();
      // Should NOT show standard "Reject" button
      expect(screen.queryByRole('button', { name: /reject/i })).not.toBeInTheDocument();
    });

    test('should show CALIBRATION label for AUTO_APPROVE routing', () => {
      const mockCandidate = createMockCandidate({
        routing: 'AUTO_APPROVE',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      expect(screen.getByText('CALIBRATION')).toBeInTheDocument();
    });

    test('should show prominent rating section for calibration items', () => {
      const mockCandidate = createMockCandidate({
        routing: 'AUTO_APPROVE',
        protocol: 'bisq_easy',
        generated_answer: 'Test answer for calibration.',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Calibration items should show calibration-specific rating prompt
      expect(screen.getByText(/Rate this answer for auto-send calibration/)).toBeInTheDocument();
    });

    test('should show standard actions (Skip/Reject/Approve) for FULL_REVIEW items', () => {
      const mockCandidate = createMockCandidate({
        routing: 'FULL_REVIEW',
        protocol: 'bisq_easy',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Standard actions for knowledge gap queue
      expect(screen.getByRole('button', { name: /skip/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /reject/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /create faq|approve/i })).toBeInTheDocument();
    });

    test('should show MINOR GAP label for SPOT_CHECK routing', () => {
      const mockCandidate = createMockCandidate({
        routing: 'SPOT_CHECK',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      expect(screen.getByText('MINOR GAP')).toBeInTheDocument();
    });
  });

  // Cycle 23-24: Label Rename - "Suggested Answer" (user-friendly, non-technical)
  describe('Suggested Answer Label (Cycle 23-24)', () => {
    test('should display "Suggested Answer" instead of technical labels', () => {
      const mockCandidate = createMockCandidate({
        protocol: 'bisq_easy',
        generated_answer: 'This is a test answer.',
      });

      render(
        <TrainingReviewItem
          pair={mockCandidate}
          isLoading={false}
          {...mockHandlers}
        />
      );

      // Should show user-friendly label
      expect(screen.getByText('Suggested Answer')).toBeInTheDocument();
      // Should NOT show technical labels
      expect(screen.queryByText('RAG Generated Answer')).not.toBeInTheDocument();
      expect(screen.queryByText('AI Generated Answer')).not.toBeInTheDocument();
    });
  });
});
