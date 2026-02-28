/**
 * Inline display shown when an escalated question is closed/dismissed without reply.
 */

import { XCircle } from "lucide-react"

interface HumanClosedSectionProps {
  resolvedAt?: string | null
  language?: string | null
}

const CLOSED_COPY: Record<string, { title: string; body: string }> = {
  en: {
    title: "Escalation Closed",
    body: "Support closed this request without sending a reply.",
  },
  de: {
    title: "Eskalation geschlossen",
    body: "Der Support hat diese Anfrage ohne Antwort geschlossen.",
  },
  es: {
    title: "Escalacion cerrada",
    body: "Soporte cerro esta solicitud sin enviar una respuesta.",
  },
  fr: {
    title: "Escalade terminee",
    body: "Le support a cloture cette demande sans envoyer de reponse.",
  },
}

function normalizeLanguage(language?: string | null): string {
  const raw = (language || "").trim().toLowerCase()
  if (!raw) return "en"
  if (raw.includes("-")) return raw.split("-", 1)[0]
  return raw
}

function getClosedCopy(language?: string | null): { title: string; body: string } {
  const normalized = normalizeLanguage(language)
  return CLOSED_COPY[normalized] || CLOSED_COPY.en
}

function formatDate(timestamp: string, language?: string | null): string {
  return new Date(timestamp).toLocaleDateString(language || "en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function HumanClosedSection({ resolvedAt, language }: HumanClosedSectionProps) {
  const copy = getClosedCopy(language)
  return (
    <div className="mt-2 p-3 rounded-lg bg-muted/40 border border-border">
      <div className="flex items-center gap-1.5 mb-1.5">
        <XCircle className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
        <span className="text-xs font-medium text-foreground">
          {copy.title}
        </span>
      </div>
      <p className="text-sm text-muted-foreground leading-relaxed">
        {copy.body}
      </p>
      {resolvedAt && (
        <p className="text-[10px] text-muted-foreground mt-1.5 tabular-nums">
          {formatDate(resolvedAt, language)}
        </p>
      )}
    </div>
  )
}
