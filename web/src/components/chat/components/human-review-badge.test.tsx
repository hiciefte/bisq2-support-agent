import { render, screen } from "@testing-library/react"

import { HumanReviewBadge } from "./human-review-badge"

jest.mock("lucide-react", () => ({
  Users: () => <svg data-testid="users-icon" />,
}))

describe("HumanReviewBadge", () => {
  test("renders default copy", () => {
    render(<HumanReviewBadge />)

    expect(screen.getByText("Support team notified")).toBeInTheDocument()
  })

  test("renders localized copy when provided", () => {
    render(<HumanReviewBadge label="Support-Team benachrichtigt" />)

    expect(screen.getByText("Support-Team benachrichtigt")).toBeInTheDocument()
  })
})
