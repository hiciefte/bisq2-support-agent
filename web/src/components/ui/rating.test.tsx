import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { Rating } from "./rating";

jest.mock("lucide-react", () => ({
  ThumbsUp: () => <svg data-testid="thumbs-up" />,
  ThumbsDown: () => <svg data-testid="thumbs-down" />,
}));

describe("Rating", () => {
  it("keeps rating retryable when async submit fails", async () => {
    const onRate = jest.fn().mockResolvedValue(false);

    render(<Rating onRate={onRate} />);

    const helpful = screen.getByRole("button", { name: /rate as helpful/i });
    fireEvent.click(helpful);

    expect(await screen.findByText("Could not save feedback. Try again.")).toBeInTheDocument();
    await waitFor(() => expect(helpful).not.toBeDisabled());
    expect(screen.queryByText("Thank you for your feedback!")).not.toBeInTheDocument();
  });

  it("locks in rating after async submit succeeds", async () => {
    const onRate = jest.fn().mockResolvedValue(true);

    render(<Rating onRate={onRate} />);

    const helpful = screen.getByRole("button", { name: /rate as helpful/i });
    fireEvent.click(helpful);

    expect(await screen.findByText("Thank you for your feedback!")).toBeInTheDocument();
    expect(helpful).toBeDisabled();
  });

  it("hydrates an existing rating", () => {
    render(<Rating onRate={jest.fn()} initialRating={1} />);

    expect(screen.getByText("Thank you for your feedback!")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rate as helpful/i })).toBeDisabled();
  });

  it("hydrates an existing unhelpful rating", () => {
    render(<Rating onRate={jest.fn()} initialRating={0} />);

    expect(screen.getByText("Thank you for your feedback!")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rate as unhelpful/i })).toBeDisabled();
  });

  it("treats null initial rating as unrated", () => {
    render(<Rating onRate={jest.fn()} initialRating={null} />);

    expect(screen.getByText("Was this response helpful?")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /rate as helpful/i })).not.toBeDisabled();
    expect(screen.getByRole("button", { name: /rate as unhelpful/i })).not.toBeDisabled();
  });
});
