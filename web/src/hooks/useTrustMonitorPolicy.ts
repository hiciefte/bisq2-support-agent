"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { TrustAlertSurface, TrustMonitorPolicy } from "@/components/admin/security/types";
import { makeAuthenticatedRequest } from "@/lib/auth";

type TrustMonitorPolicyPatch = Partial<TrustMonitorPolicy>;

export function useTrustMonitorPolicy(initialPolicy: TrustMonitorPolicy | null) {
  const [policy, setPolicy] = useState<TrustMonitorPolicy | null>(initialPolicy);
  const [isLoading, setIsLoading] = useState(initialPolicy === null);
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mutationVersionRef = useRef(0);
  const policyRef = useRef<TrustMonitorPolicy | null>(initialPolicy);

  useEffect(() => {
    policyRef.current = policy;
  }, [policy]);

  useEffect(() => {
    setPolicy(initialPolicy);
    policyRef.current = initialPolicy;
    setIsLoading(initialPolicy === null);
  }, [initialPolicy]);

  const refresh = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await makeAuthenticatedRequest("/admin/security/trust-monitor/policy");
      if (!response.ok) {
        throw new Error(`Failed to load trust monitor policy (${response.status})`);
      }
      const payload = (await response.json()) as TrustMonitorPolicy;
      policyRef.current = payload;
      setPolicy(payload);
      setError(null);
    } catch (err) {
      console.error("Failed to refresh trust monitor policy", err);
      setError("Could not load trust-monitor policy.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (initialPolicy !== null) {
      return;
    }
    void refresh();
  }, [initialPolicy, refresh]);

  const updatePolicy = useCallback(async (patch: TrustMonitorPolicyPatch) => {
    if (Object.keys(patch).length === 0) {
      return true;
    }
    const previous = policyRef.current;
    if (previous === null) {
      return false;
    }
    const version = mutationVersionRef.current + 1;
    mutationVersionRef.current = version;
    const optimistic = { ...previous, ...patch };
    policyRef.current = optimistic;
    setPolicy(optimistic);
    setIsSaving(true);
    try {
      const response = await makeAuthenticatedRequest("/admin/security/trust-monitor/policy", {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      if (!response.ok) {
        throw new Error(`Failed to update trust monitor policy (${response.status})`);
      }
      const updated = (await response.json()) as TrustMonitorPolicy;
      if (mutationVersionRef.current !== version) {
        return true;
      }
      policyRef.current = updated;
      setPolicy(updated);
      setError(null);
      return true;
    } catch (err) {
      console.error("Failed to update trust monitor policy", err);
      if (mutationVersionRef.current === version && previous !== null) {
        policyRef.current = previous;
        setPolicy(previous);
      }
      setError("Could not update trust-monitor policy.");
      return false;
    } finally {
      if (mutationVersionRef.current === version) {
        setIsSaving(false);
      }
    }
  }, []);

  const setAlertSurface = useCallback((alertSurface: TrustAlertSurface) => updatePolicy({ alert_surface: alertSurface }), [updatePolicy]);
  const setEnabled = useCallback((enabled: boolean) => updatePolicy({ enabled }), [updatePolicy]);
  const setDetectorEnabled = useCallback((detector: "name_collision_enabled" | "silent_observer_enabled", value: boolean) => (
    updatePolicy({ [detector]: value })
  ), [updatePolicy]);

  return {
    policy,
    isLoading,
    isSaving,
    error,
    refresh,
    updatePolicy,
    setAlertSurface,
    setEnabled,
    setDetectorEnabled,
  };
}
