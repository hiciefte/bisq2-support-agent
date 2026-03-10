import type { ComponentProps } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChannelAutoresponseCard } from "./ChannelAutoresponseCard";
import type { ChannelAutoresponsePolicy } from "@/components/admin/overview/types";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => <svg className={className} />;
  return {
    Cat: MockIcon,
    Globe2: MockIcon,
    Info: MockIcon,
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
    ai_response_mode: "autonomous",
    hitl_approval_timeout_seconds: 3600,
    draft_assistant_enabled: false,
    knowledge_amplifier_enabled: false,
    staff_assist_surface: "none",
    first_response_delay_seconds: 0,
    staff_active_cooldown_seconds: 0,
    max_proactive_ai_replies_per_question: 1,
    public_escalation_notice_enabled: true,
    acknowledgment_mode: "none",
    acknowledgment_reaction_key: "👀",
    acknowledgment_message_template:
      "Thanks for your question. A team member or our assistant will respond shortly.",
    group_clarification_immediate: true,
    escalation_user_notice_template:
      "This question needs a team member's attention. Someone will follow up.",
    escalation_user_notice_mode: "message",
    dispatch_failure_message_template:
      "We were unable to process your question automatically. A team member will follow up.",
    escalation_notification_channel: "public_room",
    explicit_invocation_enabled: false,
    explicit_invocation_user_rate_limit_per_5m: 0,
    explicit_invocation_room_rate_limit_per_min: 0,
    community_response_cancels_ai: false,
    community_substantive_min_chars: 20,
    staff_presence_aware_delay: false,
    min_delay_no_staff_seconds: 0,
    mandatory_escalation_topics: [],
    timer_jitter_max_seconds: 0,
    updated_at: "2026-02-25T00:00:00Z",
  },
  {
    channel_id: "bisq2",
    enabled: true,
    generation_enabled: true,
    ai_response_mode: "hitl",
    hitl_approval_timeout_seconds: 3600,
    draft_assistant_enabled: true,
    knowledge_amplifier_enabled: true,
    staff_assist_surface: "admin_ui",
    first_response_delay_seconds: 300,
    staff_active_cooldown_seconds: 300,
    max_proactive_ai_replies_per_question: 1,
    public_escalation_notice_enabled: false,
    acknowledgment_mode: "message",
    acknowledgment_reaction_key: "👀",
    acknowledgment_message_template:
      "Thanks for your question. A team member or our assistant will respond shortly.",
    group_clarification_immediate: false,
    escalation_user_notice_template:
      "This question needs a team member's attention. Someone will follow up.",
    escalation_user_notice_mode: "message",
    dispatch_failure_message_template:
      "We were unable to process your question automatically. A team member will follow up.",
    escalation_notification_channel: "staff_room",
    explicit_invocation_enabled: true,
    explicit_invocation_user_rate_limit_per_5m: 3,
    explicit_invocation_room_rate_limit_per_min: 6,
    community_response_cancels_ai: true,
    community_substantive_min_chars: 20,
    staff_presence_aware_delay: true,
    min_delay_no_staff_seconds: 300,
    mandatory_escalation_topics: [],
    timer_jitter_max_seconds: 30,
    updated_at: "2026-02-25T00:00:00Z",
  },
  {
    channel_id: "matrix",
    enabled: false,
    generation_enabled: false,
    ai_response_mode: "autonomous",
    hitl_approval_timeout_seconds: 3600,
    draft_assistant_enabled: true,
    knowledge_amplifier_enabled: true,
    staff_assist_surface: "both",
    first_response_delay_seconds: 300,
    staff_active_cooldown_seconds: 300,
    max_proactive_ai_replies_per_question: 1,
    public_escalation_notice_enabled: false,
    acknowledgment_mode: "reaction",
    acknowledgment_reaction_key: "👀",
    acknowledgment_message_template:
      "Thanks for your question. A team member or our assistant will respond shortly.",
    group_clarification_immediate: false,
    escalation_user_notice_template:
      "This question needs a team member's attention. Someone will follow up.",
    escalation_user_notice_mode: "message",
    dispatch_failure_message_template:
      "We were unable to process your question automatically. A team member will follow up.",
    escalation_notification_channel: "staff_room",
    explicit_invocation_enabled: true,
    explicit_invocation_user_rate_limit_per_5m: 3,
    explicit_invocation_room_rate_limit_per_min: 6,
    community_response_cancels_ai: true,
    community_substantive_min_chars: 20,
    staff_presence_aware_delay: true,
    min_delay_no_staff_seconds: 300,
    mandatory_escalation_topics: [],
    timer_jitter_max_seconds: 30,
    updated_at: "2026-02-25T00:00:00Z",
  },
];

type CardProps = ComponentProps<typeof ChannelAutoresponseCard>;

function renderCard(overrides: Partial<CardProps> = {}) {
  const props: CardProps = {
    policies: POLICIES,
    isLoading: false,
    isSavingByChannel: { web: false, bisq2: false, matrix: false },
    error: null,
    onModeChange: () => undefined,
    onEscalationRouteChange: () => undefined,
    onAcknowledgmentModeChange: () => undefined,
    onAcknowledgmentReactionKeyChange: () => undefined,
    onAcknowledgmentMessageTemplateChange: () => undefined,
    onEscalationUserNoticeModeChange: () => undefined,
    onRetry: () => undefined,
    ...overrides,
  };
  return render(<ChannelAutoresponseCard {...props} />);
}

function sectionScope(row: HTMLElement, heading: string) {
  const headingElement = within(row).getByText(heading);
  const section = headingElement.closest("div")?.parentElement;
  expect(section).not.toBeNull();
  return within(section as HTMLElement);
}

describe("ChannelAutoresponseCard", () => {
  test("renders channel mode labels from policy state", () => {
    renderCard();

    expect(screen.getByText("Auto-send mode")).toBeInTheDocument();
    expect(screen.getAllByText("Review (HITL)").length).toBeGreaterThan(0);
    expect(screen.getByText("AI processing off")).toBeInTheDocument();
  });

  test("calls onModeChange with selected channel mode", async () => {
    const user = userEvent.setup();
    const onModeChange = jest.fn();
    renderCard({ onModeChange });

    const bisq2Row = screen.getByText("Bisq 2 Support Chat").closest("article");
    expect(bisq2Row).not.toBeNull();
    const rowScope = within(bisq2Row as HTMLElement);
    await user.click(rowScope.getByRole("radio", { name: "Auto-send" }));

    expect(onModeChange).toHaveBeenCalledWith("bisq2", "auto");
  });

  test("renders retry action for load error", async () => {
    const user = userEvent.setup();
    const onRetry = jest.fn();
    renderCard({ error: "Could not load policy.", onRetry });

    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  test("calls onEscalationRouteChange for visible routing options", async () => {
    const user = userEvent.setup();
    const onEscalationRouteChange = jest.fn();
    renderCard({ onEscalationRouteChange });

    const matrixRow = screen.getByText("Matrix Support Rooms").closest("article");
    expect(matrixRow).not.toBeNull();
    const rowScope = within(matrixRow as HTMLElement);
    await user.click(rowScope.getByRole("radio", { name: "User Room Only" }));

    expect(onEscalationRouteChange).toHaveBeenCalledWith("matrix", "none");
  });

  test("uses a consistent internal notice target order across all channels", () => {
    renderCard();

    const expectedOrder = ["Staff Room", "User Room Only", "Public Room"];
    const channelLabels = ["Web Chat", "Bisq 2 Support Chat", "Matrix Support Rooms"];

    for (const channelLabel of channelLabels) {
      const row = screen.getByText(channelLabel).closest("article");
      expect(row).not.toBeNull();
      const rowScope = within(row as HTMLElement);
      const orderedOptions = rowScope
        .getAllByRole("radio")
        .filter((radio) => expectedOrder.includes(radio.textContent ?? ""))
        .map((radio) => radio.textContent?.trim());

      expect(orderedOptions).toEqual(expectedOrder);
    }
  });

  test("renders explicit selected behavior text for internal notice target", () => {
    renderCard();

    expect(screen.getAllByText(/Internal Notice Target/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/Selected:/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/internal escalation notice/i).length).toBeGreaterThan(0);
  });

  test("keeps web internal notice targets visible but disabled with explanatory tooltip", async () => {
    const user = userEvent.setup();
    const onEscalationRouteChange = jest.fn();
    renderCard({ onEscalationRouteChange });

    const webRow = screen.getByText("Web Chat").closest("article");
    expect(webRow).not.toBeNull();
    const rowScope = within(webRow as HTMLElement);

    const publicRoomOption = rowScope.getByRole("radio", { name: "Public Room" });
    const userRoomOnlyOption = rowScope.getByRole("radio", { name: "User Room Only" });
    const staffRoomOption = rowScope.getByRole("radio", { name: "Staff Room" });

    expect(publicRoomOption).toBeDisabled();
    expect(userRoomOnlyOption).toBeDisabled();
    expect(staffRoomOption).toBeDisabled();

    await user.hover(
      rowScope.getByRole("button", { name: "Why web routing targets are disabled" }),
    );
    const tooltipMatches = await screen.findAllByText(
      /does not route escalation notices to separate rooms yet/i,
    );
    expect(tooltipMatches.length).toBeGreaterThan(0);

    await user.click(userRoomOnlyOption);
    expect(onEscalationRouteChange).not.toHaveBeenCalled();
  });

  test("uses a consistent acknowledgment mode order across all channels", () => {
    renderCard();

    const expectedOrder = ["None", "Reaction", "Message"];
    const channelLabels = ["Web Chat", "Bisq 2 Support Chat", "Matrix Support Rooms"];

    for (const channelLabel of channelLabels) {
      const row = screen.getByText(channelLabel).closest("article");
      expect(row).not.toBeNull();
      const ackScope = sectionScope(row as HTMLElement, "Immediate Receipt Acknowledgment");
      const orderedOptions = ackScope
        .getAllByRole("radio")
        .filter((radio) => expectedOrder.includes(radio.textContent ?? ""))
        .map((radio) => radio.textContent?.trim());

      expect(orderedOptions).toEqual(expectedOrder);
    }
  });

  test("keeps web reaction acknowledgment visible but disabled with tooltip", async () => {
    const user = userEvent.setup();
    const onAcknowledgmentModeChange = jest.fn();
    renderCard({ onAcknowledgmentModeChange });

    const webRow = screen.getByText("Web Chat").closest("article");
    expect(webRow).not.toBeNull();
    const ackScope = sectionScope(webRow as HTMLElement, "Immediate Receipt Acknowledgment");

    const reactionOption = ackScope.getByRole("radio", { name: "Reaction" });
    expect(reactionOption).toBeDisabled();

    await user.hover(
      ackScope.getByRole("button", { name: "Why acknowledgment reaction is disabled for Web Chat" }),
    );
    const tooltipMatches = await screen.findAllByText(
      /Web Chat currently does not support emoji reactions/i,
    );
    expect(tooltipMatches.length).toBeGreaterThan(0);

    await user.click(reactionOption);
    expect(onAcknowledgmentModeChange).not.toHaveBeenCalled();
  });

  test("calls onAcknowledgmentModeChange for supported channel option", async () => {
    const user = userEvent.setup();
    const onAcknowledgmentModeChange = jest.fn();
    renderCard({ onAcknowledgmentModeChange });

    const matrixRow = screen.getByText("Matrix Support Rooms").closest("article");
    expect(matrixRow).not.toBeNull();
    const ackScope = sectionScope(matrixRow as HTMLElement, "Immediate Receipt Acknowledgment");

    await user.click(ackScope.getByRole("radio", { name: "Message" }));
    expect(onAcknowledgmentModeChange).toHaveBeenCalledWith("matrix", "message");
  });

  test("calls onEscalationUserNoticeModeChange for supported channel option", async () => {
    const user = userEvent.setup();
    const onEscalationUserNoticeModeChange = jest.fn();
    renderCard({ onEscalationUserNoticeModeChange });

    const matrixRow = screen.getByText("Matrix Support Rooms").closest("article");
    expect(matrixRow).not.toBeNull();
    const escalationScope = sectionScope(matrixRow as HTMLElement, "User Room Escalation Notice");

    await user.click(escalationScope.getByRole("radio", { name: "Off" }));
    expect(onEscalationUserNoticeModeChange).toHaveBeenCalledWith("matrix", "none");
  });

  test("persists reaction key on blur for reaction mode", async () => {
    const user = userEvent.setup();
    const onAcknowledgmentReactionKeyChange = jest.fn();
    renderCard({ onAcknowledgmentReactionKeyChange });

    const matrixRow = screen.getByText("Matrix Support Rooms").closest("article");
    expect(matrixRow).not.toBeNull();
    const rowScope = within(matrixRow as HTMLElement);

    const reactionInput = rowScope.getByRole("textbox", { name: "Reaction emoji" });
    await user.clear(reactionInput);
    await user.type(reactionInput, "✅");
    await user.tab();

    expect(onAcknowledgmentReactionKeyChange).toHaveBeenCalledWith("matrix", "✅");
  });

  test("persists acknowledgment message template on blur for message mode", async () => {
    const user = userEvent.setup();
    const onAcknowledgmentMessageTemplateChange = jest.fn();
    renderCard({ onAcknowledgmentMessageTemplateChange });

    const bisq2Row = screen.getByText("Bisq 2 Support Chat").closest("article");
    expect(bisq2Row).not.toBeNull();
    const rowScope = within(bisq2Row as HTMLElement);

    const templateInput = rowScope.getByRole("textbox", { name: "Acknowledgment message" });
    await user.clear(templateInput);
    await user.type(templateInput, "We saw this. A support member will reply shortly.");
    await user.tab();

    expect(onAcknowledgmentMessageTemplateChange).toHaveBeenCalledWith(
      "bisq2",
      "We saw this. A support member will reply shortly.",
    );
  });
});
