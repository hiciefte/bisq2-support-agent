"use client"

import { useState, useEffect } from "react"
import Link from "next/link"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Button } from "@/components/ui/button"
import { AlertTriangle, Send, Database, Trash2, FileText, KeyRound } from "lucide-react"

const STORAGE_KEY_PREFIX = "bisq-privacy-warning-acknowledged-v3"

interface PrivacyWarningModalProps {
  retentionDays: number
}

export function PrivacyWarningModal({ retentionDays }: PrivacyWarningModalProps) {
  const [showModal, setShowModal] = useState(false)
  const storageKey = `${STORAGE_KEY_PREFIX}-${retentionDays}-days`

  useEffect(() => {
    const acknowledged = localStorage.getItem(storageKey)
    if (!acknowledged) {
      setShowModal(true)
    }
  }, [storageKey])

  const handleAcknowledge = () => {
    localStorage.setItem(storageKey, "true")
    setShowModal(false)
  }

  return (
    <Dialog open={showModal} onOpenChange={() => {}}>
      <DialogContent
        className="max-w-2xl max-h-[90vh] overflow-y-auto"
        onPointerDownOutside={(e) => e.preventDefault()}
        showClose={false}
      >
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-xl">
            <AlertTriangle className="h-6 w-6 text-yellow-500" />
            Privacy & Data Usage Notice
          </DialogTitle>
          <DialogDescription className="sr-only">
            Important privacy and security information
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 py-4">
          <div className="border-l-4 border-red-500 bg-red-50 dark:bg-red-950/20 p-4 rounded-r-lg">
            <p className="font-bold text-red-900 dark:text-red-200 mb-3">
              ⚠️ NEVER SHARE SENSITIVE INFORMATION:
            </p>
            <ul className="space-y-2 text-sm text-red-900 dark:text-red-200">
              <li className="flex items-start">
                <span className="mr-2">•</span>
                <span>Private keys or seed phrases</span>
              </li>
              <li className="flex items-start">
                <span className="mr-2">•</span>
                <span>Personal identifying information (name, address, email)</span>
              </li>
              <li className="flex items-start">
                <span className="mr-2">•</span>
                <span>Financial account details</span>
              </li>
              <li className="flex items-start">
                <span className="mr-2">•</span>
                <span>Trading partner information</span>
              </li>
              <li className="flex items-start">
                <span className="mr-2">•</span>
                <span>Any confidential data</span>
              </li>
            </ul>
          </div>

          <div className="space-y-3 text-sm">
            <div className="flex items-start gap-3">
              <Send className="h-5 w-5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p>
                <strong>
                  Questions and conversation context may be sent to external providers
                </strong>{" "}
                for AI or translation processing
              </p>
            </div>
            <div className="flex items-start gap-3">
              <Trash2 className="h-5 w-5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p>
                <strong>
                  Qualifying local support records older than {retentionDays} days are deleted or
                  anonymized
                </strong>
                , including questions, answers, feedback, escalations, channel identifiers, and
                bind-mounted logs; legacy rows with no provable timestamp can remain pending manual
                review, and container runtime logs require a separately verified host policy
              </p>
            </div>
            <div className="flex items-start gap-3">
              <Database className="h-5 w-5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p>
                <strong>Reviewed knowledge text and aggregate metrics may be retained</strong>{" "}
                indefinitely; FAQs and support playbooks can keep reviewed question and answer text
                without structured source identifiers or conversation links, while aggregates
                exclude message text
              </p>
            </div>
            <div className="flex items-start gap-3">
              <FileText className="h-5 w-5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p>
                <strong>Matrix, Bisq, and provider-held copies are outside local deletion</strong>{" "}
                and follow those systems&apos; policies
              </p>
            </div>
            <div className="flex items-start gap-3">
              <KeyRound className="h-5 w-5 text-muted-foreground flex-shrink-0 mt-0.5" />
              <p>
                <strong>
                  Matrix session and local encryption state rotate on the {retentionDays}-day
                  cadence
                </strong>
                ; the integration reauthenticates, while current Matrix and Bisq sync cursors can
                remain as operational checkpoints
              </p>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            By using this service, you agree to our{" "}
            <Link href="/terms" target="_blank" className="text-primary hover:underline">
              Terms of Service
            </Link>{" "}
            and{" "}
            <Link href="/privacy" target="_blank" className="text-primary hover:underline">
              Privacy Policy
            </Link>
            .
          </p>
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button variant="outline" asChild className="w-full sm:w-auto">
            <Link href="/terms" target="_blank">
              Terms of Service
            </Link>
          </Button>
          <Button variant="outline" asChild className="w-full sm:w-auto">
            <Link href="/privacy" target="_blank">
              Privacy Policy
            </Link>
          </Button>
          <Button onClick={handleAcknowledge} className="w-full sm:w-auto">
            I Understand
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
