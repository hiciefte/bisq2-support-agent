import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SecurityAlertsPolicyBar } from "./SecurityAlertsPolicyBar";
import type { TrustMonitorPolicy } from "@/components/admin/security/types";

jest.mock("next/link", () => {
  function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  }
  return MockLink;
});

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

describe("SecurityAlertsPolicyBar", () => {
  test("renders rollout badge and quick actions", async () => {
    const user = userEvent.setup();
    const onAlertSurfaceChange = jest.fn();
    render(
      <SecurityAlertsPolicyBar
        policy={POLICY}
        isSaving={false}
        onAlertSurfaceChange={onAlertSurfaceChange}
      />,
    );

    expect(screen.getByText("Admin UI Shadow")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Promote to Staff Room" }));
    expect(onAlertSurfaceChange).toHaveBeenCalledWith("staff_room");
  });
});
