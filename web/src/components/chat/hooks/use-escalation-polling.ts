/**
 * Hook for resolving a web-chat escalation.
 * Uses SSE for instant staff responses and keeps polling as a safe fallback.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE_URL } from "@/lib/config";

type PollingStatus = "idle" | "polling" | "resolved";
type PollingResolution = "responded" | "closed" | null;

interface EscalationPollResult {
  status: PollingStatus;
  staffAnswer: string | null;
  respondedAt: string | null;
  resolution: PollingResolution;
  staffAnswerRating: number | null;
  rateToken: string | null;
  userLanguage: string | null;
}

interface PollResponse {
  status: "pending" | "resolved";
  staff_answer?: string;
  responded_at?: string;
  resolution?: "responded" | "closed";
  closed_at?: string;
  staff_answer_rating?: number;
  rate_token?: string;
  user_language?: string;
}

const INITIAL_INTERVAL = 10_000;
const ACTIVE_INTERVAL = 30_000;
const BACKGROUND_INTERVAL = 60_000;
const POLL_TIMEOUT = 30 * 60_000;

function escalationUrl(messageId: string, suffix: "events" | "response") {
  return `${API_BASE_URL}/escalations/${messageId}/${suffix}`;
}

export function useEscalationPolling(
  messageId: string | null,
  enabled: boolean,
): EscalationPollResult {
  const [status, setStatus] = useState<PollingStatus>("idle");
  const [staffAnswer, setStaffAnswer] = useState<string | null>(null);
  const [respondedAt, setRespondedAt] = useState<string | null>(null);
  const [resolution, setResolution] = useState<PollingResolution>(null);
  const [staffAnswerRating, setStaffAnswerRating] = useState<number | null>(null);
  const [rateToken, setRateToken] = useState<string | null>(null);
  const [userLanguage, setUserLanguage] = useState<string | null>(null);

  const pollingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingActiveRef = useRef<boolean>(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const startTimeRef = useRef<number>(0);
  const pollCountRef = useRef<number>(0);

  const cleanupPolling = useCallback(() => {
    pollingActiveRef.current = false;
    if (pollingTimeoutRef.current) {
      clearTimeout(pollingTimeoutRef.current);
      pollingTimeoutRef.current = null;
    }
  }, []);

  const cleanup = useCallback(() => {
    cleanupPolling();
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, [cleanupPolling]);

  const resetResolvedState = useCallback(() => {
    setStaffAnswer(null);
    setRespondedAt(null);
    setResolution(null);
    setStaffAnswerRating(null);
    setRateToken(null);
    setUserLanguage(null);
  }, []);

  const applyResponse = useCallback((data: PollResponse): boolean => {
    if (data.status !== "resolved") {
      return false;
    }

    setStatus("resolved");
    setResolution(data.staff_answer ? "responded" : (data.resolution ?? null));
    setStaffAnswer(data.staff_answer ?? null);
    setRespondedAt(data.responded_at || data.closed_at || null);
    setStaffAnswerRating(data.staff_answer_rating ?? null);
    setRateToken(data.rate_token ?? null);
    setUserLanguage(data.user_language ?? null);

    return Boolean(data.staff_answer || data.resolution === "closed");
  }, []);

  const poll = useCallback(async () => {
    if (!messageId) return;

    const elapsed = Date.now() - startTimeRef.current;
    if (elapsed > POLL_TIMEOUT) {
      cleanup();
      return;
    }

    try {
      const response = await fetch(escalationUrl(messageId, "response"));

      if (!response.ok) return;

      const data: PollResponse = await response.json();
      if (applyResponse(data)) {
        cleanup();
      }
    } catch {
      // Keep the fallback loop alive on transient API/network errors.
    }

    pollCountRef.current += 1;
  }, [messageId, cleanup, applyResponse]);

  useEffect(() => {
    if (!enabled || !messageId) {
      setStatus("idle");
      resetResolvedState();
      cleanup();
      return;
    }

    let active = true;

    const getInterval = () => {
      if (
        typeof document !== "undefined" &&
        document.visibilityState === "hidden"
      ) {
        return BACKGROUND_INTERVAL;
      }
      return pollCountRef.current < 5 ? INITIAL_INTERVAL : ACTIVE_INTERVAL;
    };

    const startPolling = () => {
      cleanupPolling();
      pollingActiveRef.current = true;

      const runAndSchedule = async () => {
        await poll();
        if (!active || !pollingActiveRef.current) return;

        pollingTimeoutRef.current = setTimeout(() => {
          void runAndSchedule();
        }, getInterval());
      };

      void runAndSchedule();
    };

    const startEventStream = () => {
      const EventSourceCtor =
        typeof window !== "undefined" ? window.EventSource : undefined;
      if (!EventSourceCtor) {
        startPolling();
        return;
      }

      const source = new EventSourceCtor(escalationUrl(messageId, "events"));
      eventSourceRef.current = source;

      const handleEvent = (event: MessageEvent) => {
        if (!active) return;
        try {
          const data = JSON.parse(event.data) as PollResponse;
          if (applyResponse(data)) {
            cleanup();
          }
        } catch {
          cleanup();
          startPolling();
        }
      };

      const handleError = () => {
        if (!active || eventSourceRef.current !== source) return;
        source.close();
        eventSourceRef.current = null;
        startPolling();
      };

      source.addEventListener("escalation", handleEvent);
      source.addEventListener("message", handleEvent);
      source.addEventListener("error", handleError);
    };

    setStatus("polling");
    resetResolvedState();
    startTimeRef.current = Date.now();
    pollCountRef.current = 0;
    startEventStream();

    const handleVisibilityChange = () => {
      if (pollingActiveRef.current) {
        startPolling();
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      active = false;
      cleanup();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [
    messageId,
    enabled,
    poll,
    applyResponse,
    cleanup,
    cleanupPolling,
    resetResolvedState,
  ]);

  return {
    status,
    staffAnswer,
    respondedAt,
    resolution,
    staffAnswerRating,
    rateToken,
    userLanguage,
  };
}
