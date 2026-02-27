import { Suspense } from "react";
import { OverviewClient } from "@/components/admin/overview/OverviewClient";
import { OverviewSkeleton } from "@/components/admin/overview/OverviewSkeleton";
import {
  type AdminActionCounts,
  type ChannelAutoresponsePolicy,
  type DashboardData,
} from "@/components/admin/overview/types";
import { fetchAdminApiJson } from "@/lib/server-admin-api";

async function fetchInitialOverviewData() {
  const [dashboardData, actionCounts, channelPolicies] = await Promise.all([
    fetchAdminApiJson<DashboardData>("/admin/dashboard/overview?period=7d"),
    fetchAdminApiJson<AdminActionCounts>("/admin/overview/action-counts"),
    fetchAdminApiJson<ChannelAutoresponsePolicy[]>("/admin/channels/autoresponse"),
  ]);

  return {
    dashboardData,
    actionCounts,
    channelPolicies: channelPolicies ?? [],
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
