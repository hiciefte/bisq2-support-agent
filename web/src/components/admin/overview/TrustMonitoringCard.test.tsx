import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TrustMonitoringCard } from "./TrustMonitoringCard";
import type { TrustMonitorPolicy } from "@/components/admin/security/types";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return {
    AlertTriangle: MockIcon,
    Loader2: MockIcon,
    Radar: MockIcon,
    ShieldAlert: MockIcon,
    ShieldCheck: MockIcon,
  };
});

jest.mock("@/components/ui/checkbox", () => ({
  Checkbox: ({ checked, onCheckedChange, ...props }: { checked?: boolean; onCheckedChange?: (checked: boolean) => void }) => (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onCheckedChange?.(!checked)}
      {...props}
    />
  ),
}));

const POLICY: TrustMonitorPolicy = {
  enabled: true,
  name_collision_enabled: true,
  silent_observer_enabled: true,
  alert_surface: "admin_ui",
  matrix_public_room_ids: ["!support:matrix.org"],
  matrix_staff_room_id: "!staff:matrix.org",
  silent_observer_window_days: 14,
  early_read_window_seconds: 30,
  minimum_observations: 10,
  minimum_early_read_hits: 8,
  read_to_reply_ratio_threshold: 12,
  evidence_ttl_days: 7,
  aggregate_ttl_days: 30,
  finding_ttl_days: 30,
  updated_at: "2026-03-14T10:00:00Z",
};

describe("TrustMonitoringCard", () => {
  test("renders admin-ui shadow helper text", () => {
    render(
      <TrustMonitoringCard
        policy={POLICY}
        isLoading={false}
        isSaving={false}
        error={null}
        onRetry={() => undefined}
        onEnabledChange={() => undefined}
        onDetectorToggle={() => undefined}
        onAlertSurfaceChange={() => undefined}
      />,
    );

    expect(screen.getByText("Trust Monitoring")).toBeInTheDocument();
    expect(screen.getByText("Admin UI Shadow")).toBeInTheDocument();
    expect(screen.getByText(/Silent Observer is active in shadow mode/i)).toBeInTheDocument();
  });

  test("calls alert surface change when a new destination is selected", async () => {
    const user = userEvent.setup();
    const onAlertSurfaceChange = jest.fn();
    render(
      <TrustMonitoringCard
        policy={POLICY}
        isLoading={false}
        isSaving={false}
        error={null}
        onRetry={() => undefined}
        onEnabledChange={() => undefined}
        onDetectorToggle={() => undefined}
        onAlertSurfaceChange={onAlertSurfaceChange}
      />,
    );

    await user.click(screen.getByRole("radio", { name: "Staff Room" }));
    expect(onAlertSurfaceChange).toHaveBeenCalledWith("staff_room");
  });
});
