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
      }),
    );
  });
});
