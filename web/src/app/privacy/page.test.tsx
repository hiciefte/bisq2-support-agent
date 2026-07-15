import { render, screen } from "@testing-library/react";

import PrivacyPolicy from "./page";

describe("PrivacyPolicy", () => {
    const originalRetentionDays = process.env.DATA_RETENTION_DAYS;

    afterEach(() => {
        if (originalRetentionDays === undefined) {
            delete process.env.DATA_RETENTION_DAYS;
        } else {
            process.env.DATA_RETENTION_DAYS = originalRetentionDays;
        }
    });

    it("describes the configured local retention window and its limits", () => {
        process.env.DATA_RETENTION_DAYS = "14";

        render(<PrivacyPolicy />);

        expect(
            screen.getByText(/Scheduled retention runs remove local records older than 14 days/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/legacy rows that are timestamped or otherwise provably aged/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(
                /Staff-reviewed FAQs and support playbooks may be retained indefinitely/
            )
        ).toBeInTheDocument();
        expect(
            screen.getByText(/contain reviewed question and answer text copied from a candidate/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Aggregate service and quality metrics may also be retained/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Size-based rotation alone does not guarantee deletion/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Malformed or untimestamped legacy or corrupted rows/)
        ).toBeInTheDocument();
        expect(document.body).toHaveTextContent(
            "can remain for one additional 14-day window after upgrade"
        );
        expect(
            screen.getByText(/Active bind-mounted logs are purged on the first retention run/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/whole local Matrix session generation is deleted once it reaches/)
        ).toBeInTheDocument();
        expect(screen.getByText(/configured 14-day age/)).toBeInTheDocument();
        expect(
            screen.getByText(
                /then the integration reauthenticates and creates new local encryption state/
            )
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Current Matrix and Bisq sync cursors can remain/)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Local deletion does not remove original messages from Matrix or Bisq/)
        ).toBeInTheDocument();
    });
});
