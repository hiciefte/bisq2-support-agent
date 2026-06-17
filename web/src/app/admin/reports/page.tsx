"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  CalendarDays,
  CheckCircle2,
  ClipboardCopy,
  FileText,
  Loader2,
  RefreshCw,
  UserRound,
  XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import {
  fetchSupportWorkReport,
  type SupportReportItem,
  type SupportWorkReport,
} from "@/lib/adminReportsApi";
import { cn } from "@/lib/utils";

type CopyState = "idle" | "copied" | "failed";

function toDateInputValue(date: Date): string {
  return date.toISOString().slice(0, 10);
}

function defaultReportRange(): { startDate: string; endDate: string } {
  const end = new Date();
  const start = new Date(end);
  start.setUTCDate(start.getUTCDate() - 30);
  return {
    startDate: toDateInputValue(start),
    endDate: toDateInputValue(end),
  };
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "Not recorded";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatLabel(value: string | null): string {
  if (!value) {
    return "Unknown";
  }
  return value
    .replace(/_/g, " ")
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

async function copyTextToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "fixed";
  textArea.style.opacity = "0";
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("Clipboard fallback failed");
  }
}

function StatusBadge({ status }: { status: SupportReportItem["status"] }) {
  const isApproved = status === "approved";
  return (
    <Badge
      variant="outline"
      className={cn(
        "border px-2 py-0.5 text-[11px] font-semibold",
        isApproved
          ? "border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-200"
          : "border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-200",
      )}
    >
      {isApproved ? (
        <CheckCircle2 className="mr-1 h-3 w-3" aria-hidden="true" />
      ) : (
        <XCircle className="mr-1 h-3 w-3" aria-hidden="true" />
      )}
      {formatLabel(status)}
    </Badge>
  );
}

function SummaryCell({
  label,
  value,
  description,
}: {
  label: string;
  value: number;
  description: string;
}) {
  return (
    <div className="rounded-lg border bg-muted/20 p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-2 text-2xl font-semibold tracking-tight">{value}</div>
      <div className="mt-1 text-xs text-muted-foreground">{description}</div>
    </div>
  );
}

export default function AdminReportsPage() {
  const initialRange = useMemo(defaultReportRange, []);
  const [startDate, setStartDate] = useState(initialRange.startDate);
  const [endDate, setEndDate] = useState(initialRange.endDate);
  const [reviewer, setReviewer] = useState("");
  const [periodLabel, setPeriodLabel] = useState("");
  const [report, setReport] = useState<SupportWorkReport | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copyState, setCopyState] = useState<CopyState>("idle");
  const didAutoLoadRef = useRef(false);
  const copyResetTimeoutRef = useRef<number | null>(null);

  const loadReport = useCallback(async () => {
    if (!startDate || !endDate) {
      setError("Choose a start and end date before generating the report.");
      return;
    }
    setIsLoading(true);
    setError(null);
    setCopyState("idle");
    try {
      const payload = await fetchSupportWorkReport({
        startDate,
        endDate,
        reviewer,
        periodLabel,
      });
      setReport(payload);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Failed to generate the support work report.",
      );
    } finally {
      setIsLoading(false);
    }
  }, [endDate, periodLabel, reviewer, startDate]);

  useEffect(() => {
    if (didAutoLoadRef.current) {
      return;
    }
    didAutoLoadRef.current = true;
    void loadReport();
  }, [loadReport]);

  const hasReviewedWork = (report?.summary.total_reviews ?? 0) > 0;

  const handleCopy = async () => {
    if (!report?.report_markdown) {
      return;
    }
    if (copyResetTimeoutRef.current !== null) {
      window.clearTimeout(copyResetTimeoutRef.current);
      copyResetTimeoutRef.current = null;
    }
    try {
      await copyTextToClipboard(report.report_markdown);
      setCopyState("copied");
      copyResetTimeoutRef.current = window.setTimeout(() => {
        setCopyState("idle");
        copyResetTimeoutRef.current = null;
      }, 2500);
    } catch {
      setCopyState("failed");
    }
  };

  useEffect(() => {
    return () => {
      if (copyResetTimeoutRef.current !== null) {
        window.clearTimeout(copyResetTimeoutRef.current);
      }
    };
  }, []);

  return (
    <div className="min-h-screen bg-background">
      <div className="mx-auto flex w-full max-w-7xl flex-col gap-6 p-4 pt-16 sm:p-6 lg:p-8 lg:pt-8">
        <header className="flex flex-col gap-4 border-b pb-6 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <Badge variant="secondary" className="mb-3 gap-1.5">
              <FileText className="h-3.5 w-3.5" aria-hidden="true" />
              Reporting
            </Badge>
            <h1 className="text-3xl font-semibold tracking-tight">
              Support work reports
            </h1>
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              Build a compensation-ready summary from reviewed support work. The
              first report covers LLM Wiki review decisions; handled escalations
              can be added here later without changing the workflow.
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            className="w-full gap-2 sm:w-auto"
            onClick={() => void loadReport()}
            disabled={isLoading}
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <RefreshCw className="h-4 w-4" aria-hidden="true" />
            )}
            Refresh report
          </Button>
        </header>

        <Card className="shadow-sm">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CalendarDays className="h-5 w-5 text-primary" aria-hidden="true" />
              Report period
            </CardTitle>
            <CardDescription>
              Use the calendar dates that map to the compensation cycle. Add the
              Bitcoin block range as the period label when you share the report.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1fr_1fr_1fr_1.4fr_auto]">
              <div className="space-y-2">
                <Label htmlFor="report-start">Start date</Label>
                <Input
                  id="report-start"
                  type="date"
                  value={startDate}
                  onChange={(event) => setStartDate(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="report-end">End date</Label>
                <Input
                  id="report-end"
                  type="date"
                  value={endDate}
                  onChange={(event) => setEndDate(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="report-reviewer">Reviewer</Label>
                <Input
                  id="report-reviewer"
                  value={reviewer}
                  placeholder="All reviewers"
                  onChange={(event) => setReviewer(event.target.value)}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="report-label">Period label or block range</Label>
                <Input
                  id="report-label"
                  value={periodLabel}
                  placeholder="Cycle 62, blocks 840000 to 842000"
                  onChange={(event) => setPeriodLabel(event.target.value)}
                />
              </div>
              <div className="flex items-end">
                <Button
                  type="button"
                  className="w-full"
                  onClick={() => void loadReport()}
                  disabled={isLoading}
                >
                  Generate
                </Button>
              </div>
            </div>
            <p className="mt-3 text-xs text-muted-foreground">
              Dates are evaluated against the stored review timestamp by UTC
              day. This report does not calculate compensation amounts.
            </p>
          </CardContent>
        </Card>

        {error && (
          <div
            role="alert"
            className="flex items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            <AlertCircle className="mt-0.5 h-4 w-4" aria-hidden="true" />
            <div>{error}</div>
          </div>
        )}

        {report && (
          <section className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(360px,0.65fr)]">
            <div className="space-y-6">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <SummaryCell
                  label="LLM Wiki reviews"
                  value={report.summary.total_reviews}
                  description="Approved and rejected decisions"
                />
                <SummaryCell
                  label="Approved"
                  value={report.summary.approved}
                  description="Promoted to reviewed knowledge"
                />
                <SummaryCell
                  label="Rejected"
                  value={report.summary.rejected}
                  description="Reviewed but not promoted"
                />
                <SummaryCell
                  label="Pages touched"
                  value={report.summary.pages_touched}
                  description="Unique LLM Wiki pages"
                />
              </div>

              <Card className="shadow-sm">
                <CardHeader className="pb-3">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div>
                      <CardTitle>Work modules</CardTitle>
                      <CardDescription>
                        One report can grow to cover more reviewed support work.
                      </CardDescription>
                    </div>
                    <Badge variant="outline" className="w-fit">
                      {report.period.start_date} to {report.period.end_date}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-lg border bg-secondary/40 p-4">
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                      <div>
                        <div className="font-semibold">LLM Wiki reviews</div>
                        <p className="text-sm text-muted-foreground">
                          Human decisions on proposed knowledge changes.
                        </p>
                      </div>
                      <Badge className="w-fit">
                        {report.summary.total_reviews} reviewed
                      </Badge>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-xs text-muted-foreground">
                      <span>{report.summary.new_pages} new pages</span>
                      <span aria-hidden="true">/</span>
                      <span>
                        {report.summary.existing_page_updates} existing page updates
                      </span>
                    </div>
                  </div>
                  {report.future_sections.map((section) => (
                    <div
                      key={section.key}
                      className="rounded-lg border border-dashed bg-muted/20 p-4"
                    >
                      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div>
                          <div className="font-semibold">{section.label}</div>
                          <p className="text-sm text-muted-foreground">
                            Planned for the same reporting section once the
                            escalation workflow has stable review totals.
                          </p>
                        </div>
                        <Badge variant="outline" className="w-fit">
                          Planned
                        </Badge>
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card className="shadow-sm">
                <CardHeader>
                  <CardTitle>Pages reviewed</CardTitle>
                  <CardDescription>
                    LLM Wiki pages touched during the selected period.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {hasReviewedWork ? (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Page</TableHead>
                          <TableHead className="hidden md:table-cell">Kind</TableHead>
                          <TableHead className="text-right">Reviewed</TableHead>
                          <TableHead className="hidden text-right sm:table-cell">
                            Approved
                          </TableHead>
                          <TableHead className="hidden text-right sm:table-cell">
                            Rejected
                          </TableHead>
                          <TableHead className="hidden lg:table-cell">
                            Last review
                          </TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {report.pages.map((page) => (
                          <TableRow key={page.page_id}>
                            <TableCell>
                              <div className="font-medium">{page.title}</div>
                              <div className="font-mono text-xs text-muted-foreground">
                                {page.page_id}
                              </div>
                            </TableCell>
                            <TableCell className="hidden md:table-cell">
                              <div className="flex flex-wrap gap-1.5">
                                {Object.entries(page.proposal_kinds).map(
                                  ([kind, count]) => (
                                    <Badge key={kind} variant="outline">
                                      {formatLabel(kind)}: {count}
                                    </Badge>
                                  ),
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="text-right font-medium">
                              {page.total_reviews}
                            </TableCell>
                            <TableCell className="hidden text-right sm:table-cell">
                              {page.approved}
                            </TableCell>
                            <TableCell className="hidden text-right sm:table-cell">
                              {page.rejected}
                            </TableCell>
                            <TableCell className="hidden text-muted-foreground lg:table-cell">
                              {formatDateTime(page.last_reviewed_at)}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  ) : (
                    <div className="rounded-lg border bg-muted/20 p-6 text-sm text-muted-foreground">
                      No LLM Wiki reviews were recorded for this period. Adjust
                      the dates or remove the reviewer filter.
                    </div>
                  )}
                </CardContent>
              </Card>

              <Card className="shadow-sm">
                <CardHeader>
                  <CardTitle>Recent decisions</CardTitle>
                  <CardDescription>
                    Audit entries behind the totals, ordered by latest review.
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  {report.items.length > 0 ? (
                    <div className="divide-y rounded-lg border">
                      {report.items.slice(0, 12).map((item) => (
                        <div
                          key={`${item.proposal_id}-${item.candidate_id}`}
                          className="grid gap-3 p-4 lg:grid-cols-[minmax(0,1fr)_auto]"
                        >
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <StatusBadge status={item.status} />
                              <Badge variant="outline">
                                {formatLabel(item.source)}
                              </Badge>
                              <Badge variant="outline">
                                {formatLabel(item.routing)}
                              </Badge>
                            </div>
                            <div className="mt-2 font-medium">
                              {item.target_page_title}
                            </div>
                            <div className="mt-1 line-clamp-2 text-sm text-muted-foreground">
                              {item.question_text || "Question text not stored"}
                            </div>
                          </div>
                          <div className="flex flex-col gap-1 text-sm text-muted-foreground lg:items-end">
                            <span className="flex items-center gap-1.5">
                              <UserRound className="h-3.5 w-3.5" aria-hidden="true" />
                              {item.reviewed_by || "Unknown reviewer"}
                            </span>
                            <span>{formatDateTime(item.reviewed_at)}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-lg border bg-muted/20 p-6 text-sm text-muted-foreground">
                      No decisions to show for this period.
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>

            <aside className="space-y-6">
              <Card className="sticky top-6 shadow-sm">
                <CardHeader>
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <CardTitle>Shareable Markdown</CardTitle>
                      <CardDescription>
                        Copy this into the compensation request and add any
                        personal context outside the generated report.
                      </CardDescription>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="gap-2"
                      onClick={() => void handleCopy()}
                      disabled={!report.report_markdown}
                    >
                      <ClipboardCopy className="h-4 w-4" aria-hidden="true" />
                      {copyState === "copied" ? "Copied" : "Copy"}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="space-y-3">
                  {copyState === "failed" && (
                    <div
                      role="alert"
                      className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive"
                    >
                      Clipboard access failed. Select the Markdown text and copy
                      it manually.
                    </div>
                  )}
                  <Textarea
                    readOnly
                    value={report.report_markdown}
                    className="min-h-[520px] resize-y font-mono text-xs leading-5"
                    aria-label="Shareable Markdown report"
                  />
                </CardContent>
              </Card>
            </aside>
          </section>
        )}
      </div>
    </div>
  );
}
