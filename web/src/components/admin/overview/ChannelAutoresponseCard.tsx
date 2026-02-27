"use client";

import type { LucideIcon } from "lucide-react";
import {
  Cat,
  Globe2,
  Loader2,
  MessageCircle,
  ShieldAlert,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import {
  type ChannelAutoresponsePolicy,
  type ChannelId,
} from "@/components/admin/overview/types";
import {
  type ChannelResponseMode,
} from "@/hooks/useChannelAutoresponsePolicies";
import { cn } from "@/lib/utils";

interface ChannelAutoresponseCardProps {
  policies: ChannelAutoresponsePolicy[];
  isLoading: boolean;
  isSavingByChannel: Record<ChannelId, boolean>;
  error: string | null;
  onModeChange: (channelId: ChannelId, mode: ChannelResponseMode) => void;
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

export function ChannelAutoresponseCard({
  policies,
  isLoading,
  isSavingByChannel,
  error,
  onModeChange,
  onRetry,
}: ChannelAutoresponseCardProps) {
  const policyMap = new Map<ChannelId, ChannelAutoresponsePolicy>(
    policies.map((policy) => [policy.channel_id, policy]),
  );

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
          Per channel mode: Off (ignore messages), Review (drafts require support approval), or Auto-send.
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
            const isSaving = isSavingByChannel[channel.id];
            const Icon = channel.icon;
            const mode: ChannelResponseMode = !generationEnabled
              ? "off"
              : autosendEnabled
                ? "auto"
                : "review";
            const modeLabel = mode === "off"
              ? "AI processing off"
              : mode === "review"
                ? "Review mode"
                : "Auto-send mode";

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
                      Review
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
                      ? "AI generates drafts, but messages are sent only after support approval."
                      : "AI generates and sends responses immediately."}
                </p>
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
