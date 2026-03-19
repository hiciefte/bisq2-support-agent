import { render, screen } from "@testing-library/react";
import { SecurityAlertsPolicyBar } from "./SecurityAlertsPolicyBar";
import type { TrustMonitorPolicy } from "@/components/admin/security/types";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return {
    Radar: MockIcon,
    ShieldAlert: MockIcon,
    ShieldCheck: MockIcon,
    SlidersHorizontal: MockIcon,
  };
});

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
  test("renders read-only rollout summary and overview link", () => {
    render(<SecurityAlertsPolicyBar policy={POLICY} />);

    expect(screen.getByRole("heading", { name: "Security Alerts" })).toBeInTheDocument();
    expect(screen.getAllByText("Admin UI Shadow")).toHaveLength(2);
    expect(screen.getByText("Rollout mode")).toBeInTheDocument();
    expect(screen.getByText("Enabled detectors")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Configure in Overview" })).toHaveAttribute("href", "/admin/overview");
  });

  test("shows disabled guidance when trust monitoring is off", () => {
    render(<SecurityAlertsPolicyBar policy={{ ...POLICY, enabled: false }} />);

    expect(screen.getByText(/detector pipeline is currently disabled/i)).toBeInTheDocument();
  });
});
