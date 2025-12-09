/**
 * Unit tests for EditAnswerModal component
 *
 * TDD Implementation: Tests written BEFORE component implementation
 * Following design principles:
 * - Speed Through Subtraction (minimal modal, focus on editing)
 * - Feedback Immediacy (keyboard shortcuts Cmd+Enter, Escape)
 * - Spatial Consistency (predictable button layout)
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { EditAnswerModal } from './EditAnswerModal';
import type { PendingResponse } from '@/types/pending-response';

// Mock shadcn/ui components
jest.mock('@/components/ui/dialog', () => ({
  Dialog: ({ children, open }: any) => (open ? <div role="dialog" aria-label="Edit Answer" aria-modal="true">{children}</div> : null),
  DialogContent: ({ children }: any) => <div>{children}</div>,
  DialogHeader: ({ children }: any) => <div>{children}</div>,
  DialogTitle: ({ children }: any) => <h2>{children}</h2>,
  DialogFooter: ({ children }: any) => <div>{children}</div>,
}));

jest.mock('@/components/ui/button', () => ({
  Button: ({ children, onClick, disabled, 'aria-label': ariaLabel }: any) => (
    <button onClick={onClick} disabled={disabled} aria-label={ariaLabel}>
      {children}
    </button>
  ),
}));

jest.mock('@/components/ui/label', () => ({
  Label: ({ children, htmlFor }: any) => <label htmlFor={htmlFor}>{children}</label>,
}));

jest.mock('@/components/ui/textarea', () => {
  const React = require('react');
  return {
    Textarea: React.forwardRef(({ value, onChange, onKeyDown, 'aria-label': ariaLabel, id }: any, ref: any) => (
      <textarea
        ref={ref}
        id={id}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        aria-label={ariaLabel}
      />
    )),
  };
});

const mockResponse: PendingResponse = {
  id: 'test-response-1',
  question: 'How do I restore my wallet in Bisq 2?',
  answer: 'To restore your wallet in Bisq 2, go to Settings > Backup/Restore...',
  confidence: 0.75,
  detected_version: 'Bisq 2',
  sources: [{ title: 'Bisq 2 Wallet Guide', url: 'https://bisq.wiki/Bisq_2_Wallet' }],
  created_at: new Date().toISOString(),
};

const mockHandlers = {
  onSave: jest.fn(),
  onCancel: jest.fn(),
};

describe('EditAnswerModal', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Rendering', () => {
    test('should render modal with "Edit Answer" title', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      expect(screen.getByRole('dialog', { name: /edit answer/i })).toBeInTheDocument();
    });

    test('should display question (read-only)', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      expect(screen.getByText(/restore my wallet/i)).toBeInTheDocument();
    });

    test('should display editable answer in textarea', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      expect(textarea).toHaveValue(mockResponse.answer);
    });

    test('should have Save and Cancel buttons', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      expect(screen.getByRole('button', { name: /^save$/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /cancel/i })).toBeInTheDocument();
    });
  });

  describe('Editing Functionality', () => {
    test('should allow editing answer text', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: 'This is an edited answer' } });

      expect(textarea).toHaveValue('This is an edited answer');
    });

    test('should call onSave with edited answer when Save clicked', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: 'Edited answer text' } });

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      fireEvent.click(saveButton);

      expect(mockHandlers.onSave).toHaveBeenCalledWith('Edited answer text');
    });

    test('should call onCancel when Cancel button clicked', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const cancelButton = screen.getByRole('button', { name: /cancel/i });
      fireEvent.click(cancelButton);

      expect(mockHandlers.onCancel).toHaveBeenCalledTimes(1);
    });

    test('should not save if answer is empty', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: '' } });

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      fireEvent.click(saveButton);

      expect(mockHandlers.onSave).not.toHaveBeenCalled();
    });

    test('should show validation error when answer is empty', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: '' } });

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      fireEvent.click(saveButton);

      expect(screen.getByText(/answer cannot be empty/i)).toBeInTheDocument();
    });

    test('should disable Save button when answer is empty', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: '' } });

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      expect(saveButton).toBeDisabled();
    });
  });

  describe('Keyboard Shortcuts', () => {
    test('should save on Cmd+Enter (Mac)', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: 'Edited answer' } });

      fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true });

      expect(mockHandlers.onSave).toHaveBeenCalledWith('Edited answer');
    });

    test('should save on Ctrl+Enter (Windows/Linux)', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: 'Edited answer' } });

      fireEvent.keyDown(textarea, { key: 'Enter', ctrlKey: true });

      expect(mockHandlers.onSave).toHaveBeenCalledWith('Edited answer');
    });

    test('should cancel on Escape key', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.keyDown(textarea, { key: 'Escape' });

      expect(mockHandlers.onCancel).toHaveBeenCalledTimes(1);
    });

    test('should not save on Cmd+Enter if answer is empty', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: '' } });
      fireEvent.keyDown(textarea, { key: 'Enter', metaKey: true });

      expect(mockHandlers.onSave).not.toHaveBeenCalled();
    });
  });

  describe('Character Count', () => {
    test('should display character count', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const charCount = screen.getByText(/\d+ characters/i);
      expect(charCount).toBeInTheDocument();
    });

    test('should update character count as user types', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: 'Short answer' } });

      expect(screen.getByText('12 characters')).toBeInTheDocument();
    });
  });

  describe('Accessibility', () => {
    test('should have proper ARIA labels', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const dialog = screen.getByRole('dialog', { name: /edit answer/i });
      expect(dialog).toHaveAttribute('aria-modal', 'true');
    });

    test('should focus textarea when modal opens', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      expect(textarea).toHaveFocus();
    });

    test('should have descriptive button labels', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      expect(saveButton).toHaveAttribute('aria-label');
    });
  });

  describe('Edge Cases', () => {
    test('should handle very long answer text', () => {
      const longAnswer = 'A'.repeat(5000);
      const longAnswerResponse = { ...mockResponse, answer: longAnswer };

      render(<EditAnswerModal response={longAnswerResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      expect(textarea).toHaveValue(longAnswer);
      expect(screen.getByText('5000 characters')).toBeInTheDocument();
    });

    test('should trim whitespace before saving', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: '  Trimmed answer  ' } });

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      fireEvent.click(saveButton);

      expect(mockHandlers.onSave).toHaveBeenCalledWith('Trimmed answer');
    });

    test('should treat whitespace-only answer as empty', () => {
      render(<EditAnswerModal response={mockResponse} {...mockHandlers} />);

      const textarea = screen.getByRole('textbox', { name: /your answer/i });
      fireEvent.change(textarea, { target: { value: '   ' } });

      const saveButton = screen.getByRole('button', { name: /^save$/i });
      expect(saveButton).toBeDisabled();
    });
  });
});
