"use client";

import { Radar, ShieldAlert, Siren } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { TrustFinding } from "@/components/admin/security/types";

export const DETECTOR_LABELS: Record<TrustFinding["detector_key"], string> = {
  staff_name_collision: "Staff Name Collision",
  silent_early_observer: "Silent Observer",
};

export const DETECTOR_DESCRIPTIONS: Record<TrustFinding["detector_key"], string> = {
  staff_name_collision: "Trusted identity mismatch in a public support room.",
  silent_early_observer: "High read activity with unusually low reply participation.",
};

export const DETECTOR_ICONS = {
  staff_name_collision: ShieldAlert,
  silent_early_observer: Radar,
} satisfies Record<TrustFinding["detector_key"], LucideIcon>;

export const FALLBACK_DETECTOR_ICON = Siren;

export const STATUS_STYLES: Record<TrustFinding["status"], string> = {
  open: "border-amber-500/30 bg-amber-500/10 text-amber-200",
  resolved: "border-emerald-500/30 bg-emerald-500/10 text-emerald-200",
  false_positive: "border-sky-500/30 bg-sky-500/10 text-sky-200",
  suppressed: "border-zinc-500/30 bg-zinc-500/10 text-zinc-200",
  benign: "border-violet-500/30 bg-violet-500/10 text-violet-200",
};

export function formatStatus(status: TrustFinding["status"]): string {
  return status.replace(/_/g, " ");
}

export function formatRelativeTime(value: string): string {
  const diffMs = Date.now() - new Date(value).getTime();
  const diffMinutes = Math.max(0, Math.floor(diffMs / 60000));

  if (diffMinutes < 1) {
    return "just now";
  }
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }

  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }

  return `${Math.floor(diffHours / 24)}d ago`;
}
