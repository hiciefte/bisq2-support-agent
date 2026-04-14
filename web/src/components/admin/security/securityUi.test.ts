import { formatRoomIdentifier } from "@/components/admin/security/securityUi";

describe("formatRoomIdentifier", () => {
  it("renders a friendly label for proactive scans", () => {
    expect(formatRoomIdentifier("proactive_scan")).toBe("proactive scan");
  });

  it("falls back when missing", () => {
    expect(formatRoomIdentifier(null)).toBe("(unknown room)");
    expect(formatRoomIdentifier(undefined)).toBe("(unknown room)");
    expect(formatRoomIdentifier("")).toBe("(unknown room)");
  });

  it("truncates long Matrix room IDs but keeps the homeserver", () => {
    expect(formatRoomIdentifier("!ilodKeOTMMMDTlGhkf:matrix.org")).toBe(
      "!ilodKeOT…:matrix.org",
    );
  });

  it("leaves short room IDs alone", () => {
    expect(formatRoomIdentifier("!short:matrix.org")).toBe("!short:matrix.org");
  });

  it("passes non-room strings through unchanged", () => {
    expect(formatRoomIdentifier("custom-space")).toBe("custom-space");
  });
});
