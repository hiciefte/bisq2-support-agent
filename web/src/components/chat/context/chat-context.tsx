'use client';

/**
 * ChatContext provides access to chat actions from anywhere in the component tree.
 * Used to allow deep components (like ReputationBadge tooltips) to trigger new questions.
 */

import { createContext, useContext, ReactNode, useCallback, useMemo } from 'react';

interface ChatContextValue {
  /** Send a question to the chat (triggers API call) */
  sendQuestion: (question: string) => void;
  /** Set the input field value (without sending) */
  setInputValue: (value: string) => void;
}

const ChatContext = createContext<ChatContextValue | null>(null);

interface ChatProviderProps {
  children: ReactNode;
  /** Callback to send a question */
  onSendQuestion: (question: string) => void;
  /** Callback to set input value */
  onSetInput: (value: string) => void;
}

/**
 * Provider component for chat actions
 */
export function ChatProvider({ children, onSendQuestion, onSetInput }: ChatProviderProps) {
  const sendQuestion = useCallback(
    (question: string) => {
      onSendQuestion(question);
    },
    [onSendQuestion]
  );

  const setInputValue = useCallback(
    (value: string) => {
      onSetInput(value);
    },
    [onSetInput]
  );

  const value = useMemo(
    () => ({ sendQuestion, setInputValue }),
    [sendQuestion, setInputValue]
  );

  return <ChatContext.Provider value={value}>{children}</ChatContext.Provider>;
}

/**
 * Hook to access chat actions from any component
 * @throws Error if used outside ChatProvider
 */
export function useChatActions(): ChatContextValue {
  const context = useContext(ChatContext);
  if (!context) {
    throw new Error('useChatActions must be used within a ChatProvider');
  }
  return context;
}

/**
 * Safe version of useChatActions that returns null if not in provider
 * Useful for components that may be used outside the chat context
 */
export function useChatActionsOptional(): ChatContextValue | null {
  return useContext(ChatContext);
}
