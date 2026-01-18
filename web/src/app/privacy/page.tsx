import Link from "next/link"
import { Metadata } from "next"
import { Card } from "@/components/ui/card"

export const metadata: Metadata = {
  title: "Privacy Policy - Bisq 2 Support Assistant",
  description:
    "Learn how we handle your data. We collect minimal information and automatically delete personal data after 30 days.",
}

export default function PrivacyPolicy() {
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
          <p className="text-sm text-muted-foreground mb-8">Last updated: October 1, 2025</p>

          <div className="space-y-8">
            {/* What We Collect */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">What We Collect</h2>
              <p className="mb-4">
                We collect the following information when you use our chat service:
              </p>
              <ul className="list-disc pl-6 space-y-2 mb-4">
                <li>Your questions and the AI&apos;s responses</li>
                <li>Feedback ratings (thumbs up/down)</li>
                <li>Optional explanations for negative feedback</li>
                <li>Timestamps of interactions</li>
              </ul>
              <p className="font-semibold mb-2">We do NOT collect:</p>
              <ul className="list-disc pl-6 space-y-2">
                <li>Names or personal identifiers</li>
                <li>Email addresses or contact information</li>
                <li>IP addresses (beyond standard server logs)</li>
                <li>User accounts or login credentials</li>
              </ul>
            </section>

            {/* How We Use Your Data */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">How We Use Your Data</h2>
              <ul className="list-disc pl-6 space-y-2">
                <li><strong>Improve AI Responses:</strong> Analyze feedback to enhance answer quality</li>
                <li><strong>Generate FAQs:</strong> Create anonymized frequently asked questions for our knowledge base</li>
                <li><strong>Service Analytics:</strong> Understand usage patterns to improve the chatbot</li>
              </ul>
            </section>

            {/* Data Retention */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Data Retention</h2>
              <div className="space-y-3">
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Personal Data</p>
                  <p className="text-sm">Automatically deleted after 30 days</p>
                </div>
                <div className="p-4 bg-muted rounded-lg">
                  <p className="font-semibold mb-1">Anonymized FAQs</p>
                  <p className="text-sm">Kept permanently (no personal identifiers)</p>
                </div>
              </div>
            </section>

            {/* Third-Party Services */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Third-Party Services</h2>
              <p className="mb-4">
                We use <strong>OpenAI</strong> to power our AI chatbot:
              </p>
              <ul className="list-disc pl-6 space-y-2 mb-4">
                <li>Your questions are sent to OpenAI&apos;s servers for processing</li>
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
                  </a>
                </li>
              </ul>
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
                  Treat this chatbot like a public forum. We cannot guarantee the security of any information you choose to share.
                </p>
              </div>
            </section>

            {/* Your Rights */}
            <section>
              <h2 className="text-2xl font-semibold mb-4">Your Rights</h2>
              <ul className="list-disc pl-6 space-y-2">
                <li>No account is required to use this service</li>
                <li>All data is automatically deleted after 30 days</li>
                <li>To prevent data collection: Don&apos;t share sensitive information</li>
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
