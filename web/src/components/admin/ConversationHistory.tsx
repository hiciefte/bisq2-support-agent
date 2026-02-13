import { User, Bot } from "lucide-react";
import { Label } from "@/components/ui/label";
import { ConversationMessage } from '@/types/feedback';
import { MarkdownContent } from "@/components/chat/components/markdown-content";
import { cn } from "@/lib/utils";

interface ConversationHistoryProps {
  messages: ConversationMessage[];
  excludeLastMessage?: boolean;
}

export function ConversationHistory({ messages, excludeLastMessage = true }: ConversationHistoryProps) {
  const displayMessages = excludeLastMessage ? messages.slice(0, -1) : messages;

  if (displayMessages.length === 0) return null;

  return (
    <div className="space-y-2">
      <Label className="text-xs text-muted-foreground uppercase tracking-wider">
        Conversation History ({displayMessages.length} messages)
      </Label>
      <div className="space-y-3 max-h-72 overflow-y-auto p-3 bg-accent/40 rounded-lg border border-border/60">
        {displayMessages.map((message, idx) => (
          <div
            key={idx}
            className={cn(
              "p-3 rounded-lg border",
              message.role === "user"
                ? "bg-blue-500/8 border-blue-500/25"
                : "bg-emerald-500/8 border-emerald-500/25",
            )}
          >
            <div className="flex items-center gap-2 mb-1">
              {message.role === "user" ? (
                <User className="h-3.5 w-3.5 text-blue-300" />
              ) : (
                <Bot className="h-3.5 w-3.5 text-emerald-300" />
              )}
              <span
                className={cn(
                  "font-semibold text-xs",
                  message.role === "user" ? "text-blue-200" : "text-emerald-200",
                )}
              >
                {message.role === "user" ? "User" : "Assistant"}
              </span>
            </div>
            <MarkdownContent content={message.content} className="text-sm text-foreground" />
          </div>
        ))}
      </div>
    </div>
  );
}
