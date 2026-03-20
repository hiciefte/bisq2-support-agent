import { cloneElement, createContext, isValidElement, useContext, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TrustMonitoringCard } from "./TrustMonitoringCard";
import type { TrustMonitorPolicy } from "@/components/admin/security/types";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return {
    AlertTriangle: MockIcon,
    ChevronDown: MockIcon,
    Loader2: MockIcon,
    Radar: MockIcon,
    ShieldAlert: MockIcon,
    ShieldCheck: MockIcon,
  };
});

jest.mock("next/link", () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

jest.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock("@/components/ui/button", () => ({
  Button: ({
    children,
    asChild,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { asChild?: boolean }) => (
    asChild ? <div>{children}</div> : <button {...props}>{children}</button>
  ),
}));

jest.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardHeader: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardTitle: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

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

const ToggleGroupContext = createContext<((value: string) => void) | null>(null);

jest.mock("@/components/ui/toggle-group", () => ({
  ToggleGroup: ({
    children,
    onValueChange,
  }: {
    children: React.ReactNode;
    onValueChange?: (value: string) => void;
  }) => (
    <ToggleGroupContext.Provider value={onValueChange ?? null}>
      <div>{children}</div>
    </ToggleGroupContext.Provider>
  ),
  ToggleGroupItem: ({
    children,
    value,
    "aria-checked": ariaChecked,
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { value?: string }) => {
    const onValueChange = useContext(ToggleGroupContext);
    return (
      <button
        type="button"
        role="radio"
        aria-checked={ariaChecked}
        aria-label={typeof children === "string" ? children : value}
        onClick={() => {
          if (value) {
            onValueChange?.(value);
          }
        }}
      >
        {children}
      </button>
    );
  },
}));

const CollapsibleContext = createContext<{ open: boolean; setOpen: (open: boolean) => void } | null>(null);

jest.mock("@/components/ui/collapsible", () => ({
  Collapsible: ({
    children,
    open,
    onOpenChange,
  }: {
    children: React.ReactNode;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }) => {
    const [internalOpen, setInternalOpen] = useState(Boolean(open));
    const setOpen = (next: boolean) => {
      setInternalOpen(next);
      onOpenChange?.(next);
    };
    return (
      <CollapsibleContext.Provider value={{ open: internalOpen, setOpen }}>
        <div>{children}</div>
      </CollapsibleContext.Provider>
    );
  },
  CollapsibleContent: ({ children }: { children: React.ReactNode }) => {
    const context = useContext(CollapsibleContext);
    return context?.open ? <div>{children}</div> : null;
  },
  CollapsibleTrigger: ({ children }: { children: React.ReactNode }) => {
    const context = useContext(CollapsibleContext);
    if (isValidElement(children)) {
      return cloneElement(children, {
        onClick: () => context?.setOpen(!context.open),
      });
    }
    return <div>{children}</div>;
  },
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

  test("starts collapsed when requested", async () => {
    const user = userEvent.setup();
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
        defaultCollapsed
      />,
    );

    expect(screen.queryByText("Alert destination")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /show controls/i }));

    expect(screen.getByText("Alert destination")).toBeInTheDocument();
  });

  test("does not label missing policy state as off", () => {
    render(
      <TrustMonitoringCard
        policy={null}
        isLoading={true}
        isSaving={false}
        error={null}
        onRetry={() => undefined}
        onEnabledChange={() => undefined}
        onDetectorToggle={() => undefined}
        onAlertSurfaceChange={() => undefined}
      />,
    );

    expect(screen.getByText("Loading")).toBeInTheDocument();
    expect(screen.queryByText("Off")).not.toBeInTheDocument();
    expect(
      screen.getByText("Policy state is still loading."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Policy state is loading. The browser will retry if the server bootstrap missed it."),
    ).toBeInTheDocument();
  });

  test("shows unavailable messaging when policy refresh failed", () => {
    render(
      <TrustMonitoringCard
        policy={null}
        isLoading={false}
        isSaving={false}
        error={"Could not load trust-monitor policy."}
        onRetry={() => undefined}
        onEnabledChange={() => undefined}
        onDetectorToggle={() => undefined}
        onAlertSurfaceChange={() => undefined}
      />,
    );

    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText("Policy state could not be read.")).toBeInTheDocument();
    expect(screen.getByText("Policy state is unavailable. Retry to fetch the latest policy.")).toBeInTheDocument();
  });
});
