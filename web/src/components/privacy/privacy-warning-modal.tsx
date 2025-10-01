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
import { AlertTriangle } from "lucide-react"

const STORAGE_KEY = "bisq-privacy-warning-acknowledged"

export function PrivacyWarningModal() {
  const [showModal, setShowModal] = useState(false)

  useEffect(() => {
    const acknowledged = localStorage.getItem(STORAGE_KEY)
    if (!acknowledged) {
      setShowModal(true)
    }
  }, [])

  const handleAcknowledge = () => {
    localStorage.setItem(STORAGE_KEY, "true")
    setShowModal(false)
  }

  return (
    <Dialog open={showModal} onOpenChange={() => {}}>
      <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto" onPointerDownOutside={(e) => e.preventDefault()}>
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
            <div className="flex items-start gap-2">
              <span className="text-lg">📤</span>
              <p>
                <strong>Your questions are sent to OpenAI</strong> for AI processing
              </p>
            </div>
            <div className="flex items-start gap-2">
              <span className="text-lg">📊</span>
              <p>
                <strong>We collect questions, answers, and feedback</strong> to improve our service
              </p>
            </div>
            <div className="flex items-start gap-2">
              <span className="text-lg">🗑️</span>
              <p>
                <strong>All personal data is automatically deleted after 30 days</strong>
              </p>
            </div>
            <div className="flex items-start gap-2">
              <span className="text-lg">📚</span>
              <p>
                <strong>Only anonymized FAQs are kept permanently</strong>
              </p>
            </div>
          </div>

          <p className="text-xs text-muted-foreground">
            For full details, read our{" "}
            <Link
              href="/privacy"
              target="_blank"
              className="text-primary hover:underline"
            >
              Privacy Policy
            </Link>
            .
          </p>
        </div>

        <DialogFooter className="flex-col sm:flex-row gap-2">
          <Button
            variant="outline"
            asChild
            className="w-full sm:w-auto"
          >
            <Link href="/privacy" target="_blank">
              Read Full Privacy Policy
            </Link>
          </Button>
          <Button
            onClick={handleAcknowledge}
            className="w-full sm:w-auto"
          >
            I Understand
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
