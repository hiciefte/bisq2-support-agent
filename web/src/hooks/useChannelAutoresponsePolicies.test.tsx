import { act, renderHook, waitFor } from "@testing-library/react";
import { makeAuthenticatedRequest } from "@/lib/auth";
import {
  useChannelAutoresponsePolicies,
  type ChannelAutoresponsePolicy,
} from "./useChannelAutoresponsePolicies";

jest.mock("@/lib/auth", () => ({
  makeAuthenticatedRequest: jest.fn(),
}));

const mockedMakeAuthenticatedRequest = makeAuthenticatedRequest as jest.MockedFunction<typeof makeAuthenticatedRequest>;

function mockJsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

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
    enabled: false,
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

describe("useChannelAutoresponsePolicies", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("maps channel mode to policy payload", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string, options?: RequestInit) => {
      if (endpoint === "/admin/channels/autoresponse" && !options?.method) {
        return mockJsonResponse(POLICIES);
      }
      if (endpoint === "/admin/channels/autoresponse/bisq2") {
        return mockJsonResponse({
          ...POLICIES[1],
          enabled: true,
          generation_enabled: true,
          ai_response_mode: "autonomous",
        });
      }
      return mockJsonResponse({ detail: "unexpected call" }, 500);
    });

    const { result } = renderHook(() => useChannelAutoresponsePolicies(POLICIES));
    await waitFor(() => expect(result.current.policies.length).toBe(3));

    await act(async () => {
      await result.current.setChannelMode("bisq2", "auto");
    });

    const updateCall = mockedMakeAuthenticatedRequest.mock.calls.find(
      ([endpoint]) => endpoint === "/admin/channels/autoresponse/bisq2",
    );
    expect(updateCall).toBeDefined();
    expect(updateCall?.[1]?.method).toBe("PUT");
    expect(updateCall?.[1]?.body).toBe(
      JSON.stringify({
        generation_enabled: true,
        enabled: true,
        ai_response_mode: "autonomous",
      }),
    );
  });

  test("forces autosend off when mode is off", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string, options?: RequestInit) => {
      if (endpoint === "/admin/channels/autoresponse" && !options?.method) {
        return mockJsonResponse(POLICIES);
      }
      if (endpoint === "/admin/channels/autoresponse/matrix") {
        return mockJsonResponse({
          ...POLICIES[2],
          enabled: false,
          generation_enabled: false,
          ai_response_mode: "autonomous",
        });
      }
      return mockJsonResponse({ detail: "unexpected call" }, 500);
    });

    const { result } = renderHook(() => useChannelAutoresponsePolicies(POLICIES));
    await waitFor(() => expect(result.current.policies.length).toBe(3));

    await act(async () => {
      await result.current.setChannelMode("matrix", "off");
    });

    const updateCall = mockedMakeAuthenticatedRequest.mock.calls.find(
      ([endpoint]) => endpoint === "/admin/channels/autoresponse/matrix",
    );
    expect(updateCall?.[1]?.body).toBe(
      JSON.stringify({
        generation_enabled: false,
        enabled: false,
        ai_response_mode: "autonomous",
      }),
    );
  });

  test("updates escalation notification routing channel", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string, options?: RequestInit) => {
      if (endpoint === "/admin/channels/autoresponse" && !options?.method) {
        return mockJsonResponse(POLICIES);
      }
      if (endpoint === "/admin/channels/autoresponse/matrix") {
        return mockJsonResponse({
          ...POLICIES[2],
          escalation_notification_channel: "none",
        });
      }
      return mockJsonResponse({ detail: "unexpected call" }, 500);
    });

    const { result } = renderHook(() => useChannelAutoresponsePolicies(POLICIES));
    await waitFor(() => expect(result.current.policies.length).toBe(3));

    await act(async () => {
      await result.current.setEscalationNotificationChannel("matrix", "none");
    });

    const updateCall = mockedMakeAuthenticatedRequest.mock.calls.find(
      ([endpoint]) => endpoint === "/admin/channels/autoresponse/matrix",
    );
    expect(updateCall?.[1]?.body).toBe(
      JSON.stringify({
        escalation_notification_channel: "none",
      }),
    );
  });

  test("updates acknowledgment mode", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string, options?: RequestInit) => {
      if (endpoint === "/admin/channels/autoresponse" && !options?.method) {
        return mockJsonResponse(POLICIES);
      }
      if (endpoint === "/admin/channels/autoresponse/matrix") {
        return mockJsonResponse({
          ...POLICIES[2],
          acknowledgment_mode: "message",
        });
      }
      return mockJsonResponse({ detail: "unexpected call" }, 500);
    });

    const { result } = renderHook(() => useChannelAutoresponsePolicies(POLICIES));
    await waitFor(() => expect(result.current.policies.length).toBe(3));

    await act(async () => {
      await result.current.setAcknowledgmentMode("matrix", "message");
    });

    const updateCall = mockedMakeAuthenticatedRequest.mock.calls.find(
      ([endpoint]) => endpoint === "/admin/channels/autoresponse/matrix",
    );
    expect(updateCall?.[1]?.body).toBe(
      JSON.stringify({
        acknowledgment_mode: "message",
      }),
    );
  });

  test("updates acknowledgment message template", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string, options?: RequestInit) => {
      if (endpoint === "/admin/channels/autoresponse" && !options?.method) {
        return mockJsonResponse(POLICIES);
      }
      if (endpoint === "/admin/channels/autoresponse/bisq2") {
        return mockJsonResponse({
          ...POLICIES[1],
          acknowledgment_message_template: "Support saw your message and will reply soon.",
        });
      }
      return mockJsonResponse({ detail: "unexpected call" }, 500);
    });

    const { result } = renderHook(() => useChannelAutoresponsePolicies(POLICIES));
    await waitFor(() => expect(result.current.policies.length).toBe(3));

    await act(async () => {
      await result.current.setAcknowledgmentMessageTemplate(
        "bisq2",
        "Support saw your message and will reply soon.",
      );
    });

    const updateCall = mockedMakeAuthenticatedRequest.mock.calls.find(
      ([endpoint]) => endpoint === "/admin/channels/autoresponse/bisq2",
    );
    expect(updateCall?.[1]?.body).toBe(
      JSON.stringify({
        acknowledgment_message_template: "Support saw your message and will reply soon.",
      }),
    );
  });

  test("updates escalation user notice mode", async () => {
    mockedMakeAuthenticatedRequest.mockImplementation(async (endpoint: string, options?: RequestInit) => {
      if (endpoint === "/admin/channels/autoresponse" && !options?.method) {
        return mockJsonResponse(POLICIES);
      }
      if (endpoint === "/admin/channels/autoresponse/matrix") {
        return mockJsonResponse({
          ...POLICIES[2],
          escalation_user_notice_mode: "none",
        });
      }
      return mockJsonResponse({ detail: "unexpected call" }, 500);
    });

    const { result } = renderHook(() => useChannelAutoresponsePolicies(POLICIES));
    await waitFor(() => expect(result.current.policies.length).toBe(3));

    await act(async () => {
      await result.current.setEscalationUserNoticeMode("matrix", "none");
    });

    const updateCall = mockedMakeAuthenticatedRequest.mock.calls.find(
      ([endpoint]) => endpoint === "/admin/channels/autoresponse/matrix",
    );
    expect(updateCall?.[1]?.body).toBe(
      JSON.stringify({
        escalation_user_notice_mode: "none",
      }),
    );
  });
});
