"use client";

import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Cat,
  Globe2,
  Info,
  Loader2,
  MessageCircle,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import {
  type ChannelAutoresponsePolicy,
  type ChannelId,
  type EscalationNotificationChannel,
} from "@/components/admin/overview/types";
import {
  type ChannelAcknowledgmentMode,
  type ChannelEscalationUserNoticeMode,
  type ChannelResponseMode,
} from "@/hooks/useChannelAutoresponsePolicies";
import { cn } from "@/lib/utils";

interface ChannelAutoresponseCardProps {
  policies: ChannelAutoresponsePolicy[];
  isLoading: boolean;
  isSavingByChannel: Record<ChannelId, boolean>;
  error: string | null;
  onModeChange: (channelId: ChannelId, mode: ChannelResponseMode) => void;
  onEscalationRouteChange: (
    channelId: ChannelId,
    escalationNotificationChannel: EscalationNotificationChannel,
  ) => void;
  onAcknowledgmentModeChange: (
    channelId: ChannelId,
    acknowledgmentMode: ChannelAcknowledgmentMode,
  ) => void;
  onAcknowledgmentReactionKeyChange: (
    channelId: ChannelId,
    acknowledgmentReactionKey: string,
  ) => void;
  onAcknowledgmentMessageTemplateChange: (
    channelId: ChannelId,
    acknowledgmentMessageTemplate: string,
  ) => void;
  onEscalationUserNoticeModeChange: (
    channelId: ChannelId,
    escalationUserNoticeMode: ChannelEscalationUserNoticeMode,
  ) => void;
  onRetry: () => void;
}

interface ChannelMeta {
  id: ChannelId;
  label: string;
  description: string;
  icon: LucideIcon;
}

const CHANNELS: ChannelMeta[] = [
  {
    id: "web",
    label: "Web Chat",
    description: "Public website chat endpoint.",
    icon: Globe2,
  },
  {
    id: "bisq2",
    label: "Bisq 2 Support Chat",
    description: "In-app Bisq 2 support conversations.",
    icon: Cat,
  },
  {
    id: "matrix",
    label: "Matrix Support Rooms",
    description: "Configured Matrix sync rooms.",
    icon: MessageCircle,
  },
];

interface EscalationRouteOption {
  value: EscalationNotificationChannel;
  label: string;
}

const ESCALATION_ROUTE_OPTIONS: EscalationRouteOption[] = [
  { value: "staff_room", label: "Staff Room" },
  { value: "none", label: "User Room Only" },
  { value: "public_room", label: "Public Room" },
];

const DEFAULT_ESCALATION_ROUTE: Record<ChannelId, EscalationNotificationChannel> = {
  web: "public_room",
  bisq2: "staff_room",
  matrix: "staff_room",
};

const ESCALATION_ROUTE_LABELS: Record<EscalationNotificationChannel, string> = {
  public_room: "Public Room",
  staff_room: "Staff Room",
  none: "User Room Only",
};

const ESCALATION_ROUTE_MEANING: Record<EscalationNotificationChannel, string> = {
  public_room:
    "Send internal escalation notice in the same user room.",
  staff_room:
    "Send internal escalation notice to staff room.",
  none:
    "Do not post an internal escalation notice to public or staff room.",
};

interface EscalationUserNoticeModeOption {
  value: ChannelEscalationUserNoticeMode;
  label: string;
}

const ESCALATION_USER_NOTICE_MODE_OPTIONS: EscalationUserNoticeModeOption[] = [
  { value: "none", label: "Off" },
  { value: "message", label: "Message" },
];

const DEFAULT_ESCALATION_USER_NOTICE_MODE: Record<ChannelId, ChannelEscalationUserNoticeMode> = {
  web: "message",
  bisq2: "message",
  matrix: "message",
};

const ESCALATION_USER_NOTICE_MODE_LABELS: Record<ChannelEscalationUserNoticeMode, string> = {
  none: "Off",
  message: "Message",
};

const ESCALATION_USER_NOTICE_MODE_MEANING: Record<ChannelEscalationUserNoticeMode, string> = {
  none: "Do not send any escalation acknowledgment to the user room.",
  message: "Post a short user-safe escalation notice in the user room.",
};

interface AcknowledgmentModeOption {
  value: ChannelAcknowledgmentMode;
  label: string;
}

const ACKNOWLEDGMENT_MODE_OPTIONS: AcknowledgmentModeOption[] = [
  { value: "none", label: "None" },
  { value: "reaction", label: "Reaction" },
  { value: "message", label: "Message" },
];

const DEFAULT_ACKNOWLEDGMENT_MODE: Record<ChannelId, ChannelAcknowledgmentMode> = {
  web: "none",
  bisq2: "message",
  matrix: "reaction",
};

const DEFAULT_ACKNOWLEDGMENT_REACTION_KEY = "👀";
const DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE =
  "Thanks for your question. A team member or our assistant will respond shortly.";

const ACKNOWLEDGMENT_MODE_LABELS: Record<ChannelAcknowledgmentMode, string> = {
  none: "None",
  reaction: "Reaction",
  message: "Message",
};

const ACKNOWLEDGMENT_MODE_MEANING: Record<ChannelAcknowledgmentMode, string> = {
  none: "Do not send an immediate acknowledgment.",
  reaction: "React to the user message immediately (for example 👀).",
  message: "Send a short user-facing acknowledgment message immediately.",
};

const ACKNOWLEDGMENT_MODE_DISABLED_REASONS: Partial<
  Record<ChannelId, Partial<Record<ChannelAcknowledgmentMode, string>>>
> = {
  web: {
    reaction: "Web Chat currently does not support emoji reactions.",
  },
};

const WEB_ROUTING_LOCK_REASON =
  "Web Chat does not route escalation notices to separate rooms yet. Responses are surfaced in the web chat thread and escalation status is tracked there.";

interface AcknowledgmentDraft {
  reactionKey: string;
  messageTemplate: string;
}

function buildAcknowledgmentDrafts(
  policies: ChannelAutoresponsePolicy[],
): Record<ChannelId, AcknowledgmentDraft> {
  const defaults: Record<ChannelId, AcknowledgmentDraft> = {
    web: {
      reactionKey: DEFAULT_ACKNOWLEDGMENT_REACTION_KEY,
      messageTemplate: DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE,
    },
    bisq2: {
      reactionKey: DEFAULT_ACKNOWLEDGMENT_REACTION_KEY,
      messageTemplate: DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE,
    },
    matrix: {
      reactionKey: DEFAULT_ACKNOWLEDGMENT_REACTION_KEY,
      messageTemplate: DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE,
    },
  };

  for (const policy of policies) {
    defaults[policy.channel_id] = {
      reactionKey: policy.acknowledgment_reaction_key || DEFAULT_ACKNOWLEDGMENT_REACTION_KEY,
      messageTemplate:
        policy.acknowledgment_message_template || DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE,
    };
  }

  return defaults;
}

function isAcknowledgmentModeSupported(
  channelId: ChannelId,
  mode: ChannelAcknowledgmentMode,
): boolean {
  return !ACKNOWLEDGMENT_MODE_DISABLED_REASONS[channelId]?.[mode];
}

function disabledAcknowledgmentModeReason(
  channelId: ChannelId,
  mode: ChannelAcknowledgmentMode,
): string {
  return ACKNOWLEDGMENT_MODE_DISABLED_REASONS[channelId]?.[mode] ?? "";
}

export function ChannelAutoresponseCard({
  policies,
  isLoading,
  isSavingByChannel,
  error,
  onModeChange,
  onEscalationRouteChange,
  onAcknowledgmentModeChange,
  onAcknowledgmentReactionKeyChange,
  onAcknowledgmentMessageTemplateChange,
  onEscalationUserNoticeModeChange,
  onRetry,
}: ChannelAutoresponseCardProps) {
  const policyMap = new Map<ChannelId, ChannelAutoresponsePolicy>(
    policies.map((policy) => [policy.channel_id, policy]),
  );
  const [ackDraftByChannel, setAckDraftByChannel] = useState<Record<ChannelId, AcknowledgmentDraft>>(
    () => buildAcknowledgmentDrafts(policies),
  );

  useEffect(() => {
    setAckDraftByChannel(buildAcknowledgmentDrafts(policies));
  }, [policies]);

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold">Channel Auto-Responses</h3>
          <Badge variant="outline" className="text-xs text-muted-foreground">
            Default: Web on, Bisq2/Matrix off
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Per channel mode: Off (ignore messages), Review (HITL, drafts require support approval), or Auto-send.
        </p>
      </div>

      {isLoading && policies.length === 0 ? (
        <>
          <ChannelRowSkeleton />
          <ChannelRowSkeleton />
          <ChannelRowSkeleton />
        </>
      ) : (
        CHANNELS.map((channel) => {
          const policy = policyMap.get(channel.id);
          const generationEnabled = Boolean(policy?.generation_enabled);
          const autosendEnabled = Boolean(policy?.enabled);
          const aiResponseMode = policy?.ai_response_mode ?? "autonomous";
          const isSaving = isSavingByChannel[channel.id];
          const Icon = channel.icon;
          const escalationRoute = (
            policy?.escalation_notification_channel
            ?? DEFAULT_ESCALATION_ROUTE[channel.id]
          );
          const isRouteTargetConfigurable = channel.id !== "web";
          const isRouteControlDisabled = isSaving || !isRouteTargetConfigurable;
          const mode: ChannelResponseMode = !generationEnabled
            ? "off"
            : (aiResponseMode === "hitl" || !autosendEnabled)
              ? "review"
              : "auto";
          const modeLabel = mode === "off"
            ? "AI processing off"
            : mode === "review"
              ? "Review (HITL)"
              : "Auto-send mode";
          const acknowledgmentMode = (
            policy?.acknowledgment_mode
            ?? DEFAULT_ACKNOWLEDGMENT_MODE[channel.id]
          );
          const policyReactionKey =
            policy?.acknowledgment_reaction_key ?? DEFAULT_ACKNOWLEDGMENT_REACTION_KEY;
          const policyMessageTemplate =
            policy?.acknowledgment_message_template ?? DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE;
          const reactionKeyDraft =
            ackDraftByChannel[channel.id]?.reactionKey ?? policyReactionKey;
          const messageTemplateDraft =
            ackDraftByChannel[channel.id]?.messageTemplate ?? policyMessageTemplate;
          const webReactionDisabledReason = disabledAcknowledgmentModeReason(
            channel.id,
            "reaction",
          );
          const escalationUserNoticeMode = (
            policy?.escalation_user_notice_mode
            ?? DEFAULT_ESCALATION_USER_NOTICE_MODE[channel.id]
          );

          return (
            <article
              key={channel.id}
              className={cn(
                "rounded-xl border p-3 transition-colors",
                generationEnabled
                  ? "border-emerald-500/35 bg-emerald-500/5"
                  : "border-border/70 bg-background/40",
              )}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="space-y-1">
                  <div className="inline-flex items-center gap-2 text-sm font-medium">
                    <Icon className="h-4 w-4 text-muted-foreground" />
                    {channel.label}
                  </div>
                  <p className="text-xs text-muted-foreground">{channel.description}</p>
                </div>

                <div className="flex flex-wrap items-center justify-end gap-2">
                  <Badge
                    variant="secondary"
                    className={cn(
                      "border text-xs",
                      mode !== "off"
                        ? "border-emerald-500/30 bg-emerald-500/20 text-emerald-300"
                        : "border-amber-500/35 bg-amber-500/20 text-amber-300",
                    )}
                  >
                    {mode !== "off" ? (
                      <>
                        <ShieldCheck className="mr-1 h-3.5 w-3.5" />
                        {modeLabel}
                      </>
                    ) : (
                      <>
                        <ShieldAlert className="mr-1 h-3.5 w-3.5" />
                        {modeLabel}
                      </>
                    )}
                  </Badge>
                  {isSaving ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
                </div>
              </div>
              <div className="mt-3">
                <ToggleGroup
                  type="single"
                  value={mode}
                  onValueChange={(value) => {
                    if (value === "off" || value === "review" || value === "auto") {
                      onModeChange(channel.id, value);
                    }
                  }}
                  className="justify-start"
                  disabled={isSaving}
                >
                  <ToggleGroupItem
                    value="off"
                    variant="outline"
                    size="sm"
                    className="min-w-[70px] text-xs"
                  >
                    Off
                  </ToggleGroupItem>
                  <ToggleGroupItem
                    value="review"
                    variant="outline"
                    size="sm"
                    className="min-w-[84px] text-xs"
                  >
                    Review (HITL)
                  </ToggleGroupItem>
                  <ToggleGroupItem
                    value="auto"
                    variant="outline"
                    size="sm"
                    className="min-w-[94px] text-xs"
                  >
                    Auto-send
                  </ToggleGroupItem>
                </ToggleGroup>
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                {mode === "off"
                  ? "Inbound channel messages are ignored by the AI pipeline."
                  : mode === "review"
                    ? "Review (HITL): AI drafts for staff, waits for approval, and escalates on HITL timeout."
                    : "AI generates and sends responses immediately."}
              </p>
              {policy ? (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Delay {policy.first_response_delay_seconds}s, cooldown {policy.staff_active_cooldown_seconds}s, HITL timeout {policy.hitl_approval_timeout_seconds}s.
                </p>
              ) : null}
              <div className="mt-3 space-y-2">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-medium text-foreground">Internal Notice Target</p>
                  {!isRouteTargetConfigurable ? (
                    <TooltipProvider delayDuration={0}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                            aria-label="Why web routing targets are disabled"
                          >
                            <Info className="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs">
                          {WEB_ROUTING_LOCK_REASON}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : null}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Choose where internal escalation notices are posted when a message is queued for human review.
                </p>
                <ToggleGroup
                  type="single"
                  value={escalationRoute}
                  onValueChange={(value) => {
                    if (!isRouteTargetConfigurable) {
                      return;
                    }
                    if (value === "public_room" || value === "staff_room" || value === "none") {
                      onEscalationRouteChange(channel.id, value);
                    }
                  }}
                  className="justify-start"
                  disabled={isRouteControlDisabled}
                >
                  {ESCALATION_ROUTE_OPTIONS.map((option) => (
                    <ToggleGroupItem
                      key={`${channel.id}-${option.value}`}
                      value={option.value}
                      variant="outline"
                      size="sm"
                      className="min-w-[108px] text-xs"
                    >
                      {option.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <p className="text-[11px] text-muted-foreground">
                  Selected: {ESCALATION_ROUTE_LABELS[escalationRoute]}. {ESCALATION_ROUTE_MEANING[escalationRoute]}
                </p>
              </div>

              <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-medium text-foreground">User Room Escalation Notice</p>
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Configure whether users are notified in their room when escalation is queued.
                </p>
                <ToggleGroup
                  type="single"
                  value={escalationUserNoticeMode}
                  onValueChange={(value) => {
                    if (value === "none" || value === "message") {
                      onEscalationUserNoticeModeChange(channel.id, value);
                    }
                  }}
                  className="justify-start"
                  disabled={isSaving}
                >
                  {ESCALATION_USER_NOTICE_MODE_OPTIONS.map((option) => (
                    <ToggleGroupItem
                      key={`${channel.id}-escalation-user-notice-${option.value}`}
                      value={option.value}
                      variant="outline"
                      size="sm"
                      className="min-w-[98px] text-xs"
                      disabled={isSaving}
                    >
                      {option.label}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
                <p className="text-[11px] text-muted-foreground">
                  Selected: {ESCALATION_USER_NOTICE_MODE_LABELS[escalationUserNoticeMode]}. {ESCALATION_USER_NOTICE_MODE_MEANING[escalationUserNoticeMode]}
                </p>
              </div>

              <div className="mt-3 space-y-2 border-t border-border/60 pt-3">
                <div className="flex items-center gap-1.5">
                  <p className="text-xs font-medium text-foreground">Immediate Receipt Acknowledgment</p>
                  {webReactionDisabledReason ? (
                    <TooltipProvider delayDuration={0}>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <button
                            type="button"
                            className="inline-flex h-5 w-5 items-center justify-center rounded-full text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                            aria-label={`Why acknowledgment reaction is disabled for ${channel.label}`}
                          >
                            <Info className="h-3.5 w-3.5" />
                          </button>
                        </TooltipTrigger>
                        <TooltipContent className="max-w-xs">
                          {webReactionDisabledReason}
                        </TooltipContent>
                      </Tooltip>
                    </TooltipProvider>
                  ) : null}
                </div>
                <p className="text-[11px] text-muted-foreground">
                  Configure whether users receive an immediate acknowledgment while processing starts.
                </p>
                <ToggleGroup
                  type="single"
                  value={acknowledgmentMode}
                  onValueChange={(value) => {
                    if (value === "none" || value === "reaction" || value === "message") {
                      if (!isAcknowledgmentModeSupported(channel.id, value)) {
                        return;
                      }
                      onAcknowledgmentModeChange(channel.id, value);
                    }
                  }}
                  className="justify-start"
                  disabled={isSaving}
                >
                  {ACKNOWLEDGMENT_MODE_OPTIONS.map((option) => {
                    const isUnsupported = !isAcknowledgmentModeSupported(channel.id, option.value);
                    return (
                      <ToggleGroupItem
                        key={`${channel.id}-ack-${option.value}`}
                        value={option.value}
                        variant="outline"
                        size="sm"
                        className="min-w-[98px] text-xs"
                        disabled={isSaving || isUnsupported}
                      >
                        {option.label}
                      </ToggleGroupItem>
                    );
                  })}
                </ToggleGroup>
                <p className="text-[11px] text-muted-foreground">
                  Selected: {ACKNOWLEDGMENT_MODE_LABELS[acknowledgmentMode]}. {ACKNOWLEDGMENT_MODE_MEANING[acknowledgmentMode]}
                </p>
                <p className="text-[11px] text-muted-foreground">
                  This acknowledgment is independent from escalation notices.
                </p>

                {acknowledgmentMode === "reaction" ? (
                  <div className="space-y-1.5">
                    <label
                      htmlFor={`${channel.id}-ack-reaction`}
                      className="text-[11px] font-medium text-foreground"
                    >
                      Reaction emoji
                    </label>
                    <Input
                      id={`${channel.id}-ack-reaction`}
                      aria-label="Reaction emoji"
                      value={reactionKeyDraft}
                      onChange={(event) => {
                        const nextReactionKey = event.target.value;
                        setAckDraftByChannel((current) => ({
                          ...current,
                          [channel.id]: {
                            reactionKey: nextReactionKey,
                            messageTemplate:
                              current[channel.id]?.messageTemplate ?? policyMessageTemplate,
                          },
                        }));
                      }}
                      onBlur={(event) => {
                        const nextReactionKey = event.target.value.trim() || DEFAULT_ACKNOWLEDGMENT_REACTION_KEY;
                        if (nextReactionKey !== event.target.value) {
                          setAckDraftByChannel((current) => ({
                            ...current,
                            [channel.id]: {
                              reactionKey: nextReactionKey,
                              messageTemplate:
                                current[channel.id]?.messageTemplate ?? policyMessageTemplate,
                            },
                          }));
                        }
                        if (nextReactionKey !== policyReactionKey) {
                          onAcknowledgmentReactionKeyChange(channel.id, nextReactionKey);
                        }
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") {
                          event.preventDefault();
                          event.currentTarget.blur();
                        }
                      }}
                      disabled={isSaving}
                      className="h-8 max-w-[180px] text-xs"
                    />
                  </div>
                ) : null}

                {acknowledgmentMode === "message" ? (
                  <div className="space-y-1.5">
                    <label
                      htmlFor={`${channel.id}-ack-template`}
                      className="text-[11px] font-medium text-foreground"
                    >
                      Acknowledgment message
                    </label>
                    <Textarea
                      id={`${channel.id}-ack-template`}
                      aria-label="Acknowledgment message"
                      value={messageTemplateDraft}
                      onChange={(event) => {
                        const nextMessageTemplate = event.target.value;
                        setAckDraftByChannel((current) => ({
                          ...current,
                          [channel.id]: {
                            reactionKey:
                              current[channel.id]?.reactionKey ?? policyReactionKey,
                            messageTemplate: nextMessageTemplate,
                          },
                        }));
                      }}
                      onBlur={(event) => {
                        const nextMessageTemplate = event.target.value.trim()
                          || DEFAULT_ACKNOWLEDGMENT_MESSAGE_TEMPLATE;
                        if (nextMessageTemplate !== event.target.value) {
                          setAckDraftByChannel((current) => ({
                            ...current,
                            [channel.id]: {
                              reactionKey:
                                current[channel.id]?.reactionKey ?? policyReactionKey,
                              messageTemplate: nextMessageTemplate,
                            },
                          }));
                        }
                        if (nextMessageTemplate !== policyMessageTemplate) {
                          onAcknowledgmentMessageTemplateChange(channel.id, nextMessageTemplate);
                        }
                      }}
                      disabled={isSaving}
                      className="min-h-[68px] text-xs"
                    />
                  </div>
                ) : null}
              </div>
            </article>
          );
        })
      )}

      {error ? (
        <div className="rounded-lg border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-xs text-amber-200/90">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <span>{error}</span>
            <Button
              size="sm"
              variant="ghost"
              onClick={onRetry}
              className="h-7 px-2 text-xs"
            >
              Retry
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ChannelRowSkeleton() {
  return (
    <div className="rounded-xl border border-border/70 bg-background/40 p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5">
          <Skeleton className="h-4 w-36" />
          <Skeleton className="h-3 w-56" />
        </div>
        <div className="flex items-center gap-2">
          <Skeleton className="h-6 w-24 rounded-full" />
          <Skeleton className="h-4 w-4 rounded-full" />
        </div>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Skeleton className="h-8 w-16 rounded-md" />
        <Skeleton className="h-8 w-20 rounded-md" />
        <Skeleton className="h-8 w-24 rounded-md" />
      </div>
    </div>
  );
}
