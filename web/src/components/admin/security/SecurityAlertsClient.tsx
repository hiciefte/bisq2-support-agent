"use client";

import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, FilterX, Loader2, ShieldCheck } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { SecurityAlertsInitialData, TrustFinding, TrustFindingCounts, TrustMonitorPolicy } from "@/components/admin/security/types";
import { SecurityAlertsPolicyBar } from "@/components/admin/security/SecurityAlertsPolicyBar";
import { SecurityAuditTrail } from "@/components/admin/security/SecurityAuditTrail";
import { SecurityFindingDetail } from "@/components/admin/security/SecurityFindingDetail";
import { SecurityFindingsList } from "@/components/admin/security/SecurityFindingsList";
import { SecurityOpsSummary } from "@/components/admin/security/SecurityOpsSummary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { makeAuthenticatedRequest } from "@/lib/auth";
import { cn } from "@/lib/utils";

interface SecurityAlertsClientProps {
  initialData: SecurityAlertsInitialData;
}

export function SecurityAlertsClient({ initialData }: SecurityAlertsClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [findings, setFindings] = useState<TrustFinding[]>(initialData.findings?.items ?? []);
  const [counts, setCounts] = useState<TrustFindingCounts | null>(initialData.counts);
  const [policy, setPolicy] = useState<TrustMonitorPolicy | null>(initialData.policy);
  const [ops, setOps] = useState(initialData.ops);
  const [trustAudit, setTrustAudit] = useState(initialData.trustAudit?.items ?? []);
  const [chatopsAudit, setChatopsAudit] = useState(initialData.chatopsAudit?.items ?? []);
  const [isMutating, setIsMutating] = useState(false);
  const [isBootstrapping, setIsBootstrapping] = useState(false);
  const [bootstrapError, setBootstrapError] = useState<string | null>(null);

  const statusFilter = searchParams.get("status") ?? "";
  const detectorFilter = searchParams.get("detector") ?? "";

  useEffect(() => {
    setFindings(initialData.findings?.items ?? []);
    setCounts(initialData.counts);
    setPolicy(initialData.policy);
    setOps(initialData.ops);
    setTrustAudit(initialData.trustAudit?.items ?? []);
    setChatopsAudit(initialData.chatopsAudit?.items ?? []);
  }, [initialData]);

  useEffect(() => {
    const needsBootstrap = (
      initialData.findings === null
      || initialData.counts === null
      || initialData.policy === null
      || initialData.ops === null
      || initialData.trustAudit === null
      || initialData.chatopsAudit === null
    );

    if (!needsBootstrap) {
      return;
    }

    let isCancelled = false;

    async function loadClientBootstrap() {
      setIsBootstrapping(true);
      setBootstrapError(null);
      try {
        const [
          findingsResult,
          countsResult,
          policyResult,
          opsResult,
          trustAuditResult,
          chatopsAuditResult,
        ] = await Promise.allSettled([
          makeAuthenticatedRequest("/admin/security/findings"),
          makeAuthenticatedRequest("/admin/security/findings/counts"),
          makeAuthenticatedRequest("/admin/security/trust-monitor/policy"),
          makeAuthenticatedRequest("/admin/security/trust-monitor/ops"),
          makeAuthenticatedRequest("/admin/security/trust-monitor/access-audit"),
          makeAuthenticatedRequest("/admin/security/chatops/audit"),
        ]);

        if (isCancelled) {
          return;
        }

        const findingsResponse = findingsResult.status === "fulfilled" ? findingsResult.value : null;
        const countsResponse = countsResult.status === "fulfilled" ? countsResult.value : null;
        const policyResponse = policyResult.status === "fulfilled" ? policyResult.value : null;
        const opsResponse = opsResult.status === "fulfilled" ? opsResult.value : null;
        const trustAuditResponse = trustAuditResult.status === "fulfilled" ? trustAuditResult.value : null;
        const chatopsAuditResponse = chatopsAuditResult.status === "fulfilled" ? chatopsAuditResult.value : null;

        const failedEndpoints = [
          findingsResponse?.ok ? null : "findings",
          countsResponse?.ok ? null : "counts",
          policyResponse?.ok ? null : "policy",
          opsResponse?.ok ? null : "ops",
          trustAuditResponse?.ok ? null : "trust-audit",
          chatopsAuditResponse?.ok ? null : "chatops-audit",
        ].filter((value): value is string => value !== null);

        if (findingsResponse?.ok) {
          const payload = (await findingsResponse.json()) as SecurityAlertsInitialData["findings"];
          setFindings(payload?.items ?? []);
        }
        if (countsResponse?.ok) {
          setCounts((await countsResponse.json()) as TrustFindingCounts);
        }
        if (policyResponse?.ok) {
          setPolicy((await policyResponse.json()) as TrustMonitorPolicy);
        }
        if (opsResponse?.ok) {
          setOps((await opsResponse.json()) as SecurityAlertsInitialData["ops"]);
        }
        if (trustAuditResponse?.ok) {
          const payload = await trustAuditResponse.json();
          setTrustAudit(payload.items ?? []);
        }
        if (chatopsAuditResponse?.ok) {
          const payload = await chatopsAuditResponse.json();
          setChatopsAudit(payload.items ?? []);
        }
        if (failedEndpoints.length > 0) {
          setBootstrapError(`Security review loaded with partial API data. Missing: ${failedEndpoints.join(", ")}.`);
        }
      } catch (error) {
        if (!isCancelled) {
          console.error("Failed to bootstrap security alerts client data", error);
          setBootstrapError("Security review loaded without its server bootstrap data. The page recovered as much as possible in the browser.");
        }
      } finally {
        if (!isCancelled) {
          setIsBootstrapping(false);
        }
      }
    }

    void loadClientBootstrap();

    return () => {
      isCancelled = true;
    };
  }, [initialData]);

  const filteredFindings = useMemo(() => findings.filter((finding) => {
    const statusMatch = !statusFilter || finding.status === statusFilter;
    const detectorMatch = !detectorFilter || finding.detector_key === detectorFilter;
    return statusMatch && detectorMatch;
  }), [detectorFilter, findings, statusFilter]);

  const selectedFindingId = useMemo(() => {
    const raw = searchParams.get("findingId");
    if (raw) {
      const parsed = Number(raw);
      if (filteredFindings.some((finding) => finding.id === parsed)) {
        return parsed;
      }
    }
    return filteredFindings[0]?.id ?? null;
  }, [filteredFindings, searchParams]);
  const selectedFinding = filteredFindings.find((finding) => finding.id === selectedFindingId) ?? null;
  const hasActiveFilters = Boolean(statusFilter || detectorFilter);

  const derivedCounts = useMemo<TrustFindingCounts>(() => findings.reduce<TrustFindingCounts>((summary, finding) => {
    summary.total += 1;
    summary[finding.status] += 1;
    return summary;
  }, {
    total: 0,
    open: 0,
    resolved: 0,
    false_positive: 0,
    suppressed: 0,
    benign: 0,
  }), [findings]);

  const updateUrl = (next: Record<string, string | null>) => {
    const params = new URLSearchParams(searchParams.toString());
    Object.entries(next).forEach(([key, value]) => {
      if (!value) {
        params.delete(key);
      } else {
        params.set(key, value);
      }
    });
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  };

  const handleAction = async (action: "resolve" | "false-positive" | "suppress" | "mark-benign") => {
    if (!selectedFinding) return;
    const previous = findings;
    const actionToStatus: Record<typeof action, TrustFinding["status"]> = {
      resolve: "resolved",
      "false-positive": "false_positive",
      suppress: "suppressed",
      "mark-benign": "benign",
    };
    const nextStatus = actionToStatus[action];
    setFindings((current) => current.map((finding) => (
      finding.id === selectedFinding.id ? { ...finding, status: nextStatus } : finding
    )));
    setIsMutating(true);
    try {
      const response = await makeAuthenticatedRequest(`/admin/security/findings/${selectedFinding.id}/${action}`, {
        method: "POST",
      });
      if (!response.ok) {
        throw new Error(`Failed to update finding (${response.status})`);
      }
      const updated = (await response.json()) as TrustFinding;
      setFindings((current) => current.map((finding) => (finding.id === updated.id ? updated : finding)));
      const countsResponse = await makeAuthenticatedRequest("/admin/security/findings/counts");
      if (countsResponse.ok) {
        setCounts((await countsResponse.json()) as TrustFindingCounts);
      }
    } catch (error) {
      console.error("Failed to mutate trust finding", error);
      setFindings(previous);
    } finally {
      setIsMutating(false);
    }
  };

  const statusCards: Array<{ key: keyof TrustFindingCounts | "total"; label: string; value: number; filter: string | null }> = [
    { key: "total", label: "All findings", value: counts?.total ?? derivedCounts.total, filter: null },
    { key: "open", label: "Open", value: counts?.open ?? derivedCounts.open, filter: "open" },
    { key: "resolved", label: "Resolved", value: counts?.resolved ?? derivedCounts.resolved, filter: "resolved" },
    { key: "false_positive", label: "False positive", value: counts?.false_positive ?? derivedCounts.false_positive, filter: "false_positive" },
    { key: "suppressed", label: "Suppressed", value: counts?.suppressed ?? derivedCounts.suppressed, filter: "suppressed" },
    { key: "benign", label: "Benign", value: counts?.benign ?? derivedCounts.benign, filter: "benign" },
  ];

  return (
    <div className="space-y-6">
      <SecurityAlertsPolicyBar policy={policy} />

      {bootstrapError ? (
        <div className="rounded-2xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-sm text-amber-100">
          <div className="inline-flex items-center gap-2 font-medium">
            <AlertTriangle className="h-4 w-4" />
            Partial bootstrap recovery
          </div>
          <p className="mt-1 text-xs text-amber-100/90">{bootstrapError}</p>
        </div>
      ) : null}

      <section className="rounded-2xl border border-border/70 bg-card/60 p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-xl font-semibold tracking-tight">Review queue</h2>
              {isBootstrapping ? (
                <Badge variant="outline" className="gap-1.5 text-xs text-muted-foreground">
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  Syncing from API
                </Badge>
              ) : null}
              {!isBootstrapping && filteredFindings.length > 0 ? (
                <Badge variant="outline" className="gap-1.5 text-xs text-muted-foreground">
                  <ShieldCheck className="h-3.5 w-3.5" />
                  {filteredFindings.length} findings in view
                </Badge>
              ) : null}
            </div>
            <p className="max-w-2xl text-sm text-muted-foreground">
              Work from open findings first. Use the queue filters to narrow by detector or outcome, then confirm the evidence in the side panel before taking action.
            </p>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:min-w-[420px]">
            <div className="space-y-2 text-sm">
              <div className="font-medium">Status</div>
              <Select
                value={statusFilter || "all"}
                onValueChange={(value) => updateUrl({ status: value === "all" ? null : value, findingId: null })}
              >
                <SelectTrigger className="h-11 rounded-xl border-border/80 bg-background/80 px-4 pr-11 text-left shadow-sm">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All statuses</SelectItem>
                  <SelectItem value="open">Open</SelectItem>
                  <SelectItem value="resolved">Resolved</SelectItem>
                  <SelectItem value="false_positive">False positive</SelectItem>
                  <SelectItem value="suppressed">Suppressed</SelectItem>
                  <SelectItem value="benign">Benign</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2 text-sm">
              <div className="font-medium">Detector</div>
              <Select
                value={detectorFilter || "all"}
                onValueChange={(value) => updateUrl({ detector: value === "all" ? null : value, findingId: null })}
              >
                <SelectTrigger className="h-11 rounded-xl border-border/80 bg-background/80 px-4 pr-11 text-left shadow-sm">
                  <SelectValue placeholder="All detectors" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All detectors</SelectItem>
                  <SelectItem value="staff_name_collision">Staff Name Collision</SelectItem>
                  <SelectItem value="silent_early_observer">Silent Observer</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          {statusCards.map((card) => {
            const isActive = (card.filter ?? "") === statusFilter;
            return (
              <button
                key={card.key}
                type="button"
                onClick={() => updateUrl({ status: card.filter, findingId: null })}
                className={cn(
                  "min-w-[118px] rounded-2xl border px-4 py-3 text-left transition-colors",
                  isActive
                    ? "border-emerald-500/35 bg-emerald-500/10"
                    : "border-border/70 bg-background/40 hover:bg-accent/20",
                )}
              >
                <div className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">{card.label}</div>
                <div className="mt-2 text-2xl font-semibold tabular-nums">{card.value}</div>
              </button>
            );
          })}

          {hasActiveFilters ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => updateUrl({ status: null, detector: null, findingId: null })}
            >
              <FilterX className="mr-2 h-4 w-4" />
              Clear filters
            </Button>
          ) : null}
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.12fr)_minmax(340px,0.88fr)]">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="text-sm font-medium text-muted-foreground">Findings</div>
            <div className="text-xs text-muted-foreground">
              {selectedFinding ? `Selected #${selectedFinding.id}` : "Nothing selected"}
            </div>
          </div>
          <SecurityFindingsList
            findings={filteredFindings}
            selectedFindingId={selectedFindingId}
            onSelect={(findingId) => updateUrl({ findingId: String(findingId) })}
          />
        </section>
        <div className="xl:sticky xl:top-24 xl:self-start">
          <SecurityFindingDetail finding={selectedFinding} isMutating={isMutating} onAction={handleAction} />
        </div>
      </div>

      <SecurityOpsSummary ops={ops} />

      <SecurityAuditTrail
        trustAudit={trustAudit}
        chatopsAudit={chatopsAudit}
      />
    </div>
  );
}
