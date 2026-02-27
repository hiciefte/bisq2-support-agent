import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChannelAutoresponseCard } from "./ChannelAutoresponseCard";
import type { ChannelAutoresponsePolicy } from "@/components/admin/overview/types";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return {
    Cat: MockIcon,
    Globe2: MockIcon,
    Loader2: MockIcon,
    MessageCircle: MockIcon,
    ShieldAlert: MockIcon,
    ShieldCheck: MockIcon,
  };
});

const POLICIES: ChannelAutoresponsePolicy[] = [
  {
    channel_id: "web",
    enabled: true,
    generation_enabled: true,
    updated_at: "2026-02-25T00:00:00Z",
  },
  {
    channel_id: "bisq2",
    enabled: false,
    generation_enabled: true,
    updated_at: "2026-02-25T00:00:00Z",
  },
  {
    channel_id: "matrix",
    enabled: false,
    generation_enabled: false,
    updated_at: "2026-02-25T00:00:00Z",
  },
];

describe("ChannelAutoresponseCard", () => {
  test("renders channel mode labels from policy state", () => {
    render(
      <ChannelAutoresponseCard
        policies={POLICIES}
        isLoading={false}
        isSavingByChannel={{ web: false, bisq2: false, matrix: false }}
        error={null}
        onModeChange={() => undefined}
        onRetry={() => undefined}
      />,
    );

    expect(screen.getByText("Auto-send mode")).toBeInTheDocument();
    expect(screen.getByText("Review mode")).toBeInTheDocument();
    expect(screen.getByText("AI processing off")).toBeInTheDocument();
  });

  test("calls onModeChange with selected channel mode", async () => {
    const user = userEvent.setup();
    const onModeChange = jest.fn();

    render(
      <ChannelAutoresponseCard
        policies={POLICIES}
        isLoading={false}
        isSavingByChannel={{ web: false, bisq2: false, matrix: false }}
        error={null}
        onModeChange={onModeChange}
        onRetry={() => undefined}
      />,
    );

    const bisq2Row = screen.getByText("Bisq 2 Support Chat").closest("article");
    expect(bisq2Row).not.toBeNull();
    const rowScope = within(bisq2Row as HTMLElement);
    await user.click(rowScope.getByRole("radio", { name: "Auto-send" }));

    expect(onModeChange).toHaveBeenCalledWith("bisq2", "auto");
  });

  test("renders retry action for load error", async () => {
    const user = userEvent.setup();
    const onRetry = jest.fn();

    render(
      <ChannelAutoresponseCard
        policies={POLICIES}
        isLoading={false}
        isSavingByChannel={{ web: false, bisq2: false, matrix: false }}
        error="Could not load policy."
        onModeChange={() => undefined}
        onRetry={onRetry}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
