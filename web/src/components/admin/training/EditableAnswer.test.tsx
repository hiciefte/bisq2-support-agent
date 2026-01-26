/**
 * Unit tests for EditableAnswer component
 *
 * Tests cover:
 * - Edit mode toggle
 * - Save and cancel functionality
 * - Display of edited vs original answer
 *
 * Note: "View Original Staff Answer" collapsible was removed in Cycle 24
 * Original answer viewing is now consolidated in "Original Conversation"
 * section at the top of TrainingReviewItem (Think in Flows principle)
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { EditableAnswer } from './EditableAnswer';

// Mock lucide-react icons
jest.mock('lucide-react', () => ({
  Pencil: () => <span data-testid="icon-pencil" />,
  Check: () => <span data-testid="icon-check" />,
  X: () => <span data-testid="icon-x" />,
}));

// Mock UI components
jest.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, disabled, ...props }: { children: React.ReactNode; onClick?: () => void; disabled?: boolean }) => (
    <button onClick={onClick} disabled={disabled} {...props}>{children}</button>
  ),
}));

jest.mock('@/components/ui/badge', () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

jest.mock('@/components/ui/textarea', () => ({
  Textarea: (props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) => (
    <textarea {...props} />
  ),
}));

jest.mock('@/lib/utils', () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(' '),
}));

const defaultProps = {
  answer: 'Navigate to the Wallet section and select Backup.',
  editedAnswer: null,
  isEditing: false,
  onEditStart: jest.fn(),
  onEditSave: jest.fn().mockResolvedValue(undefined),
  onEditCancel: jest.fn(),
  label: 'FAQ Answer',
  icon: <span data-testid="test-icon" />,
  isSaving: false,
};

describe('EditableAnswer', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Display Mode', () => {
    test('should display the answer text', () => {
      render(<EditableAnswer {...defaultProps} />);

      expect(screen.getByText(defaultProps.answer)).toBeInTheDocument();
    });

    test('should display the label', () => {
      render(<EditableAnswer {...defaultProps} />);

      expect(screen.getByText('FAQ Answer')).toBeInTheDocument();
    });

    test('should show Edit button when not editing', () => {
      render(<EditableAnswer {...defaultProps} />);

      expect(screen.getByText('Edit')).toBeInTheDocument();
    });

    test('should call onEditStart when Edit button is clicked', () => {
      render(<EditableAnswer {...defaultProps} />);

      fireEvent.click(screen.getByText('Edit'));

      expect(defaultProps.onEditStart).toHaveBeenCalled();
    });

    test('should display edited answer when available', () => {
      const editedAnswer = 'This is the edited answer.';
      render(<EditableAnswer {...defaultProps} editedAnswer={editedAnswer} />);

      expect(screen.getByText(editedAnswer)).toBeInTheDocument();
      expect(screen.queryByText(defaultProps.answer)).not.toBeInTheDocument();
    });

    test('should show Edited badge when answer has been modified', () => {
      render(
        <EditableAnswer
          {...defaultProps}
          editedAnswer="Modified answer"
        />
      );

      expect(screen.getByText('Edited')).toBeInTheDocument();
    });
  });

  describe('Edit Mode', () => {
    test('should show textarea when in edit mode', () => {
      render(<EditableAnswer {...defaultProps} isEditing={true} />);

      expect(screen.getByRole('textbox')).toBeInTheDocument();
    });

    test('should show Save and Cancel buttons in edit mode', () => {
      render(<EditableAnswer {...defaultProps} isEditing={true} />);

      expect(screen.getByText('Save Changes')).toBeInTheDocument();
      expect(screen.getByText('Cancel')).toBeInTheDocument();
    });

    test('should call onEditCancel when Cancel is clicked', () => {
      render(<EditableAnswer {...defaultProps} isEditing={true} />);

      fireEvent.click(screen.getByText('Cancel'));

      expect(defaultProps.onEditCancel).toHaveBeenCalled();
    });

    test('should not show Edit button in edit mode', () => {
      render(<EditableAnswer {...defaultProps} isEditing={true} />);

      expect(screen.queryByRole('button', { name: /^Edit$/ })).not.toBeInTheDocument();
    });
  });
});
