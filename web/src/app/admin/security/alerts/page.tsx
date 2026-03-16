import { SecurityAlertsClient } from "@/components/admin/security/SecurityAlertsClient";
import type {
  ChatOpsAuditListResponse,
  SecurityAlertsInitialData,
  TrustAccessAuditListResponse,
  TrustFindingCounts,
  TrustFindingListResponse,
  TrustMonitorOpsSnapshot,
  TrustMonitorPolicy,
} from "@/components/admin/security/types";
import { fetchAdminApiJson } from "@/lib/server-admin-api";

interface SecurityAlertsPageProps {
  searchParams?: Promise<Record<string, string | string[] | undefined>>;
}

async function fetchInitialData(status: string, detector: string): Promise<SecurityAlertsInitialData> {
  const params = new URLSearchParams();
  if (status) {
    params.set("status_filter", status);
  }
  if (detector) {
    params.set("detector_key", detector);
  }
  const suffix = params.toString();
  const [findings, counts, policy, ops, trustAudit, chatopsAudit] = await Promise.allSettled([
    fetchAdminApiJson<TrustFindingListResponse>(`/admin/security/findings${suffix ? `?${suffix}` : ""}`),
    fetchAdminApiJson<TrustFindingCounts>("/admin/security/findings/counts"),
    fetchAdminApiJson<TrustMonitorPolicy>("/admin/security/trust-monitor/policy"),
    fetchAdminApiJson<TrustMonitorOpsSnapshot>("/admin/security/trust-monitor/ops"),
    fetchAdminApiJson<TrustAccessAuditListResponse>("/admin/security/trust-monitor/access-audit"),
    fetchAdminApiJson<ChatOpsAuditListResponse>("/admin/security/chatops/audit"),
  ]);
  return {
    findings: findings.status === "fulfilled" ? findings.value : null,
    counts: counts.status === "fulfilled" ? counts.value : null,
    policy: policy.status === "fulfilled" ? policy.value : null,
    ops: ops.status === "fulfilled" ? ops.value : null,
    trustAudit: trustAudit.status === "fulfilled" ? trustAudit.value : null,
    chatopsAudit: chatopsAudit.status === "fulfilled" ? chatopsAudit.value : null,
  };
}

export default async function SecurityAlertsPage({ searchParams }: SecurityAlertsPageProps) {
  const resolved = (await searchParams) ?? {};
  const status = typeof resolved.status === "string" ? resolved.status : "";
  const detector = typeof resolved.detector === "string" ? resolved.detector : "";
  const initialData = await fetchInitialData(status, detector);

  return (
    <div className="p-4 md:p-8 pt-16 lg:pt-8">
      <div className="mx-auto max-w-7xl">
        <SecurityAlertsClient initialData={initialData} />
      </div>
    </div>
  );
}
