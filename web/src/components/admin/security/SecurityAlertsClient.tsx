"use client";

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { SecurityAlertsInitialData, TrustFinding, TrustFindingCounts } from "@/components/admin/security/types";
import { SecurityAlertsPolicyBar } from "@/components/admin/security/SecurityAlertsPolicyBar";
import { SecurityAuditTrail } from "@/components/admin/security/SecurityAuditTrail";
import { SecurityFindingDetail } from "@/components/admin/security/SecurityFindingDetail";
import { SecurityFindingsList } from "@/components/admin/security/SecurityFindingsList";
import { SecurityOpsSummary } from "@/components/admin/security/SecurityOpsSummary";
import { useTrustMonitorPolicy } from "@/hooks/useTrustMonitorPolicy";
import { makeAuthenticatedRequest } from "@/lib/auth";

interface SecurityAlertsClientProps {
  initialData: SecurityAlertsInitialData;
}

export function SecurityAlertsClient({ initialData }: SecurityAlertsClientProps) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [findings, setFindings] = useState<TrustFinding[]>(initialData.findings?.items ?? []);
  const [counts, setCounts] = useState<TrustFindingCounts | null>(initialData.counts);
  const [isMutating, setIsMutating] = useState(false);
  const { policy, isSaving, setAlertSurface, updatePolicy } = useTrustMonitorPolicy(initialData.policy);

  const statusFilter = searchParams.get("status") ?? "";
  const detectorFilter = searchParams.get("detector") ?? "";

  useEffect(() => {
    setFindings(initialData.findings?.items ?? []);
    setCounts(initialData.counts);
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
    const nextStatus = action === "false-positive"
      ? "false_positive"
      : action === "mark-benign"
        ? "benign"
        : action;
    setFindings((current) => current.map((finding) => (
      finding.id === selectedFinding.id ? { ...finding, status: nextStatus as TrustFinding["status"] } : finding
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

  return (
    <div className="space-y-6">
      <SecurityAlertsPolicyBar
        policy={policy}
        isSaving={isSaving}
        onAlertSurfaceChange={setAlertSurface}
        onPolicyPatch={updatePolicy}
      />

      <SecurityOpsSummary ops={initialData.ops} />

      <SecurityAuditTrail
        trustAudit={initialData.trustAudit?.items ?? []}
        chatopsAudit={initialData.chatopsAudit?.items ?? []}
      />

      <div className="grid gap-3 rounded-2xl border border-border/70 bg-card/50 p-4 md:grid-cols-3">
        <label className="space-y-2 text-sm">
          <span className="font-medium">Status</span>
          <select
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={statusFilter}
            onChange={(event) => updateUrl({ status: event.target.value || null, findingId: null })}
          >
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
            <option value="false_positive">False positive</option>
            <option value="suppressed">Suppressed</option>
            <option value="benign">Benign</option>
          </select>
        </label>
        <label className="space-y-2 text-sm">
          <span className="font-medium">Detector</span>
          <select
            className="w-full rounded-lg border border-border bg-background px-3 py-2 text-sm"
            value={detectorFilter}
            onChange={(event) => updateUrl({ detector: event.target.value || null, findingId: null })}
          >
            <option value="">All detectors</option>
            <option value="staff_name_collision">Staff Name Collision</option>
            <option value="silent_early_observer">Silent Observer</option>
          </select>
        </label>
        <div className="space-y-2 text-sm">
          <span className="font-medium">Selection</span>
          <div className="rounded-lg border border-border bg-background px-3 py-2 text-muted-foreground">
            {filteredFindings.length} findings in view
          </div>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <div className="rounded-2xl border border-border/70 bg-card/50 p-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Open</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums">{counts?.open ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-border/70 bg-card/50 p-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Resolved</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums">{counts?.resolved ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-border/70 bg-card/50 p-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">False positive</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums">{counts?.false_positive ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-border/70 bg-card/50 p-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Suppressed</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums">{counts?.suppressed ?? 0}</div>
        </div>
        <div className="rounded-2xl border border-border/70 bg-card/50 p-4">
          <div className="text-xs uppercase tracking-wide text-muted-foreground">Benign</div>
          <div className="mt-2 text-3xl font-semibold tabular-nums">{counts?.benign ?? 0}</div>
        </div>
      </div>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <SecurityFindingsList
          findings={filteredFindings}
          selectedFindingId={selectedFindingId}
          onSelect={(findingId) => updateUrl({ findingId: String(findingId) })}
        />
        <div className="xl:sticky xl:top-24 xl:self-start">
          <SecurityFindingDetail finding={selectedFinding} isMutating={isMutating} onAction={handleAction} />
        </div>
      </div>
    </div>
  );
}
