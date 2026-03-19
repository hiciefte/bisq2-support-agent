"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  type ChannelAutoresponsePolicy,
  type ChannelId,
  type EscalationNotificationChannel,
} from "@/components/admin/overview/types";
import { makeAuthenticatedRequest } from "@/lib/auth";

export type ChannelResponseMode = "off" | "review" | "auto";
export type ChannelAcknowledgmentMode = ChannelAutoresponsePolicy["acknowledgment_mode"];
export type ChannelEscalationUserNoticeMode = ChannelAutoresponsePolicy["escalation_user_notice_mode"];
type ChannelPolicyPatch = Partial<
  Pick<
    ChannelAutoresponsePolicy,
    | "enabled"
    | "generation_enabled"
    | "ai_response_mode"
    | "hitl_approval_timeout_seconds"
    | "draft_assistant_enabled"
    | "knowledge_amplifier_enabled"
    | "staff_assist_surface"
    | "first_response_delay_seconds"
    | "staff_active_cooldown_seconds"
    | "max_proactive_ai_replies_per_question"
    | "public_escalation_notice_enabled"
    | "acknowledgment_mode"
    | "acknowledgment_reaction_key"
    | "acknowledgment_message_template"
    | "group_clarification_immediate"
    | "escalation_user_notice_template"
    | "escalation_user_notice_mode"
    | "dispatch_failure_message_template"
    | "escalation_notification_channel"
    | "explicit_invocation_enabled"
    | "explicit_invocation_user_rate_limit_per_5m"
    | "explicit_invocation_room_rate_limit_per_min"
    | "community_response_cancels_ai"
    | "community_substantive_min_chars"
    | "staff_presence_aware_delay"
    | "min_delay_no_staff_seconds"
    | "mandatory_escalation_topics"
    | "timer_jitter_max_seconds"
  >
>;

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
  patch: ChannelPolicyPatch,
): ChannelAutoresponsePolicy {
  return {
    ...policy,
    ...patch,
  };
}

function normalizePatch(
  patch: ChannelPolicyPatch,
): ChannelPolicyPatch {
  const normalizedPatch = { ...patch };
  if (normalizedPatch.generation_enabled === false) {
    normalizedPatch.enabled = false;
    if (typeof normalizedPatch.ai_response_mode !== "string") {
      normalizedPatch.ai_response_mode = "autonomous";
    }
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
    patch: ChannelPolicyPatch,
  ) => {
    const normalizedPatch = normalizePatch(patch);
    if (
      typeof normalizedPatch.enabled !== "boolean"
      && typeof normalizedPatch.generation_enabled !== "boolean"
      && typeof normalizedPatch.ai_response_mode !== "string"
      && typeof normalizedPatch.hitl_approval_timeout_seconds !== "number"
      && typeof normalizedPatch.draft_assistant_enabled !== "boolean"
      && typeof normalizedPatch.knowledge_amplifier_enabled !== "boolean"
      && typeof normalizedPatch.staff_assist_surface !== "string"
      && typeof normalizedPatch.first_response_delay_seconds !== "number"
      && typeof normalizedPatch.staff_active_cooldown_seconds !== "number"
      && typeof normalizedPatch.max_proactive_ai_replies_per_question !== "number"
      && typeof normalizedPatch.public_escalation_notice_enabled !== "boolean"
      && typeof normalizedPatch.acknowledgment_mode !== "string"
      && typeof normalizedPatch.acknowledgment_reaction_key !== "string"
      && typeof normalizedPatch.acknowledgment_message_template !== "string"
      && typeof normalizedPatch.group_clarification_immediate !== "boolean"
      && typeof normalizedPatch.escalation_user_notice_template !== "string"
      && typeof normalizedPatch.escalation_user_notice_mode !== "string"
      && typeof normalizedPatch.dispatch_failure_message_template !== "string"
      && typeof normalizedPatch.escalation_notification_channel !== "string"
      && typeof normalizedPatch.explicit_invocation_enabled !== "boolean"
      && typeof normalizedPatch.explicit_invocation_user_rate_limit_per_5m !== "number"
      && typeof normalizedPatch.explicit_invocation_room_rate_limit_per_min !== "number"
      && typeof normalizedPatch.community_response_cancels_ai !== "boolean"
      && typeof normalizedPatch.community_substantive_min_chars !== "number"
      && typeof normalizedPatch.staff_presence_aware_delay !== "boolean"
      && typeof normalizedPatch.min_delay_no_staff_seconds !== "number"
      && !Array.isArray(normalizedPatch.mandatory_escalation_topics)
      && typeof normalizedPatch.timer_jitter_max_seconds !== "number"
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
          ai_response_mode: "autonomous",
        });
      }
      if (mode === "review") {
        return updateChannelPolicy(channelId, {
          generation_enabled: true,
          enabled: true,
          ai_response_mode: "hitl",
        });
      }
      return updateChannelPolicy(channelId, {
        generation_enabled: true,
        enabled: true,
        ai_response_mode: "autonomous",
      });
    },
    [updateChannelPolicy],
  );

  const setEscalationNotificationChannel = useCallback(
    async (channelId: ChannelId, escalationNotificationChannel: EscalationNotificationChannel) => (
      updateChannelPolicy(channelId, {
        escalation_notification_channel: escalationNotificationChannel,
      })
    ),
    [updateChannelPolicy],
  );

  const setAcknowledgmentMode = useCallback(
    async (channelId: ChannelId, acknowledgmentMode: ChannelAcknowledgmentMode) => (
      updateChannelPolicy(channelId, {
        acknowledgment_mode: acknowledgmentMode,
      })
    ),
    [updateChannelPolicy],
  );

  const setAcknowledgmentReactionKey = useCallback(
    async (channelId: ChannelId, acknowledgmentReactionKey: string) => (
      updateChannelPolicy(channelId, {
        acknowledgment_reaction_key: acknowledgmentReactionKey,
      })
    ),
    [updateChannelPolicy],
  );

  const setAcknowledgmentMessageTemplate = useCallback(
    async (channelId: ChannelId, acknowledgmentMessageTemplate: string) => (
      updateChannelPolicy(channelId, {
        acknowledgment_message_template: acknowledgmentMessageTemplate,
      })
    ),
    [updateChannelPolicy],
  );

  const setEscalationUserNoticeMode = useCallback(
    async (channelId: ChannelId, escalationUserNoticeMode: ChannelEscalationUserNoticeMode) => (
      updateChannelPolicy(channelId, {
        escalation_user_notice_mode: escalationUserNoticeMode,
      })
    ),
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
    setEscalationNotificationChannel,
    setAcknowledgmentMode,
    setAcknowledgmentReactionKey,
    setAcknowledgmentMessageTemplate,
    setEscalationUserNoticeMode,
  };
}
