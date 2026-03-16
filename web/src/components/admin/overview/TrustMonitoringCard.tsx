"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { Loader2, Radar, ShieldAlert, ShieldCheck } from "lucide-react";
import type { TrustAlertSurface, TrustMonitorPolicy } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { cn } from "@/lib/utils";

interface TrustMonitoringCardProps {
  policy: TrustMonitorPolicy | null;
  isLoading: boolean;
  isSaving: boolean;
  error: string | null;
  onRetry: () => void;
  onEnabledChange: (enabled: boolean) => void;
  onDetectorToggle: (detector: "name_collision_enabled" | "silent_observer_enabled", value: boolean) => void;
  onAlertSurfaceChange: (surface: TrustAlertSurface) => void;
}

const TRUST_ALERT_SURFACES: readonly TrustAlertSurface[] = [
  "admin_ui",
  "staff_room",
  "both",
  "none",
];

function rolloutState(policy: TrustMonitorPolicy | null): { label: string; description: string } {
  if (!policy || !policy.enabled) {
    return { label: "Off", description: "Detection is disabled." };
  }
  switch (policy.alert_surface) {
    case "admin_ui":
      return { label: "Admin UI Shadow", description: "Findings stay in admin review only." };
    case "staff_room":
      return { label: "Staff Room Live", description: "Findings are pushed into the Matrix staff room." };
    case "both":
      return { label: "Admin UI + Staff Room", description: "Findings appear in admin review and Matrix staff room." };
    default:
      return { label: "Muted", description: "Findings are detected but not surfaced." };
  }
}

export function TrustMonitoringCard({
  policy,
  isLoading,
  isSaving,
  error,
  onRetry,
  onEnabledChange,
  onDetectorToggle,
  onAlertSurfaceChange,
}: TrustMonitoringCardProps) {
  const rollout = rolloutState(policy);
  const showPromotionWarning = policy?.enabled && (policy.alert_surface === "staff_room" || policy.alert_surface === "both");

  return (
    <Card className="border-border/70 bg-card/70">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-lg">Trust Monitoring</CardTitle>
              <Badge variant="secondary" className="border border-border/60 bg-background/70 text-xs text-muted-foreground">
                {rollout.label}
              </Badge>
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
            </div>
            <p className="text-sm text-muted-foreground">{rollout.description}</p>
          </div>
          {error ? (
            <Button variant="outline" size="sm" onClick={onRetry}>Retry</Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {error ? (
          <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
            {error}
          </div>
        ) : null}

        <div className="flex items-center justify-between rounded-xl border border-border/70 bg-background/40 px-4 py-3">
          <div>
            <div className="text-sm font-medium">Trust monitoring</div>
            <div className="text-xs text-muted-foreground">Enable the shared detector pipeline for Matrix support rooms.</div>
          </div>
          <Checkbox
            checked={policy?.enabled ?? false}
            disabled={isLoading || policy === null}
            onCheckedChange={(checked) => onEnabledChange(Boolean(checked))}
            aria-label="Toggle trust monitoring"
          />
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <DetectorToggle
            title="Staff Name Collision"
            description="Detect accounts using a trusted staff display name with a different user ID."
            checked={policy?.name_collision_enabled ?? false}
            disabled={isLoading || policy === null || !policy?.enabled}
            icon={<ShieldAlert className="h-4 w-4 text-amber-300" />}
            onChange={(value) => onDetectorToggle("name_collision_enabled", value)}
          />
          <DetectorToggle
            title="Silent Observer"
            description="Track early readers with low reply activity and keep them in review until validated."
            checked={policy?.silent_observer_enabled ?? false}
            disabled={isLoading || policy === null || !policy?.enabled}
            icon={<Radar className="h-4 w-4 text-blue-300" />}
            onChange={(value) => onDetectorToggle("silent_observer_enabled", value)}
          />
        </div>

        <div className="space-y-2 rounded-xl border border-border/70 bg-background/40 px-4 py-3">
          <div className="flex items-center gap-2 text-sm font-medium">
            <ShieldCheck className="h-4 w-4 text-emerald-300" />
            Alert destination
          </div>
          <ToggleGroup
            type="single"
            value={policy?.alert_surface ?? "admin_ui"}
            onValueChange={(value) => {
              if (TRUST_ALERT_SURFACES.includes(value as TrustAlertSurface)) {
                onAlertSurfaceChange(value as TrustAlertSurface);
              }
            }}
            className="justify-start"
          >
            <ToggleGroupItem value="admin_ui" variant="outline" size="sm">Admin UI</ToggleGroupItem>
            <ToggleGroupItem value="staff_room" variant="outline" size="sm">Staff Room</ToggleGroupItem>
            <ToggleGroupItem value="both" variant="outline" size="sm">Both</ToggleGroupItem>
            <ToggleGroupItem value="none" variant="outline" size="sm">None</ToggleGroupItem>
          </ToggleGroup>
          {policy?.silent_observer_enabled && policy.alert_surface === "admin_ui" ? (
            <div className="text-xs text-muted-foreground">
              Silent Observer is active in shadow mode. Findings are visible in Admin UI only.
            </div>
          ) : null}
          {showPromotionWarning ? (
            <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-amber-200">
              Promotion is live. Findings may now interrupt staff in Matrix. Keep thresholds conservative.
            </div>
          ) : null}
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-xl border border-border/70 bg-background/40 px-4 py-3">
            <div className="text-sm font-medium">Room scope</div>
            <div className="mt-1 text-xs text-muted-foreground">
              Public rooms: {(policy?.matrix_public_room_ids ?? []).join(", ") || "Not configured"}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              Staff room: {policy?.matrix_staff_room_id || "Not configured"}
            </div>
          </div>
          <div className="rounded-xl border border-border/70 bg-background/40 px-4 py-3">
            <div className="text-sm font-medium">Thresholds</div>
            <div className="mt-1 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
              <div>Window: {policy?.silent_observer_window_days ?? 0}d</div>
              <div>Early read: {policy?.early_read_window_seconds ?? 0}s</div>
              <div>Min observations: {policy?.minimum_observations ?? 0}</div>
              <div>Min hits: {policy?.minimum_early_read_hits ?? 0}</div>
            </div>
          </div>
        </div>
        <div className="flex justify-end">
          <Button asChild variant="ghost" size="sm">
            <Link href="/admin/security/alerts">Open security review</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function DetectorToggle({
  title,
  description,
  checked,
  disabled,
  icon,
  onChange,
}: {
  title: string;
  description: string;
  checked: boolean;
  disabled: boolean;
  icon: ReactNode;
  onChange: (checked: boolean) => void;
}) {
  return (
    <div className={cn("rounded-xl border border-border/70 bg-background/40 px-4 py-3", disabled ? "opacity-70" : null)}>
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="inline-flex items-center gap-2 text-sm font-medium">{icon}{title}</div>
          <div className="text-xs text-muted-foreground">{description}</div>
        </div>
        <Checkbox checked={checked} disabled={disabled} onCheckedChange={(next) => onChange(Boolean(next))} aria-label={`Toggle ${title}`} />
      </div>
    </div>
  );
}
