import { fireEvent, render, screen } from "@testing-library/react";
import { MatrixAvatar } from "@/components/admin/security/MatrixAvatar";

// Radix Avatar only renders <img> after it loads successfully in jsdom; the
// fallback element is rendered eagerly so we assert against initials and the
// img's src attribute (or absence) instead of waiting for load events.

describe("MatrixAvatar", () => {
  it("renders fallback initials when avatarUrl is null", () => {
    render(<MatrixAvatar avatarUrl={null} displayName="Alice Wonder" />);
    expect(screen.getByText("AW")).toBeInTheDocument();
  });

  it("uses '?' when display name is empty", () => {
    render(<MatrixAvatar avatarUrl={null} displayName={null} />);
    expect(screen.getByText("?")).toBeInTheDocument();
  });

  it("renders an img with the proxied src for an mxc URI", () => {
    const { container } = render(
      <MatrixAvatar
        avatarUrl="mxc://matrix.org/abcDEF"
        displayName="Bob"
      />,
    );
    const img = container.querySelector("img");
    expect(img).not.toBeNull();
    expect(img?.getAttribute("src")).toMatch(
      /\/admin\/security\/matrix-media\/matrix\.org\/abcDEF$/,
    );
    expect(img?.getAttribute("alt")).toBe("Bob avatar");
  });

  it("does not render an img element when the URL is unsupported", () => {
    const { container } = render(
      <MatrixAvatar avatarUrl="ftp://example/x" displayName="Bob" />,
    );
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("BO")).toBeInTheDocument();
  });

  it("computes single-name initials", () => {
    render(<MatrixAvatar avatarUrl={null} displayName="suddenwhipvapor" />);
    expect(screen.getByText("SU")).toBeInTheDocument();
  });

  it("retries rendering when the avatar URL changes after a load error", () => {
    const { container, rerender } = render(
      <MatrixAvatar avatarUrl="mxc://matrix.org/firstid" displayName="Bob" />,
    );
    const firstImg = container.querySelector("img");
    expect(firstImg).not.toBeNull();
    // Simulate the first image failing to load
    fireEvent.error(firstImg!);
    expect(container.querySelector("img")).toBeNull();

    rerender(
      <MatrixAvatar avatarUrl="mxc://matrix.org/secondid" displayName="Bob" />,
    );
    const secondImg = container.querySelector("img");
    expect(secondImg).not.toBeNull();
    expect(secondImg?.getAttribute("src")).toContain("secondid");
  });
});
