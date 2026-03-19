import { act, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { SecurityAlertsClient } from "./SecurityAlertsClient";
import type { SecurityAlertsInitialData } from "@/components/admin/security/types";
import { makeAuthenticatedRequest } from "@/lib/auth";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return new Proxy({}, { get: () => MockIcon });
});

jest.mock("@/lib/auth", () => ({
  makeAuthenticatedRequest: jest.fn(),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: jest.fn() }),
  usePathname: () => "/admin/security/alerts",
  useSearchParams: () => new URLSearchParams(""),
}));

jest.mock("@/components/admin/security/SecurityAlertsPolicyBar", () => ({
  SecurityAlertsPolicyBar: () => <div>policy-bar</div>,
}));

jest.mock("@/components/admin/security/SecurityOpsSummary", () => ({
  SecurityOpsSummary: ({ ops }: { ops: { findings_count: number } | null }) => (
    <div>ops:{ops?.findings_count ?? "none"}</div>
  ),
}));

jest.mock("@/components/admin/security/SecurityAuditTrail", () => ({
  SecurityAuditTrail: ({
    trustAudit,
    chatopsAudit,
  }: {
    trustAudit: Array<unknown>;
    chatopsAudit: Array<unknown>;
  }) => <div>audit:{trustAudit.length}/{chatopsAudit.length}</div>,
}));

jest.mock("@/components/admin/security/SecurityFindingsList", () => ({
  SecurityFindingsList: ({ findings }: { findings: Array<{ id: number }> }) => (
    <div>findings:{findings.map((finding) => finding.id).join(",")}</div>
  ),
}));

jest.mock("@/components/admin/security/SecurityFindingDetail", () => ({
  SecurityFindingDetail: ({ finding }: { finding: { id: number } | null }) => (
    <div>detail:{finding?.id ?? "none"}</div>
  ),
}));

jest.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

jest.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement>) => <button {...props}>{children}</button>,
}));

jest.mock("@/components/ui/select", () => ({
  Select: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectTrigger: ({ children }: { children: ReactNode }) => <button type="button">{children}</button>,
  SelectValue: ({ placeholder }: { placeholder?: string }) => <span>{placeholder}</span>,
  SelectContent: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  SelectItem: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const mockedMakeAuthenticatedRequest = jest.mocked(makeAuthenticatedRequest);

function jsonResponse(body: unknown) {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

describe("SecurityAlertsClient", () => {
  beforeEach(() => {
    mockedMakeAuthenticatedRequest.mockReset();
  });

  test("bootstraps client data when server bootstrap is missing", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string) => {
      switch (endpoint) {
        case "/admin/security/findings":
          return jsonResponse({
            total: 1,
            items: [{
              id: 42,
              detector_key: "staff_name_collision",
              channel_id: "matrix",
              space_id: "!public:matrix.org",
              suspect_actor_id: "@copycat:matrix.org",
              suspect_display_name: "Bisq Moderator",
              score: 0.91,
              status: "open",
              alert_surface: "admin_ui",
              evidence_summary: { collisions: 4 },
              created_at: "2026-03-19T10:00:00Z",
              updated_at: "2026-03-19T10:05:00Z",
              last_notified_at: null,
              notification_count: 0,
            }],
          });
        case "/admin/security/findings/counts":
          return jsonResponse({
            total: 1,
            open: 1,
            resolved: 0,
            false_positive: 0,
            suppressed: 0,
            benign: 0,
          });
        case "/admin/security/trust-monitor/policy":
          return jsonResponse({
            enabled: true,
            name_collision_enabled: true,
            silent_observer_enabled: true,
            alert_surface: "admin_ui",
            matrix_public_room_ids: ["!public:matrix.org"],
            matrix_staff_room_id: "!staff:matrix.org",
            silent_observer_window_days: 14,
            early_read_window_seconds: 30,
            minimum_observations: 10,
            minimum_early_read_hits: 8,
            read_to_reply_ratio_threshold: 12,
            evidence_ttl_days: 7,
            aggregate_ttl_days: 30,
            finding_ttl_days: 30,
            updated_at: "2026-03-19T10:10:00Z",
          });
        case "/admin/security/trust-monitor/ops":
          return jsonResponse({
            monitored_public_rooms: ["!public:matrix.org"],
            staff_room_id: "!staff:matrix.org",
            evidence_events_count: 8,
            actor_aggregates_count: 2,
            findings_count: 1,
            oldest_evidence_age_seconds: 120,
            oldest_aggregate_age_seconds: 320,
            oldest_finding_age_seconds: 600,
            last_retention_run: null,
          });
        case "/admin/security/trust-monitor/access-audit":
          return jsonResponse({ items: [{ id: 1 }] });
        case "/admin/security/chatops/audit":
          return jsonResponse({ items: [{ id: 2 }] });
        default:
          throw new Error(`Unexpected endpoint: ${endpoint}`);
      }
    });

    const initialData: SecurityAlertsInitialData = {
      findings: null,
      counts: null,
      policy: null,
      ops: null,
      trustAudit: null,
      chatopsAudit: null,
    };

    await act(async () => {
      render(<SecurityAlertsClient initialData={initialData} />);
    });

    await waitFor(() => {
      expect(screen.getByText("findings:42")).toBeInTheDocument();
    });

    expect(screen.getByText("ops:1")).toBeInTheDocument();
    expect(screen.getByText("audit:1/1")).toBeInTheDocument();
    expect(screen.getByText("detail:42")).toBeInTheDocument();
  });

  test("shows bootstrap recovery warning when some bootstrap endpoints fail", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string) => {
      switch (endpoint) {
        case "/admin/security/findings":
          return jsonResponse({
            total: 1,
            items: [{
              id: 42,
              detector_key: "staff_name_collision",
              channel_id: "matrix",
              space_id: "!public:matrix.org",
              suspect_actor_id: "@copycat:matrix.org",
              suspect_display_name: "Bisq Moderator",
              score: 0.91,
              status: "open",
              alert_surface: "admin_ui",
              evidence_summary: { collisions: 4 },
              created_at: "2026-03-19T10:00:00Z",
              updated_at: "2026-03-19T10:05:00Z",
              last_notified_at: null,
              notification_count: 0,
            }],
          });
        case "/admin/security/findings/counts":
          return { ok: false } as Response;
        case "/admin/security/trust-monitor/policy":
          return jsonResponse({
            enabled: true,
            name_collision_enabled: true,
            silent_observer_enabled: true,
            alert_surface: "admin_ui",
            matrix_public_room_ids: ["!public:matrix.org"],
            matrix_staff_room_id: "!staff:matrix.org",
            silent_observer_window_days: 14,
            early_read_window_seconds: 30,
            minimum_observations: 10,
            minimum_early_read_hits: 8,
            read_to_reply_ratio_threshold: 12,
            evidence_ttl_days: 7,
            aggregate_ttl_days: 30,
            finding_ttl_days: 30,
            updated_at: "2026-03-19T10:10:00Z",
          });
        case "/admin/security/trust-monitor/ops":
          return jsonResponse({
            monitored_public_rooms: ["!public:matrix.org"],
            staff_room_id: "!staff:matrix.org",
            evidence_events_count: 8,
            actor_aggregates_count: 2,
            findings_count: 1,
            oldest_evidence_age_seconds: 120,
            oldest_aggregate_age_seconds: 320,
            oldest_finding_age_seconds: 600,
            last_retention_run: null,
          });
        case "/admin/security/trust-monitor/access-audit":
          return jsonResponse({ items: [{ id: 1 }] });
        case "/admin/security/chatops/audit":
          return jsonResponse({ items: [{ id: 2 }] });
        default:
          throw new Error(`Unexpected endpoint: ${endpoint}`);
      }
    });

    const initialData: SecurityAlertsInitialData = {
      findings: null,
      counts: null,
      policy: null,
      ops: null,
      trustAudit: null,
      chatopsAudit: null,
    };

    await act(async () => {
      render(<SecurityAlertsClient initialData={initialData} />);
    });

    await waitFor(() => {
      expect(screen.getByText("findings:42")).toBeInTheDocument();
    });

    expect(screen.getByText("Partial bootstrap recovery")).toBeInTheDocument();
    expect(screen.getByText(/Missing: counts/i)).toBeInTheDocument();
  });
});
