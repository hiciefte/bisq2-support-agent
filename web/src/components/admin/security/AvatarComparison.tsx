"use client";

import { ArrowLeftRight, ShieldAlert, ShieldCheck } from "lucide-react";
import { MatrixAvatar } from "@/components/admin/security/MatrixAvatar";
import { cn } from "@/lib/utils";

export interface AvatarComparisonProps {
  suspectAvatarUrl: string | null | undefined;
  suspectDisplayName: string | null | undefined;
  suspectActorId: string | null | undefined;
  staffAvatarUrl: string | null | undefined;
  staffDisplayName: string | null | undefined;
  className?: string;
}

/**
 * Side-by-side comparison of a suspected impersonator and the legitimate
 * staff member their display name collides with. The visual layout makes
 * the impersonation obvious at a glance: identical names + (often)
 * unrelated avatars.
 */
export function AvatarComparison({
  suspectAvatarUrl,
  suspectDisplayName,
  suspectActorId,
  staffAvatarUrl,
  staffDisplayName,
  className,
}: AvatarComparisonProps) {
  return (
    <div
      className={cn(
        "grid items-stretch gap-3 rounded-2xl border border-border/70 bg-background/40 p-4 sm:grid-cols-[1fr_auto_1fr]",
        className,
      )}
      data-testid="avatar-comparison"
    >
      <ComparisonCard
        tone="suspect"
        icon={<ShieldAlert className="h-3.5 w-3.5" />}
        label="Suspect"
        avatarUrl={suspectAvatarUrl}
        displayName={suspectDisplayName}
        secondary={suspectActorId ?? null}
      />

      <div
        className="flex items-center justify-center text-muted-foreground"
        aria-hidden="true"
      >
        <ArrowLeftRight className="h-4 w-4" />
      </div>

      <ComparisonCard
        tone="staff"
        icon={<ShieldCheck className="h-3.5 w-3.5" />}
        label="Legitimate staff"
        avatarUrl={staffAvatarUrl}
        displayName={staffDisplayName}
        secondary="Verified"
      />
    </div>
  );
}

interface ComparisonCardProps {
  tone: "suspect" | "staff";
  icon: React.ReactNode;
  label: string;
  avatarUrl: string | null | undefined;
  displayName: string | null | undefined;
  secondary: string | null;
}

function ComparisonCard({
  tone,
  icon,
  label,
  avatarUrl,
  displayName,
  secondary,
}: ComparisonCardProps) {
  const isSuspect = tone === "suspect";
  return (
    <div
      className={cn(
        "flex items-center gap-3 rounded-xl border p-3",
        isSuspect
          ? "border-red-500/30 bg-red-500/5"
          : "border-emerald-500/30 bg-emerald-500/5",
      )}
    >
      <MatrixAvatar
        avatarUrl={avatarUrl}
        displayName={displayName}
        className={cn(
          "h-14 w-14",
          isSuspect ? "ring-red-500/40" : "ring-emerald-500/40",
        )}
      />
      <div className="min-w-0">
        <div
          className={cn(
            "inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-[0.16em]",
            isSuspect ? "text-red-300" : "text-emerald-300",
          )}
        >
          {icon}
          {label}
        </div>
        <div className="mt-1 truncate text-sm font-semibold text-foreground/95">
          {displayName?.trim() || "Unknown"}
        </div>
        {secondary ? (
          <div className="truncate text-xs text-muted-foreground">
            {secondary}
          </div>
        ) : null}
      </div>
    </div>
  );
}
