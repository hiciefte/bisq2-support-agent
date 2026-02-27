import { buildApiUrl, isAbsoluteHttpUrl } from "./config";

describe("buildApiUrl", () => {
  it("uses exactly one /api prefix when base already contains /api", () => {
    expect(buildApiUrl("/public/faqs", "/api")).toBe("/api/public/faqs");
    expect(buildApiUrl("/public/faqs", "http://nginx:80/api")).toBe("http://nginx:80/api/public/faqs");
  });

  it("adds /api prefix when base points to host root", () => {
    expect(buildApiUrl("/public/faqs", "http://localhost:8000")).toBe("http://localhost:8000/api/public/faqs");
  });

  it("does not double-prefix when path already starts with /api", () => {
    expect(buildApiUrl("/api/public/faqs", "http://localhost:8000")).toBe("http://localhost:8000/api/public/faqs");
    expect(buildApiUrl("/api/public/faqs", "/api")).toBe("/api/public/faqs");
  });
});

describe("isAbsoluteHttpUrl", () => {
  it("detects absolute http and https URLs", () => {
    expect(isAbsoluteHttpUrl("http://localhost:8000")).toBe(true);
    expect(isAbsoluteHttpUrl("https://example.org")).toBe(true);
  });

  it("returns false for relative URLs", () => {
    expect(isAbsoluteHttpUrl("/api")).toBe(false);
    expect(isAbsoluteHttpUrl("api/public/faqs")).toBe(false);
  });
});
