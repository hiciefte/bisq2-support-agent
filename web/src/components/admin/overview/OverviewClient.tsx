"use client";

import Link from "next/link";
import { type ReactNode, useCallback, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Progress } from "@/components/ui/progress";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { ChannelAutoresponseCard } from "@/components/admin/overview/ChannelAutoresponseCard";
import { OverviewSkeleton } from "@/components/admin/overview/OverviewSkeleton";
import type { OverviewInitialData } from "@/components/admin/overview/types";
import { type ChannelId } from "@/components/admin/overview/types";
import { useChannelAutoresponsePolicies } from "@/hooks/useChannelAutoresponsePolicies";
import { useOverviewData } from "@/hooks/useOverviewData";
import { usePeriodStorage } from "@/hooks/usePeriodStorage";
import { cn } from "@/lib/utils";
import { type Period } from "@/types/dashboard";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  Clock,
  FileCheck,
  Gauge,
  Loader2,
  MessageSquare,
  RefreshCw,
  Sparkles,
  TrendingDown,
  TrendingUp,
  Users,
} from "lucide-react";

const PERIOD_OPTIONS: Array<{ value: Period; label: string }> = [
  { value: "24h", label: "24H" },
  { value: "7d", label: "7D" },
  { value: "30d", label: "30D" },
];

interface OverviewClientProps {
  initialData: OverviewInitialData;
}

export function OverviewClient({ initialData }: OverviewClientProps) {
  const { period, dateRange, updatePeriod, isInitialized } = usePeriodStorage("7d");
  const [isPolicyOpen, setIsPolicyOpen] = useState(false);

  const {
    dashboardData,
    actionCounts,
    isActionCountsAvailable,
    totalOpenActions,
    isLoading,
    isRefreshing,
    error,
    refresh,
  } = useOverviewData({
    period,
    dateRange,
    isInitialized,
    initialDashboardData: initialData.dashboardData,
    initialActionCounts: initialData.actionCounts,
  });

  const {
    policies: autoresponsePolicies,
    isLoading: isAutoresponseLoading,
    isSavingByChannel,
    error: autoresponseError,
    refresh: refreshAutoresponsePolicies,
    setChannelMode,
  } = useChannelAutoresponsePolicies(initialData.channelPolicies);

  const handleRefresh = useCallback(() => {
    void Promise.all([
      refresh({ background: true }),
      refreshAutoresponsePolicies(),
    ]);
  }, [refresh, refreshAutoresponsePolicies]);

  const handleModeChange = useCallback(
    (channelId: ChannelId, mode: "off" | "review" | "auto") => {
      void setChannelMode(channelId, mode);
    },
    [setChannelMode],
  );

  const formatResponseTime = (seconds: number | null | undefined) => {
    if (seconds === null || seconds === undefined) return "N/A";
    return seconds < 1 ? `${Math.round(seconds * 1000)}ms` : `${seconds.toFixed(1)}s`;
  };

  const formatUptime = (seconds: number | null | undefined) => {
    if (seconds === null || seconds === undefined || Number.isNaN(seconds) || seconds < 0) {
      return "N/A";
    }
    const totalSeconds = Math.floor(seconds);
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);

    if (days > 0) {
      return `${days}d ${hours}h`;
    }
    if (hours > 0) {
      return `${hours}h ${minutes}m`;
    }
    if (minutes > 0) {
      return `${minutes}m`;
    }
    return `${totalSeconds}s`;
  };

  const formatRelativeTime = (isoTimestamp: string) => {
    const timestamp = new Date(isoTimestamp).getTime();
    const now = Date.now();
    const diffMs = Math.max(0, now - timestamp);
    const diffMinutes = Math.floor(diffMs / 60000);

    if (diffMinutes < 1) return "just now";
    if (diffMinutes < 60) return `${diffMinutes}m ago`;

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours}h ago`;

    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  };

  const getTrendIcon = (trend: number) => {
    if (Math.abs(trend) < 0.1) return null;
    return trend > 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />;
  };

  const getTrendColor = (trend: number, isGood: "positive" | "negative") => {
    if (Math.abs(trend) < 0.1) return "text-muted-foreground";
    const isPositiveChange = trend > 0;
    const shouldBeGreen =
      (isGood === "positive" && isPositiveChange)
      || (isGood === "negative" && !isPositiveChange);
    return shouldBeGreen ? "text-green-600" : "text-red-600";
  };

  const formatNumber = (value: number) => new Intl.NumberFormat("en-US").format(value);
  const helpfulRateValue = dashboardData ? Math.max(0, Math.min(100, dashboardData.helpful_rate)) : 0;
  const hasActionBacklog = isActionCountsAvailable && totalOpenActions > 0;

  const queueSummaryLabel = useMemo(() => {
    if (!isActionCountsAvailable) {
      return "Action queue syncing";
    }
    if (hasActionBacklog) {
      return `${totalOpenActions} items need attention`;
    }
    return "No pending admin actions";
  }, [hasActionBacklog, isActionCountsAvailable, totalOpenActions]);

  if (isLoading && !dashboardData) {
    return <OverviewSkeleton />;
  }

  if (!dashboardData) {
    return (
      <div className="p-4 md:p-8 pt-16 lg:pt-8">
        <div className="mx-auto max-w-7xl">
          <Card className="border-red-500/30 bg-red-500/5">
            <CardContent className="py-12 text-center space-y-4">
              <div className="inline-flex items-center gap-2 text-red-300">
                <AlertTriangle className="h-5 w-5" />
                <span className="font-medium">Dashboard overview failed to load</span>
              </div>
              <p className="text-sm text-red-200/90">{error ?? "No dashboard data available."}</p>
              <Button onClick={handleRefresh} variant="outline">
                <RefreshCw className="h-4 w-4 mr-2" />
                Retry
              </Button>
            </CardContent>
          </Card>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-8 pt-16 lg:pt-8">
      <div className="mx-auto max-w-7xl space-y-6">
        {error ? (
          <Card className="border-amber-500/30 bg-amber-500/5">
            <CardContent className="py-3">
              <div className="inline-flex items-center gap-2 text-xs text-amber-200/90">
                <AlertTriangle className="h-4 w-4" />
                Overview refresh had errors. Showing the latest successful data.
              </div>
            </CardContent>
          </Card>
        ) : null}

        <section className="relative overflow-hidden rounded-2xl border border-border/70 bg-gradient-to-br from-emerald-500/10 via-background to-blue-500/10 px-5 py-5 shadow-sm md:px-6">
          <div className="pointer-events-none absolute -right-16 -top-16 h-48 w-48 rounded-full bg-emerald-500/10 blur-3xl" />
          <div className="pointer-events-none absolute -bottom-16 -left-16 h-40 w-40 rounded-full bg-blue-500/10 blur-3xl" />

          <div className="relative flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
            <div className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="text-2xl font-semibold tracking-tight md:text-3xl">Admin Overview</h1>
                {dashboardData.fallback ? (
                  <Badge variant="outline" className="border-amber-500/40 bg-amber-500/10 text-amber-300">
                    Fallback data
                  </Badge>
                ) : null}
                <Badge
                  variant="secondary"
                  className={cn(
                    "gap-1.5 border text-xs",
                    hasActionBacklog
                      ? "bg-amber-500/20 text-amber-300 border-amber-500/25"
                      : "bg-emerald-500/20 text-emerald-300 border-emerald-500/25",
                  )}
                >
                  <Sparkles className="h-3.5 w-3.5" />
                  {queueSummaryLabel}
                </Badge>
              </div>
              <p className="max-w-2xl text-sm text-muted-foreground md:text-base">
                Action-first snapshot with live workload and channel runtime controls.
              </p>
              <div className="flex flex-wrap items-center gap-2 pt-1">
                <Badge variant="outline" className="gap-1.5 text-muted-foreground">
                  <Clock className="h-3.5 w-3.5" />
                  Updated {formatRelativeTime(dashboardData.last_updated)}
                </Badge>
              </div>
            </div>

            <div className="flex flex-col gap-2 sm:items-end">
              <ToggleGroup
                type="single"
                value={period}
                onValueChange={(value) => {
                  if (value) {
                    updatePeriod(value as Period, undefined);
                  }
                }}
                className="justify-start sm:justify-end"
              >
                {PERIOD_OPTIONS.map((option) => (
                  <ToggleGroupItem
                    key={option.value}
                    value={option.value}
                    variant="outline"
                    size="sm"
                    className="min-w-[52px] border-border/70 bg-background/70 text-xs font-medium"
                    aria-label={`Set dashboard period to ${option.label}`}
                  >
                    {option.label}
                  </ToggleGroupItem>
                ))}
              </ToggleGroup>
              <Button
                onClick={handleRefresh}
                variant="ghost"
                size="sm"
                disabled={isRefreshing}
                className="justify-start text-muted-foreground sm:justify-end"
              >
                {isRefreshing ? (
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                ) : (
                  <RefreshCw className="h-4 w-4 mr-2" />
                )}
                Sync now
              </Button>
            </div>
          </div>
        </section>

        <section>
          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-2">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-lg">Admin Action Queue</CardTitle>
                <Badge
                  variant="secondary"
                  className={cn(
                    "text-xs border",
                    hasActionBacklog
                      ? "bg-amber-500/20 text-amber-300 border-amber-500/30"
                      : "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
                  )}
                >
                  {hasActionBacklog ? "Needs attention" : "Clear"}
                </Badge>
              </div>
              <p className="text-sm text-muted-foreground">
                Prioritized work across Quality Signals, Escalations, FAQs, and Training.
              </p>
            </CardHeader>
            <CardContent className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <ActionTaskCard
                icon={<MessageSquare className="h-4 w-4 text-violet-300" />}
                label="Quality Signals"
                count={actionCounts.actionable_signals}
                description={
                  actionCounts.actionable_signals > 0
                    ? "Asker-reported negative signals not yet covered by an escalation."
                    : "No uncovered negative asker signals right now."
                }
                href="/admin/manage-feedback"
                cta="Review signals"
                detail={`Covered ${actionCounts.covered_signals} · Total ${actionCounts.total_signals}`}
              />

              <ActionTaskCard
                icon={<AlertTriangle className="h-4 w-4 text-amber-300" />}
                label="Escalations"
                count={actionCounts.open_escalations}
                description={
                  actionCounts.open_escalations > 0
                    ? "Escalations waiting for triage or response."
                    : "No escalations currently waiting."
                }
                href="/admin/escalations"
                cta="Open escalations"
                detail={`Pending ${actionCounts.pending_escalations}`}
              />

              <ActionTaskCard
                icon={<FileCheck className="h-4 w-4 text-blue-300" />}
                label="FAQs"
                count={actionCounts.unverified_faqs}
                description={
                  actionCounts.unverified_faqs > 0
                    ? "Draft or updated FAQs waiting for verification."
                    : "No FAQ verification backlog right now."
                }
                href="/admin/manage-faqs"
                cta="Verify FAQs"
                detail={`Total FAQs ${formatNumber(dashboardData.total_faqs)}`}
              />

              <ActionTaskCard
                icon={<Gauge className="h-4 w-4 text-emerald-300" />}
                label="Training"
                count={actionCounts.training_queue}
                status={isActionCountsAvailable ? "known" : "unknown"}
                description={
                  !isActionCountsAvailable
                    ? "Training queue status is temporarily unavailable."
                    : actionCounts.training_queue > 0
                    ? "Candidate answers waiting in training queues."
                    : "Training queues are currently clear."
                }
                href="/admin/training"
                cta="Open training"
                detail={
                  !isActionCountsAvailable
                    ? "Open Training for authoritative queue counts."
                    : actionCounts.training_queue > 0
                    ? "Unified training queue has pending items."
                    : "No training actions waiting."
                }
              />
            </CardContent>
          </Card>
        </section>

        <section className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Helpful Rate</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-3xl font-semibold tracking-tight tabular-nums">
                  {dashboardData.helpful_rate.toFixed(1)}%
                </div>
                <Users className="h-5 w-5 text-emerald-400" />
              </div>
              <Progress value={helpfulRateValue} className="h-1.5 bg-emerald-500/20" />
              <div className={cn("flex items-center gap-1 text-xs", getTrendColor(dashboardData.helpful_rate_trend, "positive"))}>
                {getTrendIcon(dashboardData.helpful_rate_trend)}
                <span className="tabular-nums">
                  {dashboardData.helpful_rate_trend > 0 ? "+" : ""}
                  {dashboardData.helpful_rate_trend.toFixed(1)}% {dashboardData.period_label}
                </span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Average Response Time</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-3xl font-semibold tracking-tight tabular-nums">
                  {formatResponseTime(dashboardData.average_response_time)}
                </div>
                <Gauge className="h-5 w-5 text-blue-400" />
              </div>
              <div className="text-xs text-muted-foreground">
                P95: <span className="tabular-nums">{formatResponseTime(dashboardData.p95_response_time)}</span>
              </div>
              <div className={cn("flex items-center gap-1 text-xs", getTrendColor(dashboardData.response_time_trend, "negative"))}>
                {getTrendIcon(dashboardData.response_time_trend)}
                <span className="tabular-nums">
                  {dashboardData.response_time_trend > 0 ? "+" : ""}
                  {formatResponseTime(Math.abs(dashboardData.response_time_trend))} {dashboardData.period_label}
                </span>
              </div>
            </CardContent>
          </Card>

          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">Feedback Volume</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-3xl font-semibold tracking-tight tabular-nums">
                  {formatNumber(dashboardData.total_feedback)}
                </div>
                <MessageSquare className="h-5 w-5 text-violet-400" />
              </div>
              <div className="text-xs text-muted-foreground">
                Total queries: <span className="tabular-nums">{formatNumber(dashboardData.total_queries)}</span>
              </div>
              <Badge variant="outline" className="text-xs text-muted-foreground">
                {dashboardData.period_label}
              </Badge>
            </CardContent>
          </Card>

          <Card className="border-border/70 bg-card/70">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-medium text-muted-foreground">System Uptime</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <div className="text-3xl font-semibold tracking-tight tabular-nums">
                  {formatUptime(dashboardData.system_uptime)}
                </div>
                <CheckCircle2 className="h-5 w-5 text-emerald-400" />
              </div>
              <div className="text-xs text-muted-foreground">
                API process uptime
              </div>
              <div className="text-xs text-muted-foreground">
                FAQs created: <span className="tabular-nums">{formatNumber(dashboardData.total_faqs_created)}</span>
              </div>
            </CardContent>
          </Card>
        </section>

        <section>
          <Collapsible open={isPolicyOpen} onOpenChange={setIsPolicyOpen}>
            <Card className="border-border/70 bg-card/70">
              <CardHeader className="pb-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <CardTitle className="text-lg">Channel Runtime Policy</CardTitle>
                    <p className="text-sm text-muted-foreground">
                      Manage channel-level AI processing and delivery behavior.
                    </p>
                  </div>
                  <CollapsibleTrigger asChild>
                    <Button variant="outline" size="sm">
                      {isPolicyOpen ? "Hide controls" : "Show controls"}
                      <ChevronDown
                        className={cn(
                          "ml-2 h-4 w-4 transition-transform duration-200",
                          isPolicyOpen ? "rotate-180" : "rotate-0",
                        )}
                      />
                    </Button>
                  </CollapsibleTrigger>
                </div>
              </CardHeader>
              <CollapsibleContent>
                <CardContent className="pt-0">
                  <ChannelAutoresponseCard
                    policies={autoresponsePolicies}
                    isLoading={isAutoresponseLoading}
                    isSavingByChannel={isSavingByChannel}
                    error={autoresponseError}
                    onModeChange={handleModeChange}
                    onRetry={() => {
                      void refreshAutoresponsePolicies();
                    }}
                  />
                </CardContent>
              </CollapsibleContent>
            </Card>
          </Collapsible>
        </section>

        <footer className="text-xs text-muted-foreground text-center">
          Last updated: {new Date(dashboardData.last_updated).toLocaleString()}
        </footer>
      </div>
    </div>
  );
}

interface ActionTaskCardProps {
  icon: ReactNode;
  label: string;
  count: number;
  status?: "known" | "unknown";
  description: string;
  href: string;
  cta: string;
  detail?: string;
}

function ActionTaskCard({ icon, label, count, status = "known", description, href, cta, detail }: ActionTaskCardProps) {
  const hasWork = status === "known" && count > 0;
  const countLabel = status === "unknown" ? "—" : count;

  return (
    <article
      className={cn(
        "rounded-xl border p-4 transition-colors",
        status === "unknown"
          ? "border-border/70 bg-background/40"
          : null,
        hasWork
          ? "border-amber-500/30 bg-amber-500/5"
          : "border-border/70 bg-background/40",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1.5">
          <div className="inline-flex items-center gap-2 text-sm font-medium">
            {icon}
            {label}
          </div>
          <div className="text-3xl font-semibold tracking-tight tabular-nums">{countLabel}</div>
        </div>
        <Badge
          variant="secondary"
          className={cn(
            "text-xs",
            status === "unknown"
              ? "bg-muted text-muted-foreground border border-border"
              : null,
            hasWork
              ? "bg-amber-500/20 text-amber-300 border border-amber-500/30"
              : "bg-emerald-500/20 text-emerald-300 border border-emerald-500/30",
          )}
        >
          {status === "unknown" ? "Syncing" : hasWork ? "Needs action" : "Clear"}
        </Badge>
      </div>

      <p className="mt-2 text-sm text-muted-foreground">{description}</p>
      {detail ? <p className="mt-1 text-xs text-muted-foreground">{detail}</p> : null}

      <div className="mt-4">
        <Button asChild size="sm" variant={hasWork ? "default" : "outline"}>
          <Link href={href}>
            {cta}
            <ArrowRight className="ml-1.5 h-3.5 w-3.5" />
          </Link>
        </Button>
      </div>
    </article>
  );
}
