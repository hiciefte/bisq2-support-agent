import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => (
    <svg className={className} />
  );
  return new Proxy({}, { get: () => MockIcon });
});

import { SecurityFindingDetail } from "@/components/admin/security/SecurityFindingDetail";
import type { TrustFinding } from "@/components/admin/security/types";

function makeFinding(overrides: Partial<TrustFinding> = {}): TrustFinding {
  return {
    id: 99,
    detector_key: "staff_name_collision",
    channel_id: "matrix",
    space_id: "!room:matrix.org",
    suspect_actor_id: "@casaamigis:matrix.org",
    suspect_display_name: "suddenwhipvapor",
    score: 0.95,
    status: "open",
    alert_surface: "admin_ui",
    evidence_summary: {
      detection_method: "user_directory_search",
      matched_staff_name: "suddenwhipvapor",
      user_id: "@casaamigis:matrix.org",
      display_name: "suddenwhipvapor",
      suspect_avatar_url: "mxc://matrix.org/suspectabc",
      staff_avatar_url: "mxc://matrix.org/staffxyz",
      // intentionally extra-noisy field that should land in "Other signals"
      heuristic_version: "v3",
    },
    created_at: "2026-04-10T09:00:00Z",
    updated_at: "2026-04-10T09:30:00Z",
    last_notified_at: null,
    notification_count: 0,
    ...overrides,
  };
}

describe("SecurityFindingDetail", () => {
  it("renders the empty state when no finding is selected", () => {
    render(
      <SecurityFindingDetail finding={null} isMutating={false} onAction={jest.fn()} />,
    );
    expect(screen.getByTestId("security-finding-empty")).toBeInTheDocument();
  });

  it("renders the avatar comparison when both avatars are present", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding()}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    const comparison = screen.getByTestId("avatar-comparison");
    expect(within(comparison).getByText("Suspect")).toBeInTheDocument();
    expect(within(comparison).getByText("Legitimate staff")).toBeInTheDocument();
    const imgs = comparison.querySelectorAll("img");
    expect(imgs).toHaveLength(2);
    // No raw mxc:// URLs visible in the page
    expect(screen.queryByText(/mxc:\/\//)).toBeNull();
  });

  it("structures the 'Why it was flagged' section with humanised labels", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding()}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    expect(screen.getByText("Why it was flagged")).toBeInTheDocument();
    expect(screen.getByText("Detection method")).toBeInTheDocument();
    expect(screen.getByText("User directory search")).toBeInTheDocument();
    expect(screen.getByText("Collides with staff name")).toBeInTheDocument();
    expect(screen.getByText("Alert destination")).toBeInTheDocument();
    expect(screen.getByText("Admin UI only")).toBeInTheDocument();
  });

  it("collapses non-structured signals into the 'Other signals' details element", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding()}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    // Heuristic version is not in the structured set
    expect(screen.getByText(/Other signals \(1\)/)).toBeInTheDocument();
    // matched_staff_name is structured: it must NOT show up under "Other signals"
    const others = screen.getByText(/Other signals/).parentElement!;
    expect(within(others).queryByText("Matched Staff Name")).toBeNull();
  });

  it("calls onAction('resolve') when the primary button is clicked", async () => {
    const onAction = jest.fn();
    render(
      <SecurityFindingDetail
        finding={makeFinding()}
        isMutating={false}
        onAction={onAction}
      />,
    );
    const primary = screen.getByRole("button", { name: /resolve finding/i });
    expect(primary).toHaveAttribute("data-action", "primary");
    await userEvent.click(primary);
    expect(onAction).toHaveBeenCalledWith("resolve");
  });

  it("does not call zero notifications 'Shadow only' for admin_ui findings", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding({
          alert_surface: "admin_ui",
          notification_count: 0,
        })}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    expect(screen.queryByText("Shadow only")).toBeNull();
    expect(screen.getByText("0× notified")).toBeInTheDocument();
  });

  it("exposes the full room ID via a title attribute even when truncated", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding({
          channel_id: "matrix",
          space_id: "!ilodKeOTMMMDTlGhkf:matrix.org",
        })}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    const fullId = "!ilodKeOTMMMDTlGhkf:matrix.org";
    const node = screen.getByTitle(fullId);
    expect(node.textContent).toContain("…");
    expect(node.textContent).toContain(":matrix.org");
  });

  it("renders 'Silent' for findings whose alert_surface is none", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding({
          alert_surface: "none",
          notification_count: 0,
        })}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    expect(screen.getByText("Silent")).toBeInTheDocument();
  });

  it("renders the risk score progress bar with a percentage value", () => {
    render(
      <SecurityFindingDetail
        finding={makeFinding({ score: 0.95 })}
        isMutating={false}
        onAction={jest.fn()}
      />,
    );
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "95");
  });
});
