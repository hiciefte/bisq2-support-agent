import Link from "next/link"
import { Metadata } from "next"
import { Card } from "@/components/ui/card"
import { getPrivacyRetentionDays } from "@/lib/privacy-retention"

export const metadata: Metadata = {
  title: "Privacy Policy - Bisq 2 Support Assistant",
  description:
    "Learn how support records, retained knowledge, external copies, and operational integration state are handled.",
}

export const dynamic = "force-dynamic"

export default function PrivacyPolicy() {
  const retentionDays = getPrivacyRetentionDays()

  return (
    <main className="min-h-screen bg-gradient-to-b from-background to-muted/20 p-4 md:p-8">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8">
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            ← Back to Chat
          </Link>
        </div>

        <Card className="p-6 md:p-10">
          <h1 className="text-3xl font-bold mb-2">Privacy Policy</h1>
          <p className="text-sm text-muted-foreground mb-8">Last updated: July 15, 2026</p>

          <div className="space-y-8">
            {/* What We Collect */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">What We Collect</h2>
              <p className="mb-4">
                The support service stores information needed to answer questions, collect feedback,
                and operate connected support channels:
              </p>
              <ul className="list-disc pl-6 space-y-2 mb-4">
                <li>Questions, responses, conversation context, and timestamps</li>
                <li>Feedback ratings and optional feedback explanations</li>
                <li>Escalations and source records used for staff review and training workflows</li>
                <li>
                  For Matrix and Bisq interactions, the display names and user, room, conversation,
                  and message identifiers supplied by those channels
                </li>
                <li>Application and access logs, including request and operational metadata</li>
              </ul>
              <p className="font-semibold mb-2">What the web chat does not require:</p>
              <ul className="list-disc pl-6 space-y-2">
                <li>A user account or login</li>
                <li>Your name, email address, or contact information</li>
              </ul>
            </section>

            {/* How We Use Your Data */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">How We Use Your Data</h2>
              <ul className="list-disc pl-6 space-y-2">
                <li>
                  <strong>Answer and escalate questions:</strong> Provide automated support and
                  route uncertain cases to staff
                </li>
                <li>
                  <strong>Improve responses:</strong> Review feedback and support conversations to
                  improve answer quality
                </li>
                <li>
                  <strong>Generate reviewed knowledge:</strong> Create FAQ candidates for staff
                  approval
                </li>
                <li>
                  <strong>Operate the service:</strong> Prevent duplicate processing, troubleshoot
                  failures, and measure service health
                </li>
              </ul>
            </section>

            {/* Data Retention */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Data Retention</h2>
              <div className="space-y-3">
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Local records deleted on schedule</p>
                  <p className="text-sm">
                    Scheduled retention runs remove local records older than {retentionDays} days
                    from feedback and conversation data, escalations, channel-derived training and
                    review sources, translation caches, timestamped processed-message IDs, legacy
                    rows that are timestamped or otherwise provably aged, backups, and bind-mounted
                    application and access logs. Related message, user, room, and conversation
                    identifiers are deleted or anonymized when a newer linked row still needs a
                    stable key. Active bind-mounted logs are purged on the first retention run or
                    after a scheduling gap when their oldest line cannot be bounded safely.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Legacy records with unknown age need review</p>
                  <p className="text-sm">
                    Malformed or untimestamped legacy or corrupted rows are not automatically
                    deleted because their age cannot be proven. They can remain beyond{" "}
                    {retentionDays} days until an operator safely migrates or removes them.
                    Processed-message IDs written before per-ID timestamps were introduced use the
                    file modification time as a migration boundary and can remain for one additional{" "}
                    {retentionDays}-day window after upgrade.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Container runtime logs need a host policy</p>
                  <p className="text-sm">
                    Container stdout and stderr logs are outside the application job. An operator
                    must install and verify the provided host age-retention policy. Size-based
                    rotation alone does not guarantee deletion on the {retentionDays}-day schedule.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">
                    Reviewed knowledge text and aggregates may remain
                  </p>
                  <p className="text-sm">
                    Staff-reviewed FAQs and support playbooks may be retained indefinitely. They can
                    contain reviewed question and answer text copied from a candidate, but do not
                    retain source user, room, message, reviewer, or conversation identifiers after
                    their retention boundary. Aggregate service and quality metrics may also be
                    retained when they contain no message text or user and channel identifiers.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Operational channel state is rotated</p>
                  <p className="text-sm">
                    The Matrix session file and its local end-to-end encryption crypto store are
                    operational security state, not support conversation records. The whole local
                    Matrix session generation is deleted once it reaches the configured{" "}
                    {retentionDays}-day age, then the integration reauthenticates and creates new
                    local encryption state. Current Matrix and Bisq sync cursors can remain so the
                    connectors know where to resume; processed-message ID history older than{" "}
                    {retentionDays} days is deleted. Rotating local state does not delete original
                    channel messages.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Copies outside this service</p>
                  <p className="text-sm">
                    Local deletion does not remove original messages from Matrix or Bisq, or copies
                    held by configured AI and translation providers. Those copies follow the
                    retention and deletion policies of the external system that holds them.
                  </p>
                </div>
              </div>
            </section>

            {/* Third-Party Services */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">
                External Processing and Source Systems
              </h2>
              <p className="mb-4">
                Answer generation and translation can send question text and relevant conversation
                context to configured external providers. Messages received through Matrix or Bisq
                also remain in those source systems.
              </p>
              <p>
                The local retention job controls only this service&apos;s local stores. External
                providers and channel networks process and retain their own copies under their own
                policies.
              </p>
            </section>

            {/* Security Warning */}
            <section>
              <div className="border-l-4 border-yellow-500 bg-yellow-50 dark:bg-yellow-950/20 p-4 rounded-r-lg">
                <h2 className="text-2xl font-semibold mb-4 text-yellow-900 dark:text-yellow-200">
                  Security Warning
                </h2>
                <p className="mb-3 font-semibold text-yellow-900 dark:text-yellow-200">
                  ⚠️ NEVER share sensitive information with this chatbot:
                </p>
                <ul className="list-disc pl-6 space-y-2 text-yellow-900 dark:text-yellow-200">
                  <li>Private keys or seed phrases</li>
                  <li>Personal identifying information</li>
                  <li>Financial account details</li>
                  <li>Trading partner information</li>
                </ul>
                <p className="mt-4 text-sm text-yellow-800 dark:text-yellow-300">
                  Treat this chatbot like a public forum. We cannot guarantee the security of any
                  information you choose to share.
                </p>
              </div>
            </section>

            {/* Your Rights */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Your Choices and Limits</h2>
              <ul className="list-disc pl-6 space-y-2">
                <li>No account is required to use the web chat</li>
                <li>Do not submit sensitive or identifying information</li>
                <li>
                  The {retentionDays}-day window applies to the local records listed above, not to
                  retained reviewed knowledge, aggregate metrics, current channel sync cursors,
                  legacy rows whose age cannot be proven, the one-time processed-ID migration
                  allowance, or copies held by external systems. Matrix session and encryption
                  states are rotated on that configured cadence
                </li>
              </ul>
            </section>

            {/* Contact */}
            <section className="border-t pt-6">
              <h2 className="text-2xl font-semibold mb-4">Contact</h2>
              <p>
                For privacy questions, contact Bisq support through{" "}
                <a
                  href="https://bisq.network"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-primary hover:underline"
                >
                  official channels
                </a>
                .
              </p>
            </section>
          </div>
        </Card>
      </div>
    </main>
  )
}
