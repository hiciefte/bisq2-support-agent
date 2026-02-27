"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ChannelAutoresponsePolicy,
  type ChannelId,
} from "@/components/admin/overview/types";
import { makeAuthenticatedRequest } from "@/lib/auth";

export type ChannelResponseMode = "off" | "review" | "auto";

const CHANNEL_ORDER: ChannelId[] = ["web", "bisq2", "matrix"];
const EMPTY_SAVING_STATE: Record<ChannelId, boolean> = {
  web: false,
  bisq2: false,
  matrix: false,
};

function sortPolicies(policies: ChannelAutoresponsePolicy[]): ChannelAutoresponsePolicy[] {
  const rank = new Map<ChannelId, number>(CHANNEL_ORDER.map((id, index) => [id, index]));
  return [...policies].sort((a, b) => {
    const left = rank.get(a.channel_id) ?? Number.MAX_SAFE_INTEGER;
    const right = rank.get(b.channel_id) ?? Number.MAX_SAFE_INTEGER;
    return left - right;
  });
}

function applyPatch(
  policy: ChannelAutoresponsePolicy,
  patch: Partial<Pick<ChannelAutoresponsePolicy, "enabled" | "generation_enabled">>,
): ChannelAutoresponsePolicy {
  return {
    ...policy,
    ...patch,
  };
}

function normalizePatch(
  patch: Partial<Pick<ChannelAutoresponsePolicy, "enabled" | "generation_enabled">>,
): Partial<Pick<ChannelAutoresponsePolicy, "enabled" | "generation_enabled">> {
  const normalizedPatch = { ...patch };
  if (normalizedPatch.generation_enabled === false) {
    normalizedPatch.enabled = false;
  }
  return normalizedPatch;
}

export function useChannelAutoresponsePolicies(initialPolicies: ChannelAutoresponsePolicy[] = []) {
  const initialSorted = sortPolicies(initialPolicies);
  const [policies, setPolicies] = useState<ChannelAutoresponsePolicy[]>(initialSorted);
  const [isLoading, setIsLoading] = useState(initialSorted.length === 0);
  const [isSavingByChannel, setIsSavingByChannel] = useState<Record<ChannelId, boolean>>(EMPTY_SAVING_STATE);
  const [error, setError] = useState<string | null>(null);
  const latestFetchIdRef = useRef(0);
  const policiesRef = useRef<ChannelAutoresponsePolicy[]>(initialSorted);
  const mutationVersionRef = useRef<Record<ChannelId, number>>({
    web: 0,
    bisq2: 0,
    matrix: 0,
  });

  useEffect(() => {
    policiesRef.current = policies;
  }, [policies]);

  const refresh = useCallback(async () => {
    const requestId = ++latestFetchIdRef.current;
    setIsLoading(true);
    try {
      const response = await makeAuthenticatedRequest("/admin/channels/autoresponse");
      if (!response.ok) {
        throw new Error(`Failed to load channel policy (${response.status})`);
      }
      const payload = (await response.json()) as ChannelAutoresponsePolicy[];
      if (requestId !== latestFetchIdRef.current) {
        return;
      }
      setPolicies(sortPolicies(payload));
      setError(null);
    } catch (err) {
      if (requestId !== latestFetchIdRef.current) {
        return;
      }
      console.error("Failed to load channel autoresponse policies", err);
      setError("Could not load channel auto-response policy.");
    } finally {
      if (requestId === latestFetchIdRef.current) {
        setIsLoading(false);
      }
    }
  }, []);

  const updateChannelPolicy = useCallback(async (
    channelId: ChannelId,
    patch: Partial<Pick<ChannelAutoresponsePolicy, "enabled" | "generation_enabled">>,
  ) => {
    const normalizedPatch = normalizePatch(patch);
    if (
      typeof normalizedPatch.enabled !== "boolean"
      && typeof normalizedPatch.generation_enabled !== "boolean"
    ) {
      return true;
    }

    const previousPolicy = policiesRef.current.find((policy) => policy.channel_id === channelId);
    const mutationVersion = mutationVersionRef.current[channelId] + 1;
    mutationVersionRef.current[channelId] = mutationVersion;

    setPolicies((current) =>
      current.map((policy) =>
        policy.channel_id === channelId
          ? applyPatch(policy, normalizedPatch)
          : policy,
      ),
    );
    setIsSavingByChannel((current) => ({
      ...current,
      [channelId]: true,
    }));

    try {
      const response = await makeAuthenticatedRequest(`/admin/channels/autoresponse/${channelId}`, {
        method: "PUT",
        body: JSON.stringify(normalizedPatch),
      });
      if (!response.ok) {
        throw new Error(`Failed to update ${channelId} policy (${response.status})`);
      }
      const updatedPolicy = (await response.json()) as ChannelAutoresponsePolicy;
      if (mutationVersionRef.current[channelId] !== mutationVersion) {
        return true;
      }
      setPolicies((current) =>
        sortPolicies(
          current.map((policy) =>
            policy.channel_id === channelId ? updatedPolicy : policy,
          ),
        ),
      );
      setError(null);
      return true;
    } catch (err) {
      console.error("Failed to update channel autoresponse policy", err);
      if (mutationVersionRef.current[channelId] !== mutationVersion) {
        return false;
      }
      if (previousPolicy) {
        setPolicies((current) =>
          current.map((policy) =>
            policy.channel_id === channelId
              ? previousPolicy
              : policy,
          ),
        );
      } else {
        void refresh();
      }
      setError("Could not update channel auto-response policy.");
      return false;
    } finally {
      if (mutationVersionRef.current[channelId] === mutationVersion) {
        setIsSavingByChannel((current) => ({
          ...current,
          [channelId]: false,
        }));
      }
    }
  }, [refresh]);

  const setChannelEnabled = useCallback(async (channelId: ChannelId, enabled: boolean) => (
    updateChannelPolicy(channelId, { enabled })
  ), [updateChannelPolicy]);

  const setChannelGenerationEnabled = useCallback(
    async (channelId: ChannelId, generation_enabled: boolean) => (
      updateChannelPolicy(channelId, { generation_enabled })
    ),
    [updateChannelPolicy],
  );

  const setChannelMode = useCallback(
    async (channelId: ChannelId, mode: ChannelResponseMode) => {
      if (mode === "off") {
        return updateChannelPolicy(channelId, {
          generation_enabled: false,
          enabled: false,
        });
      }
      if (mode === "review") {
        return updateChannelPolicy(channelId, {
          generation_enabled: true,
          enabled: false,
        });
      }
      return updateChannelPolicy(channelId, {
        generation_enabled: true,
        enabled: true,
      });
    },
    [updateChannelPolicy],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    policies,
    isLoading,
    isSavingByChannel,
    error,
    refresh,
    updateChannelPolicy,
    setChannelEnabled,
    setChannelGenerationEnabled,
    setChannelMode,
  };
}
