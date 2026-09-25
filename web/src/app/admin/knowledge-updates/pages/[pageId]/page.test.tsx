import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import InternalSupportGuidePage from "./page";
import { makeAuthenticatedRequest } from "@/lib/auth";

jest.mock("next/navigation", () => ({ useParams: () => ({ pageId: "synthetic-guide" }) }));
jest.mock("@/lib/auth", () => ({ makeAuthenticatedRequest: jest.fn() }));

const request = makeAuthenticatedRequest as jest.MockedFunction<typeof makeAuthenticatedRequest>;

it("allows withdrawing a changed page's dormant approval without publishing it again", async () => {
  const guide = {
    page_id: "synthetic-guide", title: "Synthetic guide", protocol: "bisq_easy",
    status: "reviewed", body: "Internal", projection: null, public: false,
    can_publish: false,
    publication_history: [{ action: "publish", revision: "old", reviewer: "reviewer", created_at: "2026-09-25" }],
  };
  request.mockResolvedValueOnce({ ok: true, json: async () => guide } as Response);
  request.mockResolvedValueOnce({ ok: true } as Response);
  request.mockResolvedValueOnce({ ok: true, json: async () => ({ ...guide, publication_history: [{ ...guide.publication_history[0], action: "revoke" }] }) } as Response);
  render(<InternalSupportGuidePage />);
  const revoke = await screen.findByRole("button", { name: "Make private" });
  expect(revoke).toBeEnabled();
  expect(screen.getByRole("button", { name: "Publish reviewed view" })).toBeDisabled();
  fireEvent.click(revoke);
  await waitFor(() => expect(request).toHaveBeenCalledWith(
    "/admin/knowledge-updates/pages/synthetic-guide/revoke",
    { method: "POST", body: JSON.stringify({}) },
  ));
  await waitFor(() => expect(screen.getByRole("button", { name: "Make private" })).toBeDisabled());
});
