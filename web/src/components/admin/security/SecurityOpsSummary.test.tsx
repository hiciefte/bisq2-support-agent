import { render, screen } from "@testing-library/react";
import { SecurityOpsSummary } from "./SecurityOpsSummary";
import type { TrustMonitorOpsSnapshot } from "@/components/admin/security/types";

const SNAPSHOT: TrustMonitorOpsSnapshot = {
  monitored_public_rooms: ["!support:matrix.org"],
  staff_room_id: "!staff:matrix.org",
  evidence_events_count: 12,
  actor_aggregates_count: 4,
  findings_count: 2,
  oldest_evidence_age_seconds: 7200,
  oldest_aggregate_age_seconds: 3600,
  oldest_finding_age_seconds: 1800,
  last_retention_run: {
    id: 1,
    created_at: "2026-03-16T10:00:00Z",
    deleted_evidence_events: 3,
    deleted_actor_aggregates: 1,
    deleted_findings: 0,
    deleted_feedback: 0,
    deleted_access_audit: 1,
  },
};

describe("SecurityOpsSummary", () => {
  test("renders monitoring scope and retention diagnostics", () => {
    render(<SecurityOpsSummary ops={SNAPSHOT} />);

    expect(screen.getByText("Monitoring scope")).toBeInTheDocument();
    expect(screen.getByText("Evidence rows")).toBeInTheDocument();
    expect(screen.getByText("Public rooms")).toBeInTheDocument();
    expect(screen.getByText("Retention")).toBeInTheDocument();
    expect(screen.getByText("Evidence deleted")).toBeInTheDocument();
  });
});
