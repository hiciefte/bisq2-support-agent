import { render, screen } from "@testing-library/react"

import { HumanResponseSection } from "./human-response-section"

jest.mock("lucide-react", () => ({
  CheckCircle: () => <svg data-testid="check-icon" />,
}))

jest.mock("./markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
}))

jest.mock("@/components/ui/rating", () => ({
  Rating: ({
    promptText,
  }: {
    promptText?: string
  }) => <div>{promptText}</div>,
}))

describe("HumanResponseSection", () => {
  test("uses localized labels and locale-aware date formatting", () => {
    const dateTimeFormatSpy = jest.spyOn(Intl, "DateTimeFormat")

    render(
      <HumanResponseSection
        response={{
          answer: "Antwort vom Team",
          responded_at: "2026-03-03T12:00:00Z",
        }}
        language="de"
        uiLabels={{
          staff_response_label: "Antwort vom Support",
          staff_helpful_prompt: "War diese Antwort hilfreich?",
          helpful_thank_you: "Danke fur dein Feedback!",
        }}
        onRate={() => {}}
      />,
    )

    expect(screen.getByText("Antwort vom Support")).toBeInTheDocument()
    expect(screen.getByText("War diese Antwort hilfreich?")).toBeInTheDocument()
    expect(dateTimeFormatSpy).toHaveBeenCalledWith(
      "de",
      expect.objectContaining({
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }),
    )

    dateTimeFormatSpy.mockRestore()
  })
})
