import { fireEvent, render, screen } from "@testing-library/react";
import { BatchReviewList } from "./BatchReviewList";

jest.mock("lucide-react", () => ({
  Check: () => <span data-testid="icon-check" />,
  Loader2: () => <span data-testid="icon-loader" />,
  ChevronDown: () => <span data-testid="icon-down" />,
  ChevronUp: () => <span data-testid="icon-up" />,
}));

jest.mock("@/components/ui/card", () => ({
  Card: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  CardContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

jest.mock("@/components/ui/button", () => ({
  Button: ({ children, ...props }: { children: React.ReactNode }) => <button {...props}>{children}</button>,
}));

jest.mock("@/components/ui/badge", () => ({
  Badge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

jest.mock("@/components/ui/checkbox", () => ({
  Checkbox: ({
    checked,
    onCheckedChange,
    ...props
  }: {
    checked?: boolean;
    onCheckedChange?: (value: boolean) => void;
  }) => (
    <input
      type="checkbox"
      checked={checked}
      onChange={() => onCheckedChange?.(!checked)}
      {...props}
    />
  ),
}));

jest.mock("@/lib/utils", () => ({
  cn: (...args: unknown[]) => args.filter(Boolean).join(" "),
}));

describe("BatchReviewList", () => {
  const baseCandidate = {
    id: 7,
    question_text: "What is Bisq Easy?",
    generated_answer: "Bisq Easy is a reputation-based buying flow.",
    final_score: 0.85,
    category: "bisq_easy",
    protocol: "bisq_easy" as const,
    source: "matrix",
  };

  it("renders normalized percentage score when final_score is 0-1", () => {
    render(
      <BatchReviewList
        candidates={[baseCandidate]}
        isLoading={false}
        onBatchApprove={jest.fn()}
        onExpandItem={jest.fn()}
      />
    );

    expect(screen.getByText("85%")).toBeInTheDocument();
  });

  it("treats exact 1 as a 1% score", () => {
    render(
      <BatchReviewList
        candidates={[
          {
            ...baseCandidate,
            final_score: 1,
          },
        ]}
        isLoading={false}
        onBatchApprove={jest.fn()}
        onExpandItem={jest.fn()}
      />,
    );

    expect(screen.getByText("1%")).toBeInTheDocument();
  });

  it("strips generated footer metadata in expanded preview", () => {
    const footerAnswer = [
      "Bisq Easy is a reputation-based buying flow.",
      "",
      "---",
      "",
      "**Answer quality**",
      "- Confidence: 73%",
      "",
      "**Sources**",
      "- [Wiki] Main Page",
    ].join("\n");

    render(
      <BatchReviewList
        candidates={[
          {
            ...baseCandidate,
            generated_answer: footerAnswer,
          },
        ]}
        isLoading={false}
        onBatchApprove={jest.fn()}
        onExpandItem={jest.fn()}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: /what is bisq easy/i }));
    expect(screen.getByText("Bisq Easy is a reputation-based buying flow.")).toBeInTheDocument();
    expect(screen.queryByText(/Answer quality/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/Confidence: 73%/i)).not.toBeInTheDocument();
  });
});
