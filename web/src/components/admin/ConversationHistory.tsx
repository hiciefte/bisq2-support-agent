import { MessageCircle } from 'lucide-react';
import { Label } from "@/components/ui/label";
import { ConversationMessage } from '@/types/feedback';

interface ConversationHistoryProps {
  messages: ConversationMessage[];
  excludeLastMessage?: boolean;
}

export function ConversationHistory({ messages, excludeLastMessage = true }: ConversationHistoryProps) {
  const displayMessages = excludeLastMessage ? messages.slice(0, -1) : messages;

  if (displayMessages.length === 0) return null;

  return (
    <div>
      <Label>Conversation History ({displayMessages.length} messages)</Label>
      <div className="mt-2 space-y-3 max-h-64 overflow-y-auto p-3 bg-accent rounded">
        {displayMessages.map((message, idx) => (
          <div key={idx} className={`p-3 rounded ${message.role === 'user' ? 'bg-blue-50 border-l-4 border-blue-400' : 'bg-green-50 border-l-4 border-green-400'}`}>
            <div className="flex items-center gap-2 mb-1">
              <MessageCircle className="h-4 w-4 text-gray-700" />
              <span className="font-semibold text-sm text-gray-900">
                {message.role === 'user' ? 'User' : 'Assistant'}
              </span>
            </div>
            <p className="text-sm text-gray-800 whitespace-pre-wrap">{message.content}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
