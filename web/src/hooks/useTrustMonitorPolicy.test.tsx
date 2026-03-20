import { act, renderHook, waitFor } from "@testing-library/react";
import { makeAuthenticatedRequest } from "@/lib/auth";
import { useTrustMonitorPolicy } from "./useTrustMonitorPolicy";

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

const POLICY = {
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
  updated_at: "2026-03-20T10:00:00Z",
} as const;

describe("useTrustMonitorPolicy", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test("bootstraps client-side when initial policy is missing", async () => {
    mockedMakeAuthenticatedRequest.mockResolvedValue(mockJsonResponse(POLICY));

    const { result } = renderHook(() => useTrustMonitorPolicy(null));

    await waitFor(() => expect(result.current.policy).toEqual(POLICY));
    expect(mockedMakeAuthenticatedRequest).toHaveBeenCalledWith(
      "/admin/security/trust-monitor/policy",
    );
    expect(result.current.isLoading).toBe(false);
    expect(result.current.error).toBeNull();
  });

  test("surfaces an error when bootstrap refresh fails", async () => {
    mockedMakeAuthenticatedRequest.mockResolvedValue(mockJsonResponse({ detail: "nope" }, 503));

    const { result } = renderHook(() => useTrustMonitorPolicy(null));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.policy).toBeNull();
    expect(result.current.error).toBe("Could not load trust-monitor policy.");
  });

  test("updates policy optimistically and keeps server response", async () => {
    mockedMakeAuthenticatedRequest.mockResolvedValueOnce(mockJsonResponse({
      ...POLICY,
      enabled: false,
    }));

    const { result } = renderHook(() => useTrustMonitorPolicy(POLICY));

    await act(async () => {
      await result.current.setEnabled(false);
    });

    expect(mockedMakeAuthenticatedRequest).toHaveBeenCalledWith(
      "/admin/security/trust-monitor/policy",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ enabled: false }),
      }),
    );
    expect(result.current.policy?.enabled).toBe(false);
  });
});
