"use client"

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  BookOpenCheck,
  Bot,
  CheckCircle2,
  ChevronDown,
  FileText,
  GraduationCap,
  HelpCircle,
  Loader2,
  MessageSquare,
  PencilLine,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { toast } from "sonner";
import { AdminQueueShell } from "@/components/admin/queue/AdminQueueShell";
import { QueuePageHeader } from "@/components/admin/queue/QueuePageHeader";
import { QueueTabs } from "@/components/admin/queue/QueueTabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Textarea } from "@/components/ui/textarea";
import { MarkdownContent } from "@/components/chat/components/markdown-content";
import { SourceBadges } from "@/components/chat/components/source-badges";
import { makeAuthenticatedRequest } from "@/lib/auth";
import { stripGeneratedAnswerFooter } from "@/lib/answer-format";
import { cn } from "@/lib/utils";
import type { Source } from "@/components/chat/types/chat.types";
import type { QueueCounts, RoutingCategory, UnifiedCandidate } from "@/components/admin/training/types";

type CheckStatus = "pass" | "warn" | "fail";
type AnswerRating = "good" | "needs_improvement";
type DocumentReviewMode = "diff" | "preview";

interface KnowledgeCheck {
  code: string;
  label: string;
  status: CheckStatus;
  detail: string;
  blocking: boolean;
}

interface KnowledgeOperation {
  id: string;
  section: string;
  action: string;
  content: string;
}

interface KnowledgeProposal {
  id: number;
  candidate_id: number;
  target_page_id: string | null;
  target_page_title: string | null;
  target_page_status: string | null;
  proposal_kind: "update_existing" | "create_new";
  operations: KnowledgeOperation[];
  preview_markdown: string;
  document_markdown_override: string | null;
  source_refs: string[];
  checks: KnowledgeCheck[];
  status: string;
  current_page_markdown: string | null;
}

interface KnowledgeUpdateResponse {
  candidate: UnifiedCandidate;
  proposal: KnowledgeProposal;
}

interface DiffRow {
  kind: "context" | "add" | "remove";
  beforeLine: number | null;
  afterLine: number | null;
  text: string;
}

const QUEUE_LABELS: Record<RoutingCategory, string> = {
  FULL_REVIEW: "1. Full review",
  SPOT_CHECK: "2. Spot check",
  AUTO_APPROVE: "3. Ready queue",
};

const QUEUE_TABS = [
  {
    key: "FULL_REVIEW" as const,
    label: QUEUE_LABELS.FULL_REVIEW,
    description: "Start here: highest review risk",
    countLabel: "pending candidates",
    icon: BookOpenCheck,
  },
  {
    key: "SPOT_CHECK" as const,
    label: QUEUE_LABELS.SPOT_CHECK,
    description: "Lower-risk edits to verify",
    countLabel: "pending candidates",
    icon: ShieldCheck,
  },
  {
    key: "AUTO_APPROVE" as const,
    label: QUEUE_LABELS.AUTO_APPROVE,
    description: "High-confidence backlog",
    countLabel: "pending candidates",
    icon: GraduationCap,
  },
];

const QUEUE_GUIDANCE: Record<RoutingCategory, { title: string; body: string; nextAction: string }> = {
  FULL_REVIEW: {
    title: "Start with full review",
    body: "These candidates need the most human judgment. Read the proposed LLM Wiki page, edit weak wording, and check sources when a claim looks risky or unsupported.",
    nextAction: "Approve only when the final page is reusable support knowledge.",
  },
  SPOT_CHECK: {
    title: "Spot-check lower-risk edits",
    body: "These candidates look closer to existing knowledge. Read the changed page first, then open sources only for claims that feel surprising, broad, or user-facing.",
    nextAction: "Use this lane after the full-review queue is under control.",
  },
  AUTO_APPROVE: {
    title: "Use the ready queue last",
    body: "These candidates were routed as high confidence, but during initial bootstrapping they still deserve quick sampling so the generated LLM Wiki stays clean.",
    nextAction: "Do not treat this as the first lane for manual cleanup.",
  },
};

const SHORTCUT_HINTS = [
  { keyCombo: "S", label: "Save document" },
  { keyCombo: "A", label: "Approve" },
  { keyCombo: "R", label: "Reject" },
];

const REVIEW_GUIDE_STORAGE_KEY = "bisq-support:knowledge-updates:review-guide-dismissed";

const DOCUMENT_REVIEW_MODES: Array<{
  key: DocumentReviewMode;
  label: string;
  description: string;
}> = [
  {
    key: "diff",
    label: "Diff & edit",
    description: "Read the full file and edit proposed lines in context.",
  },
  {
    key: "preview",
    label: "Preview",
    description: "Read the final rendered page without frontmatter noise.",
  },
];

const SUPPORTING_OPERATION_IDS = new Set([
  "do-not-say",
  "review-note",
  "last-change",
  "evidence-sources",
]);

const OPERATION_HINTS: Record<string, string> = {
  "canonical-answer": "Primary content. Check that this is durable, precise support guidance before approving.",
  "applies-when": "Retrieval cue. This teaches when the LLM Wiki page should be used.",
  "do-not-say": "Safety guardrail. Edit only if the generated limit is too broad or too narrow.",
  "review-note": "Reviewer audit trail. Usually no manual edit needed.",
  "last-change": "Maintenance summary for future reviewers. Usually no manual edit needed.",
  "evidence-sources": "Stored source references. Use the compact source badge before these fields when verification is needed.",
};

function formatDate(value: string | null | undefined): string {
  if (!value) return "Unknown";
  return new Date(value).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatPercent(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  return `${Math.round(value * 100)}%`;
}

function stripFrontmatter(markdown: string): string {
  const value = markdown.trim();
  if (!value.startsWith("---")) return value;
  const end = value.indexOf("\n---", 3);
  if (end === -1) return value;
  return value.slice(end + 4).trim();
}

function splitMarkdownLines(markdown: string): string[] {
  if (!markdown) return [];
  return markdown.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");
}

function buildLineDiff(beforeMarkdown: string | null, afterMarkdown: string): DiffRow[] {
  const before = splitMarkdownLines(beforeMarkdown ?? "");
  const after = splitMarkdownLines(afterMarkdown);
  const dp: number[][] = Array.from({ length: before.length + 1 }, () =>
    Array(after.length + 1).fill(0),
  );

  for (let i = before.length - 1; i >= 0; i -= 1) {
    for (let j = after.length - 1; j >= 0; j -= 1) {
      dp[i][j] = before[i] === after[j]
        ? dp[i + 1][j + 1] + 1
        : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }

  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  let beforeLine = 1;
  let afterLine = 1;
  while (i < before.length && j < after.length) {
    if (before[i] === after[j]) {
      rows.push({
        kind: "context",
        beforeLine,
        afterLine,
        text: before[i],
      });
      i += 1;
      j += 1;
      beforeLine += 1;
      afterLine += 1;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      rows.push({
        kind: "remove",
        beforeLine,
        afterLine: null,
        text: before[i],
      });
      i += 1;
      beforeLine += 1;
    } else {
      rows.push({
        kind: "add",
        beforeLine: null,
        afterLine,
        text: after[j],
      });
      j += 1;
      afterLine += 1;
    }
  }

  while (i < before.length) {
    rows.push({
      kind: "remove",
      beforeLine,
      afterLine: null,
      text: before[i],
    });
    i += 1;
    beforeLine += 1;
  }

  while (j < after.length) {
    rows.push({
      kind: "add",
      beforeLine: null,
      afterLine,
      text: after[j],
    });
    j += 1;
    afterLine += 1;
  }

  return rows;
}

function replaceMarkdownLine(markdown: string, lineNumber: number, value: string): string {
  const lines = splitMarkdownLines(markdown);
  lines[lineNumber - 1] = value;
  return lines.join("\n");
}

function actionLabel(action: string): string {
  return action
    .replace(/_/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function parseConversation(value: string | null): Array<{ sender?: string; content: string; timestamp?: string }> {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed)
      ? parsed.filter((item) => item && typeof item.content === "string")
      : [];
  } catch {
    return [];
  }
}

function protocolLabel(protocol: UnifiedCandidate["protocol"]): string {
  if (protocol === "multisig_v1") return "Multisig";
  if (protocol === "bisq_easy") return "Bisq Easy";
  if (protocol === "musig") return "MuSig";
  if (protocol === "all") return "All";
  return "Protocol unknown";
}

function ContextBadge({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
}) {
  return (
    <span className="inline-flex h-7 items-center gap-1.5 rounded-full border border-border/70 bg-background px-2.5 text-xs font-medium text-foreground shadow-sm shadow-black/[0.02]">
      <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden="true" />
      <span className="text-[10px] uppercase tracking-[0.3px] text-muted-foreground">{label}</span>
      <span>{value}</span>
    </span>
  );
}

function formatCandidateCount(count: number): string {
  return `${count.toLocaleString()} ${count === 1 ? "candidate" : "candidates"}`;
}

function KnowledgeUpdateReviewGuide({
  counts,
  activeQueue,
  isDismissed,
  onDismiss,
  onShow,
}: {
  counts: QueueCounts;
  activeQueue: RoutingCategory;
  isDismissed: boolean | null;
  onDismiss: () => void;
  onShow: () => void;
}) {
  const total = counts.FULL_REVIEW + counts.SPOT_CHECK + counts.AUTO_APPROVE;
  const guidance = QUEUE_GUIDANCE[activeQueue];
  const activeCount = counts[activeQueue] ?? 0;

  if (isDismissed === null) return null;

  if (isDismissed) {
    return (
      <div className="flex justify-end">
        <Button
          variant="ghost"
          size="sm"
          onClick={onShow}
          className="gap-2 text-muted-foreground hover:text-foreground"
        >
          <BookOpenCheck className="h-4 w-4" aria-hidden="true" />
          Show review guide
        </Button>
      </div>
    );
  }

  return (
    <Card className="relative border-primary/20 bg-secondary/40 shadow-sm">
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={onDismiss}
        className="absolute right-[13px] top-[13px] z-10 h-8 w-8 text-muted-foreground hover:bg-background/70 hover:text-foreground"
        aria-label="Hide review guide"
        title="Hide review guide"
      >
        <X className="h-4 w-4" aria-hidden="true" />
      </Button>
      <CardContent className="p-4 pr-14 md:p-5 md:pr-16">
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(280px,0.75fr)]">
          <div className="space-y-3">
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 rounded-full bg-primary/10 p-2 text-primary">
                <BookOpenCheck className="h-4 w-4" aria-hidden="true" />
              </div>
              <div className="min-w-0">
                <h2 className="text-base font-semibold">Your job: approve one reusable LLM Wiki page at a time</h2>
                <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">
                  The page turns repeated support evidence into internal knowledge the bot can retrieve later.
                  It is not asking you to create hundreds of FAQs. Read the proposed page first, edit it if
                  needed, then spot-check sources only when a claim looks wrong, unsupported, or risky.
                </p>
              </div>
            </div>
            <div className="grid gap-2 md:grid-cols-3">
              {[
                ["1", "Read the wiki page", "Check whether the reusable answer is precise and durable."],
                ["2", "Open sources only if needed", "Use support evidence to verify suspicious or high-impact claims."],
                ["3", "Approve, skip, or reject", "Approval updates internal LLM Wiki knowledge, not a public FAQ."],
              ].map(([step, title, body]) => (
                <div key={step} className="rounded-lg border border-border/70 bg-background/70 p-3">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-foreground text-[11px] font-semibold text-background">
                      {step}
                    </span>
                    <p className="text-sm font-medium">{title}</p>
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">{body}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="space-y-3 rounded-xl border border-border/70 bg-background/80 p-4">
            <div className="rounded-lg border border-border/70 bg-muted/20 p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-medium">{guidance.title}</p>
                  <p className="mt-1 text-xs leading-5 text-muted-foreground">{guidance.body}</p>
                  <p className="mt-1 text-xs font-medium text-foreground">{guidance.nextAction}</p>
                </div>
                <Badge variant="secondary" className="shrink-0 justify-center tabular-nums">
                  {formatCandidateCount(activeCount)}
                </Badge>
              </div>
            </div>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-medium">About the backlog</p>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  The lane numbers are pending support candidates, not final pages. A large initial count is
                  expected while bootstrapping; approving one good LLM Wiki page can absorb many similar
                  future questions.
                </p>
              </div>
              <Badge variant="outline" className="shrink-0 tabular-nums">
                {total.toLocaleString()}
              </Badge>
            </div>
            <div className="mt-3 grid gap-2 text-xs">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Full review</span>
                <span className="font-medium tabular-nums">{formatCandidateCount(counts.FULL_REVIEW)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Spot check</span>
                <span className="font-medium tabular-nums">{formatCandidateCount(counts.SPOT_CHECK)}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Ready queue</span>
                <span className="font-medium tabular-nums">{formatCandidateCount(counts.AUTO_APPROVE)}</span>
              </div>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function CompactKnowledgeSources({
  sources,
}: {
  sources: Source[] | null;
}) {
  const generatedSources = sources ?? [];

  if (generatedSources.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border/70 bg-muted/10 px-3 py-2">
      <p className="text-xs leading-5 text-muted-foreground">
        Spot-check sources only if the reviewed document raises questions.
      </p>
      <SourceBadges sources={generatedSources} />
    </div>
  );
}

function DocumentDiffViewer({
  rows,
  editingLine,
  onEditLine,
  onChangeLine,
  onStopEditing,
}: {
  rows: DiffRow[];
  editingLine: number | null;
  onEditLine: (lineNumber: number) => void;
  onChangeLine: (lineNumber: number, value: string) => void;
  onStopEditing: () => void;
}) {
  const addedCount = rows.filter((row) => row.kind === "add").length;
  const removedCount = rows.filter((row) => row.kind === "remove").length;

  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-background">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 bg-muted/20 px-3 py-2">
        <div>
          <p className="text-sm font-medium">Full wiki file: diff & edit</p>
          <p className="text-xs text-muted-foreground">
            Click a proposed line to edit it in place while keeping the diff context visible.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-emerald-700">
            +{addedCount}
          </span>
          <span className="rounded-full border border-red-500/25 bg-red-500/10 px-2 py-0.5 text-red-700">
            -{removedCount}
          </span>
        </div>
      </div>
      <div className="max-h-[64vh] overflow-auto">
        <table className="w-full border-collapse text-left font-mono text-xs">
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={`${row.kind}-${row.beforeLine ?? "x"}-${row.afterLine ?? "x"}-${index}`}
                onClick={row.afterLine !== null ? () => onEditLine(row.afterLine ?? 1) : undefined}
                className={cn(
                  "border-b border-border/30",
                  row.kind === "add" && "bg-emerald-500/10",
                  row.kind === "remove" && "bg-red-500/10",
                  row.afterLine !== null && "cursor-text hover:bg-muted/30",
                )}
              >
                <td className="w-10 select-none border-r border-border/40 px-2 py-1 text-right text-muted-foreground">
                  {row.beforeLine ?? ""}
                </td>
                <td className="w-10 select-none border-r border-border/40 px-2 py-1 text-right text-muted-foreground">
                  {row.afterLine ?? ""}
                </td>
                <td
                  className={cn(
                    "w-7 select-none border-r border-border/40 px-2 py-1 text-center",
                    row.kind === "add" && "text-emerald-700",
                    row.kind === "remove" && "text-red-700",
                    row.kind === "context" && "text-muted-foreground",
                  )}
                >
                  {row.kind === "add" ? "+" : row.kind === "remove" ? "-" : ""}
                </td>
                <td className="min-w-0 px-3 py-1">
                  {row.afterLine !== null && editingLine === row.afterLine ? (
                    <Textarea
                      autoFocus
                      value={row.text}
                      onClick={(event) => event.stopPropagation()}
                      onChange={(event) => onChangeLine(row.afterLine ?? 1, event.target.value)}
                      onBlur={onStopEditing}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") onStopEditing();
                      }}
                      className="min-h-20 resize-y bg-background font-mono text-xs leading-5"
                      aria-label={`Edit proposed markdown line ${row.afterLine}`}
                    />
                  ) : (
                    <pre className="whitespace-pre-wrap break-words font-mono leading-5">
                      {row.text || " "}
                    </pre>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function DocumentReviewModeSelector({
  value,
  onChange,
}: {
  value: DocumentReviewMode;
  onChange: (value: DocumentReviewMode) => void;
}) {
  return (
    <div
      className="grid gap-1 rounded-lg border border-border/70 bg-muted/15 p-1 sm:grid-cols-2"
      role="tablist"
      aria-label="Document review mode"
    >
      {DOCUMENT_REVIEW_MODES.map((mode) => (
        <button
          key={mode.key}
          type="button"
          role="tab"
          aria-selected={value === mode.key}
          onClick={() => onChange(mode.key)}
          className={cn(
            "rounded-md px-3 py-2 text-left transition-colors",
            value === mode.key
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:bg-background/60 hover:text-foreground",
          )}
        >
          <span className="block text-sm font-medium">{mode.label}</span>
          <span className="mt-0.5 block text-xs leading-4">{mode.description}</span>
        </button>
      ))}
    </div>
  );
}

function OperationEditor({
  operation,
  onChange,
}: {
  operation: KnowledgeOperation;
  onChange: (id: string, content: string) => void;
}) {
  return (
    <div className="rounded-lg border border-border/70 bg-muted/10 p-3">
      <div className="mb-2 space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-background px-2.5 py-1 text-xs font-medium">
            <FileText className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            Section: {operation.section}
          </span>
          <span className="inline-flex items-center gap-1.5 rounded-full border border-border/70 bg-background px-2.5 py-1 text-xs font-medium">
            <ArrowRight className="h-3 w-3 text-muted-foreground" aria-hidden="true" />
            On approval: {actionLabel(operation.action)}
          </span>
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          {OPERATION_HINTS[operation.id] ?? "Edit only if this generated section is inaccurate or too broad."}
        </p>
      </div>
      <Textarea
        value={operation.content}
        onChange={(event) => onChange(operation.id, event.target.value)}
        className="min-h-24 resize-y bg-background/80"
        aria-label={`${operation.section} ${actionLabel(operation.action)}`}
      />
    </div>
  );
}

function CheckIcon({ status }: { status: CheckStatus }) {
  if (status === "pass") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "warn") return <AlertTriangle className="h-4 w-4 text-amber-500" />;
  return <XCircle className="h-4 w-4 text-destructive" />;
}

function CheckPill({ check }: { check: KnowledgeCheck }) {
  return (
    <div
      className={cn(
        "rounded-lg border p-3",
        check.status === "pass" && "border-emerald-500/20 bg-emerald-500/5",
        check.status === "warn" && "border-amber-500/25 bg-amber-500/5",
        check.status === "fail" && "border-destructive/25 bg-destructive/5",
      )}
    >
      <div className="flex items-start gap-2">
        <CheckIcon status={check.status} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-medium">{check.label}</p>
            {check.blocking && (
              <Badge variant="outline" className="h-5 text-[11px]">
                Blocking
              </Badge>
            )}
          </div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">{check.detail}</p>
        </div>
      </div>
    </div>
  );
}

export default function KnowledgeUpdatesPage() {
  const [queueCounts, setQueueCounts] = useState<QueueCounts>({
    FULL_REVIEW: 0,
    SPOT_CHECK: 0,
    AUTO_APPROVE: 0,
  });
  const [activeQueue, setActiveQueue] = useState<RoutingCategory>("FULL_REVIEW");
  const [data, setData] = useState<KnowledgeUpdateResponse | null>(null);
  const [operations, setOperations] = useState<KnowledgeOperation[]>([]);
  const [documentMarkdown, setDocumentMarkdown] = useState("");
  const [documentMode, setDocumentMode] = useState<DocumentReviewMode>("diff");
  const [editingDocumentLine, setEditingDocumentLine] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<Date | null>(null);
  const [showConversation, setShowConversation] = useState(false);
  const [showFaqFallback, setShowFaqFallback] = useState(false);
  const [showSupportingEdits, setShowSupportingEdits] = useState(false);
  const [answerRating, setAnswerRating] = useState<AnswerRating | null>(null);
  const [ratingLoading, setRatingLoading] = useState<AnswerRating | null>(null);
  const [isReviewGuideDismissed, setIsReviewGuideDismissed] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);

  const isOperationDirty = useMemo(
    () => JSON.stringify(operations) !== JSON.stringify(data?.proposal.operations ?? []),
    [operations, data?.proposal.operations],
  );

  const isDocumentDirty = useMemo(
    () => documentMarkdown !== (data?.proposal.preview_markdown ?? ""),
    [documentMarkdown, data?.proposal.preview_markdown],
  );

  const isDirty = isOperationDirty || isDocumentDirty;

  const hasBlockingFailure = useMemo(
    () => data?.proposal.checks.some((check) => check.blocking && check.status === "fail") ?? false,
    [data?.proposal.checks],
  );

  const conversation = useMemo(
    () => parseConversation(data?.candidate.conversation_context ?? null),
    [data?.candidate.conversation_context],
  );

  const previewBody = useMemo(
    () => stripFrontmatter(documentMarkdown),
    [documentMarkdown],
  );

  const documentDiffRows = useMemo(
    () => buildLineDiff(data?.proposal.current_page_markdown ?? null, documentMarkdown),
    [data?.proposal.current_page_markdown, documentMarkdown],
  );

  const cleanedGeneratedAnswer = useMemo(
    () => stripGeneratedAnswerFooter(data?.candidate.generated_answer ?? ""),
    [data?.candidate.generated_answer],
  );

  const { primaryOperations, supportingOperations } = useMemo(() => {
    const primary: KnowledgeOperation[] = [];
    const supporting: KnowledgeOperation[] = [];
    for (const operation of operations) {
      if (SUPPORTING_OPERATION_IDS.has(operation.id)) {
        supporting.push(operation);
      } else {
        primary.push(operation);
      }
    }
    return { primaryOperations: primary, supportingOperations: supporting };
  }, [operations]);

  const tabs = useMemo(
    () =>
      QUEUE_TABS.map((tab) => ({
        ...tab,
        count: queueCounts[tab.key] ?? 0,
      })),
    [queueCounts],
  );

  const loadData = useCallback(async (options?: { silent?: boolean }) => {
    if (!options?.silent) setIsLoading(true);
    setIsRefreshing(true);
    setError(null);
    try {
      const [countsResponse, currentResponse] = await Promise.all([
        makeAuthenticatedRequest("/admin/knowledge-updates/counts"),
        makeAuthenticatedRequest(`/admin/knowledge-updates/current?queue=${activeQueue}`),
      ]);
      if (!countsResponse.ok) throw new Error("Failed to load queue counts");
      if (!currentResponse.ok) throw new Error("Failed to load current knowledge update");

      const counts = await countsResponse.json();
      const current = (await currentResponse.json()) as KnowledgeUpdateResponse | null;
      setQueueCounts(counts);
      setData(current);
      setOperations(current?.proposal.operations ?? []);
      setDocumentMarkdown(current?.proposal.preview_markdown ?? "");
      setDocumentMode("diff");
      setEditingDocumentLine(null);
      setShowConversation(Boolean(current?.candidate.has_correction || current?.candidate.routing === "FULL_REVIEW"));
      setShowFaqFallback(false);
      setLastUpdatedAt(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load Knowledge Updates";
      setError(message);
      toast.error(message);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, [activeQueue]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  useEffect(() => {
    try {
      setIsReviewGuideDismissed(
        window.localStorage.getItem(REVIEW_GUIDE_STORAGE_KEY) === "true",
      );
    } catch {
      setIsReviewGuideDismissed(false);
    }
  }, []);

  useEffect(() => {
    setAnswerRating(null);
    setRatingLoading(null);
    setShowSupportingEdits(false);
    setEditingDocumentLine(null);
  }, [data?.candidate.id, data?.candidate.generated_answer]);

  const handleDismissReviewGuide = useCallback(() => {
    setIsReviewGuideDismissed(true);
    try {
      window.localStorage.setItem(REVIEW_GUIDE_STORAGE_KEY, "true");
    } catch {
      // Local storage can be unavailable in hardened browser contexts.
    }
  }, []);

  const handleShowReviewGuide = useCallback(() => {
    setIsReviewGuideDismissed(false);
    try {
      window.localStorage.removeItem(REVIEW_GUIDE_STORAGE_KEY);
    } catch {
      // Local storage can be unavailable in hardened browser contexts.
    }
  }, []);

  const persistOperations = async (): Promise<KnowledgeProposal | null> => {
    if (!data || !isOperationDirty) return data?.proposal ?? null;
    setIsSaving(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/proposal`,
        {
          method: "PATCH",
          body: JSON.stringify({ operations }),
        },
      );
      if (!response.ok) throw new Error("Failed to save proposed diff");
      const proposal = (await response.json()) as KnowledgeProposal;
      setData((current) => current ? { ...current, proposal } : current);
      setOperations(proposal.operations);
      setDocumentMarkdown(proposal.preview_markdown);
      setEditingDocumentLine(null);
      toast.success("Structured suggestions saved");
      return proposal;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save structured suggestions";
      toast.error(message);
      return null;
    } finally {
      setIsSaving(false);
    }
  };

  const persistDocumentMarkdown = async (): Promise<KnowledgeProposal | null> => {
    if (!data || !isDocumentDirty) return data?.proposal ?? null;
    setIsSaving(true);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/document`,
        {
          method: "PATCH",
          body: JSON.stringify({ markdown: documentMarkdown }),
        },
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || "Failed to save document");
      }
      const proposal = (await response.json()) as KnowledgeProposal;
      setData((current) => current ? { ...current, proposal } : current);
      setOperations(proposal.operations);
      setDocumentMarkdown(proposal.preview_markdown);
      setEditingDocumentLine(null);
      toast.success("Document saved");
      return proposal;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save document";
      toast.error(message);
      return null;
    } finally {
      setIsSaving(false);
    }
  };

  const handleApprove = async () => {
    if (!data) return;
    const saved = isDocumentDirty
      ? await persistDocumentMarkdown()
      : await persistOperations();
    if (!saved) return;
    setActionLoading("approve");
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/approve`,
        {
          method: "POST",
          body: JSON.stringify({ reviewer: "admin" }),
        },
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || "Failed to approve knowledge update");
      }
      toast.success("LLM Wiki change approved. Rebuild the vector store to make it retrievable.");
      await loadData({ silent: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to approve knowledge update";
      toast.error(message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleReject = async () => {
    if (!data) return;
    setActionLoading("reject");
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/reject`,
        {
          method: "POST",
          body: JSON.stringify({ reviewer: "admin", reason: "not_durable" }),
        },
      );
      if (!response.ok) throw new Error("Failed to reject knowledge update");
      toast.success("Knowledge update rejected");
      await loadData({ silent: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reject knowledge update";
      toast.error(message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleSkip = async () => {
    if (!data) return;
    setActionLoading("skip");
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/skip`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error("Failed to skip knowledge update");
      toast.success("Moved to the end of the queue");
      await loadData({ silent: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to skip knowledge update";
      toast.error(message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleRegenerate = async () => {
    if (!data) return;
    setActionLoading("regenerate");
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/generate`,
        { method: "POST" },
      );
      if (!response.ok) throw new Error("Failed to regenerate proposal");
      const proposal = (await response.json()) as KnowledgeProposal;
      setData((current) => current ? { ...current, proposal } : current);
      setOperations(proposal.operations);
      setDocumentMarkdown(proposal.preview_markdown);
      setDocumentMode("diff");
      setEditingDocumentLine(null);
      toast.success("Proposal regenerated");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to regenerate proposal";
      toast.error(message);
    } finally {
      setActionLoading(null);
    }
  };

  const handleCreateFaq = async () => {
    if (!data) return;
    setActionLoading("faq");
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/knowledge-updates/${data.candidate.id}/create-faq`,
        {
          method: "POST",
          body: JSON.stringify({ reviewer: "admin", force: false }),
        },
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail?.message || detail?.detail || "Failed to create FAQ");
      }
      toast.success("Public FAQ created from this item");
      await loadData({ silent: true });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to create FAQ";
      toast.error(message);
    } finally {
      setActionLoading(null);
    }
  };

  const updateOperation = (id: string, content: string) => {
    setOperations((current) =>
      current.map((operation) =>
        operation.id === id ? { ...operation, content } : operation,
      ),
    );
  };

  const updateDocumentLine = (lineNumber: number, content: string) => {
    setDocumentMarkdown((current) => replaceMarkdownLine(current, lineNumber, content));
  };

  const handleRateGeneratedAnswer = async (rating: AnswerRating) => {
    if (!data || !data.candidate.generated_answer) return;
    setRatingLoading(rating);
    try {
      const response = await makeAuthenticatedRequest(
        `/admin/training/candidates/${data.candidate.id}/rate-answer`,
        {
          method: "POST",
          body: JSON.stringify({ rating, reviewer: "admin" }),
        },
      );
      if (!response.ok) {
        const detail = await response.json().catch(() => null);
        throw new Error(detail?.detail || "Failed to record generated answer rating");
      }
      setAnswerRating(rating);
      toast.success(
        rating === "good"
          ? "AI answer marked as good enough"
          : "AI answer marked as needing work",
      );
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to record generated answer rating";
      toast.error(message);
    } finally {
      setRatingLoading(null);
    }
  };

  const generationConfidenceLabel = formatPercent(data?.candidate.generation_confidence);

  return (
    <AdminQueueShell showVectorStoreBanner shortcutHints={SHORTCUT_HINTS}>
      <QueuePageHeader
        title="Knowledge Updates"
        description="Review proposed LLM Wiki pages created from real support discussions. Start with Full review, then use Spot check and Ready queue as lower-risk follow-up lanes."
        lastUpdatedLabel={lastUpdatedAt ? `Updated ${formatDate(lastUpdatedAt.toISOString())}` : null}
        isRefreshing={isRefreshing}
        onRefresh={() => void loadData({ silent: true })}
        rightSlot={
          <Button
            variant="outline"
            size="sm"
            onClick={handleRegenerate}
            disabled={!data || actionLoading === "regenerate"}
            className="gap-2"
          >
            {actionLoading === "regenerate" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <RefreshCw className="h-4 w-4" />
            )}
            Regenerate
          </Button>
        }
      />

      <QueueTabs
        tabs={tabs}
        activeTab={activeQueue}
        onTabChange={setActiveQueue}
      />

      <KnowledgeUpdateReviewGuide
        counts={queueCounts}
        activeQueue={activeQueue}
        isDismissed={isReviewGuideDismissed}
        onDismiss={handleDismissReviewGuide}
        onShow={handleShowReviewGuide}
      />

      {error && (
        <Card className="border-destructive/30 bg-destructive/5">
          <CardContent className="p-4 text-sm text-destructive">{error}</CardContent>
        </Card>
      )}

      {isLoading ? (
        <Card className="border-border/70">
          <CardContent className="flex items-center gap-3 p-8 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Loading knowledge update queue...
          </CardContent>
        </Card>
      ) : !data ? (
        <Card className="border-border/70 bg-card/70">
          <CardContent className="flex min-h-72 flex-col items-center justify-center p-8 text-center">
            <div className="mb-4 rounded-full border border-border bg-muted/40 p-4">
              <BookOpenCheck className="h-7 w-7 text-muted-foreground" />
            </div>
            <h2 className="text-lg font-semibold">No knowledge updates waiting</h2>
            <p className="mt-2 max-w-xl text-sm leading-6 text-muted-foreground">
              New items appear here when Matrix or Bisq 2 support discussions reveal durable knowledge
              that should improve the internal LLM Wiki.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid min-w-0 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,0.95fr)_minmax(280px,0.75fr)]">
          <Card className="min-w-0 border-border/70 bg-card/90">
            <CardHeader className="pb-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <CardTitle className="text-base">LLM Wiki file review</CardTitle>
                  <p className="mt-1 text-sm text-muted-foreground">
                    {data.proposal.proposal_kind === "update_existing"
                      ? `Updating ${data.proposal.target_page_title || data.proposal.target_page_id}`
                      : "Creating a new internal LLM Wiki page"}
                  </p>
                  <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
                    This is the main object you approve. Read the complete page first, then edit unclear
                    wording directly in the diff. Open sources only when a claim needs proof.
                  </p>
                </div>
                {isDirty && (
                  <Badge variant="outline" className="border-amber-500/30 text-amber-600">
                    Unsaved edits
                  </Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="rounded-xl border border-border/70 bg-muted/15 p-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-foreground text-[11px] text-background">
                      1
                    </span>
                    Read file
                  </div>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <ArrowRight className="hidden h-4 w-4 text-muted-foreground sm:block" aria-hidden="true" />
                    <BookOpen className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                    Check sources if needed
                  </div>
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <ArrowRight className="hidden h-4 w-4 text-muted-foreground sm:block" aria-hidden="true" />
                    <CheckCircle2 className="h-4 w-4 text-emerald-500" aria-hidden="true" />
                    Approve or reject
                  </div>
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  Approval updates the internal LLM Wiki. It does not publish a public FAQ and it does not
                  immediately change autoresponse confidence thresholds.
                </p>
              </div>

              <section className="space-y-3">
                <div className="flex flex-col gap-3 rounded-xl border border-border/70 bg-muted/10 p-3">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <p className="text-sm font-medium">Review final LLM Wiki file</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        Diff & edit is the normal workflow. Click a proposed line to edit it without losing
                        the surrounding document context.
                      </p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        if (isDocumentDirty) {
                          void persistDocumentMarkdown();
                        } else {
                          void persistOperations();
                        }
                      }}
                      disabled={!isDirty || isSaving}
                      className="gap-2 lg:shrink-0"
                    >
                      {isSaving && <Loader2 className="h-4 w-4 animate-spin" />}
                      Save document
                    </Button>
                  </div>
                  <DocumentReviewModeSelector
                    value={documentMode}
                    onChange={setDocumentMode}
                  />
                </div>

                {documentMode === "diff" && (
                  <DocumentDiffViewer
                    rows={documentDiffRows}
                    editingLine={editingDocumentLine}
                    onEditLine={setEditingDocumentLine}
                    onChangeLine={updateDocumentLine}
                    onStopEditing={() => setEditingDocumentLine(null)}
                  />
                )}

                {documentMode === "preview" && (
                  <div className="max-h-[64vh] overflow-y-auto rounded-xl border border-border/70 bg-background p-4">
                    <MarkdownContent content={previewBody} className="text-sm" />
                  </div>
                )}

                <CompactKnowledgeSources sources={data.candidate.generated_answer_sources} />
              </section>

              <Collapsible open={showSupportingEdits} onOpenChange={setShowSupportingEdits}>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" className="w-full justify-between px-2">
                    <span className="inline-flex items-center gap-2">
                      <PencilLine className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                      Advanced: generated fields
                    </span>
                    <ChevronDown className={cn("h-4 w-4 transition-transform", showSupportingEdits && "rotate-180")} />
                  </Button>
                </CollapsibleTrigger>
                <CollapsibleContent className="space-y-3 pt-2">
                  <p className="rounded-lg border border-border/70 bg-muted/15 p-3 text-xs leading-5 text-muted-foreground">
                    These fields are the generator output behind the document. Most reviews should happen
                    directly in Diff & edit. Open this section only when you need to understand or repair
                    a specific generated field.
                  </p>
                  <section className="space-y-3">
                    <div>
                      <p className="text-sm font-medium">Primary generated changes</p>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        These fields shape what the support agent can retrieve and say later.
                      </p>
                    </div>
                    {primaryOperations.map((operation) => (
                      <OperationEditor key={operation.id} operation={operation} onChange={updateOperation} />
                    ))}
                  </section>
                  {supportingOperations.length > 0 && (
                    <section className="space-y-3">
                      <p className="text-sm font-medium">Supporting audit fields</p>
                      {supportingOperations.map((operation) => (
                        <OperationEditor key={operation.id} operation={operation} onChange={updateOperation} />
                      ))}
                    </section>
                  )}
                </CollapsibleContent>
              </Collapsible>

            </CardContent>
          </Card>

          <Card className="min-w-0 border-border/70 bg-card/80">
            <CardHeader className="pb-4">
              <div className="flex flex-wrap items-center gap-2">
                <ContextBadge
                  label="Channel"
                  value={data.candidate.source === "bisq2" ? "Bisq 2" : "Matrix"}
                  icon={MessageSquare}
                />
                {data.candidate.category && (
                  <ContextBadge label="Topic" value={data.candidate.category} icon={FileText} />
                )}
                <ContextBadge label="Protocol" value={protocolLabel(data.candidate.protocol)} icon={ShieldCheck} />
              </div>
              <CardTitle className="pt-2 text-base">Evidence from support chat</CardTitle>
              <p className="text-sm text-muted-foreground">
                Use this after reading the wiki page. Verify the original question, the human staff answer,
                and whether the bot draft would have been good enough.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <section className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">User question</p>
                <div className="rounded-lg border border-border/70 bg-muted/25 p-3 text-sm leading-6">
                  {data.candidate.edited_question_text || data.candidate.question_text}
                </div>
              </section>
              <section className="space-y-2">
                <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Human staff answer</p>
                <div className="rounded-lg border border-emerald-500/20 bg-emerald-500/5 p-3 text-sm leading-6 whitespace-pre-wrap">
                  {data.candidate.edited_staff_answer || data.candidate.staff_answer}
                </div>
              </section>
              {cleanedGeneratedAnswer && (
                <section className="space-y-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="inline-flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      <Bot className="h-3.5 w-3.5" aria-hidden="true" />
                      Bot draft at ingest
                    </p>
                    {generationConfidenceLabel && (
                      <Badge variant="outline" className="h-6 text-[11px]">
                        Confidence {generationConfidenceLabel}
                      </Badge>
                    )}
                  </div>
                  <div className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm leading-6">
                    <MarkdownContent content={cleanedGeneratedAnswer} />
                    {data.candidate.generated_answer_sources && data.candidate.generated_answer_sources.length > 0 && (
                      <div className="mt-3 border-t border-border/50 pt-3">
                        <SourceBadges sources={data.candidate.generated_answer_sources} />
                      </div>
                    )}
                  </div>
                  <div className="rounded-lg border border-dashed border-border bg-muted/15 p-3">
                    <div className="space-y-3">
                      <div>
                        <p className="text-sm font-medium leading-5">Could the bot have sent this answer?</p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          Records an answer-quality signal only. It does not approve the LLM Wiki change or change channel thresholds.
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-2">
                        <Button
                          variant={answerRating === "needs_improvement" ? "default" : "outline"}
                          size="sm"
                          onClick={() => void handleRateGeneratedAnswer("needs_improvement")}
                          disabled={ratingLoading !== null}
                          className={cn(
                            "w-full justify-center gap-1.5 px-2 text-xs",
                            answerRating === "needs_improvement"
                              ? "bg-amber-600 text-white hover:bg-amber-700"
                              : "text-amber-700 hover:bg-amber-50 hover:text-amber-800",
                          )}
                        >
                          {ratingLoading === "needs_improvement" ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <ThumbsDown className="h-3.5 w-3.5" />
                          )}
                          Needs work
                        </Button>
                        <Button
                          variant={answerRating === "good" ? "default" : "outline"}
                          size="sm"
                          onClick={() => void handleRateGeneratedAnswer("good")}
                          disabled={ratingLoading !== null}
                          className={cn(
                            "w-full justify-center gap-1.5 px-2 text-xs",
                            answerRating === "good"
                              ? "bg-emerald-600 text-white hover:bg-emerald-700"
                              : "text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800",
                          )}
                        >
                          {ratingLoading === "good" ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" />
                          ) : (
                            <ThumbsUp className="h-3.5 w-3.5" />
                          )}
                          Good enough
                        </Button>
                      </div>
                    </div>
                  </div>
                </section>
              )}
              {conversation.length > 0 && (
                <Collapsible open={showConversation} onOpenChange={setShowConversation}>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" className="w-full justify-between px-2">
                      Full support thread
                      <ChevronDown className={cn("h-4 w-4 transition-transform", showConversation && "rotate-180")} />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="space-y-2">
                    {conversation.map((message, index) => (
                      <div key={`${message.timestamp}-${index}`} className="rounded-lg border border-border/60 bg-muted/20 p-3">
                        <div className="mb-1 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                          <span>{message.sender || "participant"}</span>
                          <span>{message.timestamp ? formatDate(message.timestamp) : ""}</span>
                        </div>
                        <p className="whitespace-pre-wrap text-sm leading-6">{message.content}</p>
                      </div>
                    ))}
                  </CollapsibleContent>
                </Collapsible>
              )}
            </CardContent>
          </Card>

          <aside className="order-3 min-w-0 space-y-4 xl:sticky xl:top-6 xl:max-h-[calc(100vh-3rem)] xl:overflow-y-auto xl:pr-1">
            <Card className="border-border/70 bg-card/80">
              <CardHeader className="pb-3">
                <CardTitle className="text-base">Decision</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Approve only when the final wiki page should become retrievable support knowledge.
                  Use FAQ only for a durable public one-question answer.
                </p>
              </CardHeader>
              <CardContent className="space-y-3 p-4">
                <Button
                  onClick={handleApprove}
                  disabled={hasBlockingFailure || actionLoading === "approve"}
                  className="w-full gap-2"
                >
                  {actionLoading === "approve" ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <Sparkles className="h-4 w-4" />
                  )}
                  Approve LLM Wiki change
                </Button>
                <div className="grid grid-cols-2 gap-2">
                  <Button variant="outline" onClick={handleSkip} disabled={actionLoading === "skip"}>
                    Skip
                  </Button>
                  <Button variant="outline" onClick={handleReject} disabled={actionLoading === "reject"}>
                    Reject
                  </Button>
                </div>
                <Collapsible open={showFaqFallback} onOpenChange={setShowFaqFallback}>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" className="w-full justify-between text-muted-foreground">
                      <span className="inline-flex items-center gap-2">
                        <HelpCircle className="h-4 w-4" />
                        Optional public FAQ
                      </span>
                      <ChevronDown className={cn("h-4 w-4 transition-transform", showFaqFallback && "rotate-180")} />
                    </Button>
                  </CollapsibleTrigger>
                  <CollapsibleContent className="space-y-3 rounded-lg border border-border/70 bg-muted/15 p-3">
                    <p className="text-xs leading-5 text-muted-foreground">
                      Use this only when the support answer should become a short public FAQ.
                      The default path is to improve the internal LLM Wiki.
                    </p>
                    <Button
                      variant="outline"
                      className="w-full gap-2"
                      onClick={handleCreateFaq}
                      disabled={actionLoading === "faq"}
                    >
                      {actionLoading === "faq" ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <HelpCircle className="h-4 w-4" />
                      )}
                      Create public FAQ
                    </Button>
                  </CollapsibleContent>
                </Collapsible>
              </CardContent>
            </Card>

            <Card className="border-border/70 bg-card/80">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <ShieldCheck className="h-4 w-4 text-emerald-500" />
                  Safety checks
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.proposal.checks.map((check) => (
                  <CheckPill key={check.code} check={check} />
                ))}
              </CardContent>
            </Card>
          </aside>
        </div>
      )}
    </AdminQueueShell>
  );
}
