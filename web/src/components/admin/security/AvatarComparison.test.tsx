import { render, screen, within } from "@testing-library/react";

jest.mock("lucide-react", () => {
  const MockIcon = ({ className }: { className?: string }) => (
    <svg className={className} />
  );
  return new Proxy({}, { get: () => MockIcon });
});

import { AvatarComparison } from "@/components/admin/security/AvatarComparison";

describe("AvatarComparison", () => {
  it("renders both avatars and labels when all data is present", () => {
    render(
      <AvatarComparison
        suspectAvatarUrl="mxc://matrix.org/suspectabc"
        suspectDisplayName="suddenwhipvapor"
        suspectActorId="@casaamigis:matrix.org"
        staffAvatarUrl="mxc://matrix.org/staffxyz"
        staffDisplayName="suddenwhipvapor"
      />,
    );

    const root = screen.getByTestId("avatar-comparison");
    const imgs = root.querySelectorAll("img");
    expect(imgs).toHaveLength(2);
    expect(imgs[0]?.getAttribute("src")).toContain("/matrix-media/matrix.org/suspectabc");
    expect(imgs[1]?.getAttribute("src")).toContain("/matrix-media/matrix.org/staffxyz");

    expect(within(root).getByText("Suspect")).toBeInTheDocument();
    expect(within(root).getByText("Legitimate staff")).toBeInTheDocument();
    expect(within(root).getByText("@casaamigis:matrix.org")).toBeInTheDocument();
    expect(within(root).getByText("Verified")).toBeInTheDocument();
  });

  it("falls back to initials when no avatar URLs are supplied", () => {
    render(
      <AvatarComparison
        suspectAvatarUrl={null}
        suspectDisplayName="alice"
        suspectActorId="@bad:matrix.org"
        staffAvatarUrl={null}
        staffDisplayName="alice"
      />,
    );

    const root = screen.getByTestId("avatar-comparison");
    expect(root.querySelectorAll("img")).toHaveLength(0);
    // Both fallbacks render the same initials text
    expect(within(root).getAllByText("AL")).toHaveLength(2);
  });

  it("handles a mixed case where only the suspect avatar is missing", () => {
    render(
      <AvatarComparison
        suspectAvatarUrl={null}
        suspectDisplayName="alice"
        suspectActorId="@bad:matrix.org"
        staffAvatarUrl="mxc://matrix.org/alicepic"
        staffDisplayName="alice"
      />,
    );

    const root = screen.getByTestId("avatar-comparison");
    const imgs = root.querySelectorAll("img");
    expect(imgs).toHaveLength(1);
    expect(imgs[0]?.getAttribute("src")).toContain(
      "/matrix-media/matrix.org/alicepic",
    );
  });

  it("shows 'Unknown' when display name is missing", () => {
    render(
      <AvatarComparison
        suspectAvatarUrl={null}
        suspectDisplayName={null}
        suspectActorId="@x:matrix.org"
        staffAvatarUrl={null}
        staffDisplayName=""
      />,
    );

    const root = screen.getByTestId("avatar-comparison");
    expect(within(root).getAllByText("Unknown")).toHaveLength(2);
  });
});
