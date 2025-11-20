import Link from "next/link"
import { Card } from "@/components/ui/card"

export default function TermsOfService() {
  return (
    <main className="min-h-screen bg-gradient-to-b from-background to-muted/20 p-4 md:p-8">
      <div className="mx-auto max-w-4xl">
        <div className="mb-8">
          <Link
            href="/"
            className="text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            &larr; Back to Chat
          </Link>
        </div>

        <Card className="p-6 md:p-10">
          <h1 className="text-3xl font-bold mb-2">Terms of Service &amp; Disclaimer</h1>
          <p className="text-sm text-muted-foreground mb-8">Last updated: November 20, 2025</p>

          <div className="space-y-8">
            {/* Unofficial Community Service */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Unofficial Community Service</h2>
              <div className="border-l-4 border-yellow-500 bg-yellow-50 dark:bg-yellow-950/20 p-4 rounded-r-lg">
                <p className="text-yellow-900 dark:text-yellow-200">
                  This support bot is an <strong>unofficial community contribution</strong> to the Bisq ecosystem.
                  It is <strong>NOT</strong> operated by, affiliated with, or endorsed by any official Bisq entity.
                </p>
              </div>
            </section>

            {/* No Warranty or Liability */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">No Warranty or Liability</h2>
              <div className="space-y-3">
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">No Warranty of Accuracy</p>
                  <p className="text-sm text-muted-foreground">
                    Information provided may be incomplete, outdated, or incorrect.
                    We make no guarantees about the accuracy or completeness of any information.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">No Liability for Losses</p>
                  <p className="text-sm text-muted-foreground">
                    We are not responsible for any financial losses, trading errors, technical issues,
                    or any other damages resulting from using this bot or acting on its suggestions.
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">No Confidential Relationship</p>
                  <p className="text-sm text-muted-foreground">
                    This is a public community resource. No fiduciary, advisory, or confidential
                    relationship is created between you and the bot maintainer(s).
                  </p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Not Financial Advice</p>
                  <p className="text-sm text-muted-foreground">
                    Nothing provided by this bot constitutes financial, legal, tax, or investment advice.
                    Always consult qualified professionals for such matters.
                  </p>
                </div>
              </div>
            </section>

            {/* Use at Your Own Risk */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Use at Your Own Risk</h2>
              <ul className="list-disc pl-6 space-y-2">
                <li>
                  <strong>Verify all information</strong> through official Bisq documentation at{" "}
                  <a
                    href="https://bisq.wiki"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    bisq.wiki
                  </a>
                </li>
                <li>
                  <strong>Never make trading decisions</strong> based solely on this bot&apos;s responses
                </li>
                <li>
                  <strong>Always consult official resources</strong> for critical operations like dispute resolution
                </li>
                <li>
                  <strong>You are solely responsible</strong> for your trading decisions and actions
                </li>
              </ul>
            </section>

            {/* Sensitive Information Warning */}
            <section>
              <div className="border-l-4 border-red-500 bg-red-50 dark:bg-red-950/20 p-4 rounded-r-lg">
                <h2 className="text-2xl font-semibold mb-4 text-red-900 dark:text-red-200">
                  No Sensitive Data
                </h2>
                <p className="mb-3 font-semibold text-red-900 dark:text-red-200">
                  Do NOT share the following with this bot:
                </p>
                <ul className="list-disc pl-6 space-y-2 text-red-900 dark:text-red-200">
                  <li>Private keys or seed phrases</li>
                  <li>Personal identifying information (name, address, email)</li>
                  <li>Financial account details or banking information</li>
                  <li>Trading partner information</li>
                  <li>Any confidential or sensitive data</li>
                </ul>
                <p className="mt-4 text-sm text-red-800 dark:text-red-300">
                  Treat this bot like a public forum. We cannot guarantee the security of any
                  information you choose to share.
                </p>
              </div>
            </section>

            {/* Third-Party Services */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Third-Party Services</h2>
              <p className="mb-4">
                This bot is powered by <strong>OpenAI&apos;s API</strong>:
              </p>
              <ul className="list-disc pl-6 space-y-2 mb-4">
                <li>Your questions are sent to OpenAI&apos;s servers for AI processing</li>
                <li>Usage is subject to OpenAI&apos;s terms of service and usage policies</li>
                <li>OpenAI does not use API data to train their models</li>
                <li>
                  See{" "}
                  <a
                    href="https://openai.com/policies/row-privacy-policy/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    OpenAI&apos;s Privacy Policy
                  </a>{" "}
                  and{" "}
                  <a
                    href="https://openai.com/policies/terms-of-use/"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    Terms of Use
                  </a>
                </li>
              </ul>
            </section>

            {/* Community Nature */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Community Nature</h2>
              <ul className="list-disc pl-6 space-y-2">
                <li>
                  <strong>Maintainer:</strong> Independent contributor to Bisq community
                </li>
                <li>
                  <strong>Compensation:</strong> BSQ only, through official Bisq DAO contribution process
                </li>
                <li>
                  <strong>Not part of exchange infrastructure:</strong> This bot does not participate
                  in trade matching, fund custody, or any core exchange operations
                </li>
                <li>
                  <strong>Open source:</strong> Code is available for review on GitHub
                </li>
              </ul>
            </section>

            {/* Official Resources */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Official Bisq Resources</h2>
              <p className="mb-4">
                For authoritative information and official support, please use:
              </p>
              <ul className="list-disc pl-6 space-y-2">
                <li>
                  <a
                    href="https://bisq.wiki"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    Bisq Wiki
                  </a>{" "}
                  - Official documentation
                </li>
                <li>
                  <a
                    href="https://bisq.network"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    Bisq Network
                  </a>{" "}
                  - Official website
                </li>
                <li>
                  <a
                    href="https://bisq.community"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    Bisq Community Forum
                  </a>{" "}
                  - Community discussions
                </li>
                <li>
                  <a
                    href="https://matrix.to/#/#bisq:bitcoin.kyoto"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline"
                  >
                    Bisq Matrix Channel
                  </a>{" "}
                  - Real-time community support
                </li>
              </ul>
            </section>

            {/* Acceptance */}
            <section className="border-t pt-6">
              <h2 className="text-2xl font-semibold mb-4">Acceptance of Terms</h2>
              <p className="text-muted-foreground">
                By using this chatbot, you acknowledge that you have read, understood, and agree
                to be bound by these Terms of Service. If you do not agree to these terms,
                please do not use this service.
              </p>
            </section>

            {/* Related Policies */}
            <section className="border-t pt-6">
              <h2 className="text-2xl font-semibold mb-4">Related Policies</h2>
              <p>
                Please also review our{" "}
                <Link
                  href="/privacy"
                  className="text-primary hover:underline"
                >
                  Privacy Policy
                </Link>{" "}
                to understand how we handle your data.
              </p>
            </section>
          </div>
        </Card>
      </div>
    </main>
  )
}
