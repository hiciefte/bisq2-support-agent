"use client";

import Link from "next/link";
import type { TrustAlertSurface, TrustMonitorPolicy } from "@/components/admin/security/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

interface SecurityAlertsPolicyBarProps {
  policy: TrustMonitorPolicy | null;
  isSaving: boolean;
  onAlertSurfaceChange: (surface: TrustAlertSurface) => void;
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

export function SecurityAlertsPolicyBar({ policy, isSaving, onAlertSurfaceChange }: SecurityAlertsPolicyBarProps) {
  const currentSurface = policy?.alert_surface ?? "admin_ui";
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-border/70 bg-card/70 px-4 py-4 md:flex-row md:items-center md:justify-between">
      <div className="space-y-1">
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Security Alerts</h1>
          <Badge variant="secondary" className="border border-border/60 bg-background/70 text-xs text-muted-foreground">
            {surfaceLabel(currentSurface)}
          </Badge>
        </div>
        <p className="text-sm text-muted-foreground">
          Review trust-monitor findings before promoting them into the staff room.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={isSaving || currentSurface === "staff_room"}
          onClick={() => onAlertSurfaceChange("staff_room")}
        >
          Promote to Staff Room
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={isSaving || currentSurface === "admin_ui"}
          onClick={() => onAlertSurfaceChange("admin_ui")}
        >
          Return to Admin UI Only
        </Button>
        <Button asChild variant="ghost" size="sm">
          <Link href="/admin/overview">Overview controls</Link>
        </Button>
      </div>
    </div>
  );
}
