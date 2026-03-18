import { Suspense } from "react";
import { OverviewClient } from "@/components/admin/overview/OverviewClient";
import { OverviewSkeleton } from "@/components/admin/overview/OverviewSkeleton";
import {
  type AdminActionCounts,
  type ChannelAutoresponsePolicy,
  type DashboardData,
} from "@/components/admin/overview/types";
import type { TrustMonitorPolicy } from "@/components/admin/security/types";
import { fetchAdminApiJson } from "@/lib/server-admin-api";

async function fetchInitialOverviewData() {
  const [dashboardData, actionCounts, channelPolicies, trustMonitorPolicy] = await Promise.all([
    fetchAdminApiJson<DashboardData>("/admin/dashboard/overview?period=7d"),
    fetchAdminApiJson<AdminActionCounts>("/admin/overview/action-counts"),
    fetchAdminApiJson<ChannelAutoresponsePolicy[]>("/admin/channels/autoresponse"),
    fetchAdminApiJson<TrustMonitorPolicy>("/admin/security/trust-monitor/policy").catch(() => null),
  ]);

  return {
    dashboardData,
    actionCounts,
    channelPolicies: channelPolicies ?? [],
    trustMonitorPolicy,
  };
}

export default async function AdminOverviewPage() {
  const initialData = await fetchInitialOverviewData();
  return (
    <Suspense fallback={<OverviewSkeleton />}>
      <OverviewClient initialData={initialData} />
    </Suspense>
  );
}
