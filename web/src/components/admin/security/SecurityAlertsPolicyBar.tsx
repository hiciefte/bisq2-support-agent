"use client";

import Link from "next/link";
import { Radar, ShieldAlert, ShieldCheck, SlidersHorizontal } from "lucide-react";
import type { ReactNode } from "react";
import type { TrustAlertSurface, TrustMonitorPolicy } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface SecurityAlertsPolicyBarProps {
  policy: TrustMonitorPolicy | null;
}

function surfaceLabel(surface: TrustAlertSurface | undefined): string {
  switch (surface) {
    case "staff_room":
      return "Staff Room Live";
    case "both":
      return "Admin UI + Staff Room";
    case "none":
      return "Muted";
    default:
      return "Admin UI Shadow";
  }
}

function rolloutDescription(policy: TrustMonitorPolicy | null): string {
  if (!policy?.enabled) {
    return "Trust monitoring is disabled. Configure rollout and detector thresholds from Overview before relying on this review queue.";
  }
  if (policy.alert_surface === "staff_room" || policy.alert_surface === "both") {
    return "Findings can already surface into the staff room. Review the queue here, but keep rollout and threshold changes centralized in Overview.";
  }
  return "Review trust-monitor findings here. Configuration stays on Overview so rollout, detector state, and thresholds have one source of truth.";
}

function enabledDetectors(policy: TrustMonitorPolicy | null): string {
  if (!policy?.enabled) {
    return "Disabled";
  }
  const detectors = [];
  if (policy.name_collision_enabled) {
    detectors.push("Name Collision");
  }
  if (policy.silent_observer_enabled) {
    detectors.push("Silent Observer");
  }
  return detectors.length > 0 ? detectors.join(" + ") : "No detectors enabled";
}

function roomSummary(policy: TrustMonitorPolicy | null): string {
  const publicRooms = policy?.matrix_public_room_ids?.length ?? 0;
  const staffRoom = policy?.matrix_staff_room_id ? "Configured" : "Missing";
  return `${publicRooms} public room${publicRooms === 1 ? "" : "s"} · Staff ${staffRoom}`;
}

function thresholdSummary(policy: TrustMonitorPolicy | null): string {
  if (!policy) {
    return "Window 14d · Early read 30s";
  }
  return `Window ${policy.silent_observer_window_days}d · Early read ${policy.early_read_window_seconds}s`;
}

export function SecurityAlertsPolicyBar({ policy }: SecurityAlertsPolicyBarProps) {
  const currentSurface = policy?.alert_surface ?? "admin_ui";

  return (
    <section className="rounded-3xl border border-border/70 bg-card/80 p-5 shadow-sm">
      <div className="flex flex-col gap-5">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-semibold tracking-tight">Security Alerts</h1>
              <Badge variant="secondary" className="border border-border/60 bg-background/70 text-xs text-muted-foreground">
                {surfaceLabel(currentSurface)}
              </Badge>
            </div>
            <p className="max-w-3xl text-sm text-muted-foreground">
              {rolloutDescription(policy)}
            </p>
          </div>
          <Button asChild size="sm" className="self-start rounded-xl px-4 xl:self-auto">
            <Link href="/admin/overview">Configure in Overview</Link>
          </Button>
        </div>

        <div className="grid gap-3 lg:grid-cols-3">
          <SummaryCard
            icon={<ShieldCheck aria-hidden="true" className="h-4 w-4 text-emerald-300" />}
            label="Rollout mode"
            value={surfaceLabel(currentSurface)}
            hint="Overview owns alert-surface changes."
          />
          <SummaryCard
            icon={<Radar aria-hidden="true" className="h-4 w-4 text-sky-300" />}
            label="Enabled detectors"
            value={enabledDetectors(policy)}
            hint="Keep detector toggles centralized on Overview."
          />
          <SummaryCard
            icon={<SlidersHorizontal aria-hidden="true" className="h-4 w-4 text-amber-300" />}
            label="Threshold snapshot"
            value={thresholdSummary(policy)}
            hint={roomSummary(policy)}
          />
        </div>

        {!policy?.enabled ? (
          <div className="rounded-2xl border border-amber-500/25 bg-amber-500/6 px-4 py-3 text-sm text-amber-100/90">
            The review queue is available, but the detector pipeline is currently disabled. Re-enable trust monitoring from Overview before acting on this page operationally.
          </div>
        ) : null}

        <div className="rounded-2xl border border-border/70 bg-background/35 px-4 py-3">
          <div className="inline-flex items-center gap-2 text-sm font-medium">
            <ShieldAlert aria-hidden="true" className="h-4 w-4 text-muted-foreground" />
            Review workflow
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            Use this page to triage findings, inspect evidence, and apply review decisions. Use Overview for rollout, detector, and threshold changes.
          </p>
        </div>
      </div>
    </section>
  );
}

function SummaryCard({
  icon,
  label,
  value,
  hint,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="rounded-2xl border border-border/70 bg-background/40 px-4 py-4">
      <div className="inline-flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground">
        {icon}
        {label}
      </div>
      <div className="mt-3 text-base font-semibold tracking-tight text-foreground/95">
        {value}
      </div>
      <div className="mt-1 text-xs text-muted-foreground">
        {hint}
      </div>
    </div>
  );
}
