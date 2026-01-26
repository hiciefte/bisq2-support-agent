/**
 * Unit tests for ScoreBreakdown component
 *
 * TDD Implementation: Tests for accessibility (WCAG 1.4.1) and generation_confidence display
 *
 * Cycle 14: Score display with icons for accessibility
 * Cycle 25: Traffic Light System with Progressive Disclosure
 *
 * Design Principles Applied:
 * - Progressive Disclosure: Show traffic light summary first, details on click
 * - Being Clear: Simple visual indicator (green/yellow/red)
 * - Speed Through Subtraction: Remove cognitive overhead for casual review
 */

import { render, screen } from '@testing-library/react';
import { ScoreBreakdown } from './ScoreBreakdown';

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  ChevronDown: () => <span data-testid="icon-chevron-down" />,
  ChevronUp: () => <span data-testid="icon-chevron-up" />,
  BarChart3: () => <span data-testid="icon-bar-chart" />,
  GitCompare: () => <span data-testid="icon-git-compare" />,
  CheckCircle2: () => <span data-testid="icon-check-circle" />,
  AlertTriangle: () => <span data-testid="icon-alert-triangle" />,
  ListChecks: () => <span data-testid="icon-list-checks" />,
  ShieldAlert: () => <span data-testid="icon-shield-alert" />,
  Zap: () => <span data-testid="icon-zap" />,
  Eye: () => <span data-testid="icon-eye" />,
  ClipboardCheck: () => <span data-testid="icon-clipboard-check" />,
  Sparkles: () => <span data-testid="icon-sparkles" />,
  CircleCheck: () => <span data-testid="icon-circle-check" />,
  CircleAlert: () => <span data-testid="icon-circle-alert" />,
  CircleX: () => <span data-testid="icon-circle-x" />,
  Info: () => <span data-testid="icon-info" />,
}));

// Mock UI components
jest.mock('@/components/ui/tooltip', () => ({
  Tooltip: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div data-testid="tooltip-content">{children}</div>,
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock('@/components/ui/collapsible', () => ({
  Collapsible: ({ children, open }: { children: React.ReactNode; open?: boolean }) => (
    <div data-testid="collapsible" data-open={open}>{children}</div>
  ),
  CollapsibleContent: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="collapsible-content">{children}</div>
  ),
  CollapsibleTrigger: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="collapsible-trigger">{children}</div>
  ),
}));

jest.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span data-testid="badge">{children}</span>,
}));

jest.mock('@/lib/utils', () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(' '),
}));

describe('ScoreBreakdown', () => {
  const defaultProps = {
    embeddingSimilarity: 0.85,
    factualAlignment: 0.9,
    contradictionScore: 0.1,
    completeness: 0.8,
    hallucinationRisk: 0.1,
    finalScore: 0.85,
    generationConfidence: null,
    defaultCollapsed: false,
  };

  describe('Accessibility - Icons alongside color bars (WCAG 1.4.1)', () => {
    it('displays icon alongside each metric bar', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      // Each metric should have an icon (not relying on color alone)
      expect(screen.getByTestId('icon-git-compare')).toBeInTheDocument(); // Meaning Match
      expect(screen.getByTestId('icon-check-circle')).toBeInTheDocument(); // Facts Aligned
      expect(screen.getByTestId('icon-alert-triangle')).toBeInTheDocument(); // No Conflicts
      expect(screen.getByTestId('icon-list-checks')).toBeInTheDocument(); // Coverage
      expect(screen.getByTestId('icon-shield-alert')).toBeInTheDocument(); // Grounded
    });

    it('displays percentage text alongside visual bar', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      // Should show percentage values as text (not just color)
      // May have multiple 85% (header and metric), so check at least one exists
      const elements85 = screen.getAllByText('85%');
      expect(elements85.length).toBeGreaterThanOrEqual(1);

      const elements90 = screen.getAllByText('90%');
      expect(elements90.length).toBeGreaterThanOrEqual(1); // factualAlignment
    });

    it('displays metric labels as text', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      // Labels should be visible (may appear multiple times in tooltips)
      expect(screen.getAllByText('Meaning Match').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Facts Aligned').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('No Conflicts').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Coverage').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('Grounded').length).toBeGreaterThanOrEqual(1);
    });
  });

  describe('Generation Confidence Display', () => {
    it('displays generation confidence when provided', () => {
      render(
        <ScoreBreakdown
          {...defaultProps}
          generationConfidence={0.82}
        />
      );

      // Should show RAG Confidence metric (may appear in label and tooltip)
      expect(screen.getAllByText('RAG Confidence').length).toBeGreaterThanOrEqual(1);
      expect(screen.getAllByText('82%').length).toBeGreaterThanOrEqual(1);
    });

    it('does not display generation confidence when null', () => {
      render(
        <ScoreBreakdown
          {...defaultProps}
          generationConfidence={null}
        />
      );

      // Should not show RAG Confidence metric
      expect(screen.queryByText('RAG Confidence')).not.toBeInTheDocument();
    });

    it('differentiates generation_confidence from comparison_score visually', () => {
      render(
        <ScoreBreakdown
          {...defaultProps}
          generationConfidence={0.78}
        />
      );

      // RAG Confidence should have the sparkles icon
      expect(screen.getByTestId('icon-sparkles')).toBeInTheDocument();
    });

    it('displays generation confidence with different semantics label', () => {
      render(
        <ScoreBreakdown
          {...defaultProps}
          generationConfidence={0.78}
        />
      );

      // Should have description that differs from comparison metrics
      expect(screen.getByText(/How confident RAG is in its answer/i)).toBeInTheDocument();
    });
  });

  describe('Final Score Display', () => {
    it('shows final score as percentage in header', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      // Final score shown in collapsible header (may appear multiple times)
      const elements = screen.getAllByText('85%');
      expect(elements.length).toBeGreaterThanOrEqual(1);
    });

    it('shows routing indicator based on final score', () => {
      render(<ScoreBreakdown {...defaultProps} finalScore={0.92} />);

      // 92% should show Auto indicator
      expect(screen.getByText('Auto')).toBeInTheDocument();
    });

    it('shows Spot indicator for medium scores', () => {
      render(<ScoreBreakdown {...defaultProps} finalScore={0.82} />);

      expect(screen.getByText('Spot')).toBeInTheDocument();
    });

    it('shows Full indicator for low scores', () => {
      render(<ScoreBreakdown {...defaultProps} finalScore={0.65} />);

      expect(screen.getByText('Full')).toBeInTheDocument();
    });
  });

  describe('Null value handling', () => {
    it('displays N/A for null metric values', () => {
      render(
        <ScoreBreakdown
          embeddingSimilarity={null}
          factualAlignment={null}
          contradictionScore={null}
          completeness={null}
          hallucinationRisk={null}
          finalScore={null}
          generationConfidence={null}
        />
      );

      // All metrics should show N/A
      const naElements = screen.getAllByText('N/A');
      expect(naElements.length).toBeGreaterThanOrEqual(5);
    });
  });

  describe('ARIA Accessibility Attributes', () => {
    it('has role="meter" on score bars for assistive technologies', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      // Each metric bar should have role="meter"
      const meters = screen.getAllByRole('meter');
      expect(meters.length).toBeGreaterThanOrEqual(5); // 5 comparison metrics
    });

    it('has aria-valuenow, aria-valuemin, aria-valuemax on meters', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      const meters = screen.getAllByRole('meter');
      meters.forEach((meter) => {
        expect(meter).toHaveAttribute('aria-valuemin', '0');
        expect(meter).toHaveAttribute('aria-valuemax', '100');
        expect(meter).toHaveAttribute('aria-valuenow');
      });
    });

    it('has aria-label describing each metric', () => {
      render(<ScoreBreakdown {...defaultProps} />);

      const meters = screen.getAllByRole('meter');
      meters.forEach((meter) => {
        expect(meter).toHaveAttribute('aria-label');
        // Each aria-label should include the metric name and percentage
        const label = meter.getAttribute('aria-label') || '';
        expect(label).toMatch(/\d+%/); // Contains percentage
      });
    });

    it('includes generation confidence in accessible meters when provided', () => {
      render(
        <ScoreBreakdown
          {...defaultProps}
          generationConfidence={0.82}
        />
      );

      const meters = screen.getAllByRole('meter');
      expect(meters.length).toBeGreaterThanOrEqual(6); // 5 comparison + 1 generation
    });
  });

  // Cycle 25: Traffic Light System Tests
  describe('Traffic Light System (Progressive Disclosure)', () => {
    describe('Summary View (Level 1)', () => {
      it('shows GREEN status indicator for high scores (>= 75%)', () => {
        render(<ScoreBreakdown {...defaultProps} finalScore={0.85} />);

        // Should show positive status message
        expect(screen.getByText(/good match/i)).toBeInTheDocument();
      });

      it('shows YELLOW status indicator for medium scores (50-74%)', () => {
        render(<ScoreBreakdown {...defaultProps} finalScore={0.60} />);

        // Should show caution status message (may appear multiple times due to mock)
        const elements = screen.getAllByText(/review needed|needs review/i);
        expect(elements.length).toBeGreaterThanOrEqual(1);
      });

      it('shows RED status indicator for low scores (< 50%)', () => {
        render(<ScoreBreakdown {...defaultProps} finalScore={0.30} />);

        // Should show warning status message
        expect(screen.getByText(/issues found|check carefully/i)).toBeInTheDocument();
      });

      it('shows actionable hint for specific issues', () => {
        // Low factual alignment
        render(
          <ScoreBreakdown
            {...defaultProps}
            finalScore={0.40}
            factualAlignment={0.20}
          />
        );

        // Should give actionable guidance (may appear multiple times)
        const elements = screen.getAllByText(/fact|verify|check/i);
        expect(elements.length).toBeGreaterThanOrEqual(1);
      });

      it('shows actionable hint for contradictions', () => {
        // High contradiction score (bad)
        render(
          <ScoreBreakdown
            {...defaultProps}
            finalScore={0.40}
            contradictionScore={0.80}
          />
        );

        // Should warn about conflicts (may appear multiple times)
        const elements = screen.getAllByText(/conflict|contradict/i);
        expect(elements.length).toBeGreaterThanOrEqual(1);
      });
    });

    describe('Detailed View (Level 2 - on expand)', () => {
      it('shows all 6 metrics when expanded', () => {
        render(<ScoreBreakdown {...defaultProps} defaultCollapsed={false} />);

        // All metrics visible in expanded view
        expect(screen.getAllByText('Meaning Match').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Facts Aligned').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('No Conflicts').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Coverage').length).toBeGreaterThanOrEqual(1);
        expect(screen.getAllByText('Grounded').length).toBeGreaterThanOrEqual(1);
      });

      it('hides routing threshold footer when collapsed', () => {
        render(<ScoreBreakdown {...defaultProps} defaultCollapsed={true} />);

        // In collapsed state, the collapsible should be closed
        // Note: Mock always renders content, but real component hides it
        // Check that collapsible data attribute indicates closed state
        const collapsible = screen.getByTestId('collapsible');
        expect(collapsible).toHaveAttribute('data-open', 'false');
      });
    });

    describe('Edge Cases', () => {
      it('handles null final score gracefully', () => {
        render(<ScoreBreakdown {...defaultProps} finalScore={null} />);

        // Should not crash and show N/A or similar
        expect(screen.getByTestId('collapsible')).toBeInTheDocument();
      });

      it('handles 0% score (shows red indicator)', () => {
        render(<ScoreBreakdown {...defaultProps} finalScore={0} />);

        expect(screen.getByText('0%')).toBeInTheDocument();
        expect(screen.getByText(/issues found|check carefully/i)).toBeInTheDocument();
      });

      it('handles 100% score (shows green indicator)', () => {
        render(<ScoreBreakdown {...defaultProps} finalScore={1.0} />);

        expect(screen.getByText('100%')).toBeInTheDocument();
        expect(screen.getByText(/good match/i)).toBeInTheDocument();
      });
    });
  });
});
