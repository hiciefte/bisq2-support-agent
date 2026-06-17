import { makeAuthenticatedRequest } from "@/lib/auth";

export interface SupportReportPeriod {
  start_date: string;
  end_date: string;
  period_label: string | null;
  reviewer: string | null;
  date_basis: string;
}

export interface SupportReportSummary {
  total_reviews: number;
  approved: number;
  rejected: number;
  pages_touched: number;
  new_pages: number;
  existing_page_updates: number;
}

export interface SupportReportReviewer {
  reviewer: string;
  total_reviews: number;
  approved: number;
  rejected: number;
}

export interface SupportReportPage {
  page_id: string;
  title: string;
  total_reviews: number;
  approved: number;
  rejected: number;
  last_reviewed_at: string | null;
  proposal_kinds: Record<string, number>;
}

export interface SupportReportItem {
  proposal_id: number;
  candidate_id: number;
  target_page_id: string;
  target_page_title: string;
  proposal_kind: string;
  status: "approved" | "rejected";
  reviewed_by: string | null;
  reviewed_at: string | null;
  rejection_reason: string | null;
  source: string | null;
  routing: string | null;
  protocol: string | null;
  category: string | null;
  question_text: string | null;
  staff_sender: string | null;
}

export interface SupportReportFutureSection {
  key: string;
  label: string;
  status: "planned";
  total_reviews: number;
}

export interface SupportWorkReport {
  period: SupportReportPeriod;
  summary: SupportReportSummary;
  reviewers: SupportReportReviewer[];
  pages: SupportReportPage[];
  items: SupportReportItem[];
  future_sections: SupportReportFutureSection[];
  report_markdown: string;
}

export interface SupportWorkReportFilters {
  startDate: string;
  endDate: string;
  reviewer?: string;
  periodLabel?: string;
}

export function buildSupportWorkReportPath(filters: SupportWorkReportFilters): string {
  const params = new URLSearchParams();
  params.set("start_date", filters.startDate);
  params.set("end_date", filters.endDate);
  const reviewer = filters.reviewer?.trim();
  const periodLabel = filters.periodLabel?.trim();
  if (reviewer) {
    params.set("reviewer", reviewer);
  }
  if (periodLabel) {
    params.set("period_label", periodLabel);
  }
  return `/admin/reports/support-work?${params.toString()}`;
}

export async function fetchSupportWorkReport(
  filters: SupportWorkReportFilters,
): Promise<SupportWorkReport> {
  const response = await makeAuthenticatedRequest(buildSupportWorkReportPath(filters));
  if (!response.ok) {
    const payload = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(payload?.detail || `Report request failed with status ${response.status}`);
  }
  return (await response.json()) as SupportWorkReport;
}
