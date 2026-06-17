import { buildSupportWorkReportPath, fetchSupportWorkReport } from "./adminReportsApi";
import { makeAuthenticatedRequest } from "@/lib/auth";

jest.mock("@/lib/auth", () => ({
  makeAuthenticatedRequest: jest.fn(),
}));

const mockedMakeAuthenticatedRequest = makeAuthenticatedRequest as jest.MockedFunction<typeof makeAuthenticatedRequest>;

function jsonResponse(payload: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  } as Response;
}

describe("adminReportsApi", () => {
  beforeEach(() => {
    mockedMakeAuthenticatedRequest.mockReset();
  });

  test("builds a compact support-work report path", () => {
    expect(buildSupportWorkReportPath({
      startDate: "2026-06-01",
      endDate: "2026-06-16",
      reviewer: "support-admin",
      periodLabel: "Cycle 62, blocks 840000-842000",
    })).toBe(
      "/admin/reports/support-work?start_date=2026-06-01&end_date=2026-06-16&reviewer=support-admin&period_label=Cycle+62%2C+blocks+840000-842000",
    );
  });

  test("fetches the support-work report through authenticated admin API", async () => {
    mockedMakeAuthenticatedRequest.mockResolvedValue(jsonResponse({
      summary: { total_reviews: 2 },
    }));

    const payload = await fetchSupportWorkReport({
      startDate: "2026-06-01",
      endDate: "2026-06-16",
    });

    expect(payload.summary.total_reviews).toBe(2);
    expect(mockedMakeAuthenticatedRequest).toHaveBeenCalledWith(
      "/admin/reports/support-work?start_date=2026-06-01&end_date=2026-06-16",
    );
  });

  test("raises a useful error when the report endpoint fails", async () => {
    mockedMakeAuthenticatedRequest.mockResolvedValue(
      jsonResponse({ detail: "reporting unavailable" }, 500),
    );

    await expect(fetchSupportWorkReport({
      startDate: "2026-06-01",
      endDate: "2026-06-16",
    })).rejects.toThrow("reporting unavailable");
  });
});
