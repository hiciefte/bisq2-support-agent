import { parseMxcUri, resolveAvatarUrl } from "@/lib/matrix-media";

describe("parseMxcUri", () => {
  it("parses a well-formed mxc URI", () => {
    expect(parseMxcUri("mxc://matrix.org/abcDEF123")).toEqual({
      serverName: "matrix.org",
      mediaId: "abcDEF123",
    });
  });

  it("returns null for null/undefined/empty", () => {
    expect(parseMxcUri(null)).toBeNull();
    expect(parseMxcUri(undefined)).toBeNull();
    expect(parseMxcUri("")).toBeNull();
  });

  it("returns null for non-mxc URLs", () => {
    expect(parseMxcUri("https://matrix.org/abc")).toBeNull();
    expect(parseMxcUri("abc")).toBeNull();
  });

  it("returns null when the media id is missing", () => {
    expect(parseMxcUri("mxc://matrix.org/")).toBeNull();
    expect(parseMxcUri("mxc://matrix.org")).toBeNull();
  });

  it("returns null when the server is missing", () => {
    expect(parseMxcUri("mxc:///abc")).toBeNull();
  });

  it("rejects nested paths", () => {
    expect(parseMxcUri("mxc://matrix.org/foo/bar")).toBeNull();
  });
});

describe("resolveAvatarUrl", () => {
  it("converts mxc URIs to a backend proxy path", () => {
    const url = resolveAvatarUrl("mxc://matrix.org/abcDEF123");
    expect(url).toMatch(
      /\/admin\/security\/matrix-media\/matrix\.org\/abcDEF123$/,
    );
  });

  it("escapes special characters in segments", () => {
    const url = resolveAvatarUrl("mxc://matrix.org/abc%foo");
    // "%" must be percent-encoded by encodeURIComponent
    expect(url).toContain("abc%25foo");
  });

  it("passes through https URLs unchanged", () => {
    expect(resolveAvatarUrl("https://example.com/a.png")).toBe(
      "https://example.com/a.png",
    );
  });

  it("returns null for unsupported schemes and empty input", () => {
    expect(resolveAvatarUrl(null)).toBeNull();
    expect(resolveAvatarUrl("")).toBeNull();
    expect(resolveAvatarUrl("ftp://x/y")).toBeNull();
  });
});
