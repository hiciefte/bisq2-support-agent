/**
 * Hook for polling escalation status for a specific message.
 * Polls the API at adaptive intervals to check if staff has responded.
 */

import { useCallback, useEffect, useRef, useState } from "react"
import { API_BASE_URL } from "@/lib/config"

type PollingStatus = 'idle' | 'polling' | 'resolved'

interface EscalationPollResult {
  status: PollingStatus
  staffAnswer: string | null
  respondedAt: string | null
}

interface PollResponse {
  status: 'pending' | 'resolved'
  staff_answer?: string
  responded_at?: string
}

// Polling intervals in milliseconds
const INITIAL_INTERVAL = 10_000     // 10 seconds
const ACTIVE_INTERVAL = 30_000      // 30 seconds
const BACKGROUND_INTERVAL = 60_000  // 60 seconds
const POLL_TIMEOUT = 30 * 60_000    // 30 minutes

export function useEscalationPolling(
  messageId: string | null,
  enabled: boolean
): EscalationPollResult {
  const [status, setStatus] = useState<PollingStatus>('idle')
  const [staffAnswer, setStaffAnswer] = useState<string | null>(null)
  const [respondedAt, setRespondedAt] = useState<string | null>(null)

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startTimeRef = useRef<number>(0)
  const pollCountRef = useRef<number>(0)

  const cleanup = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current)
      intervalRef.current = null
    }
  }, [])

  const poll = useCallback(async () => {
    if (!messageId) return

    // Check timeout
    const elapsed = Date.now() - startTimeRef.current
    if (elapsed > POLL_TIMEOUT) {
      cleanup()
      return
    }

    try {
      const response = await fetch(`${API_BASE_URL}/escalations/poll/${messageId}`)

      if (!response.ok) return

      const data: PollResponse = await response.json()

      if (data.status === 'resolved' && data.staff_answer) {
        setStatus('resolved')
        setStaffAnswer(data.staff_answer)
        setRespondedAt(data.responded_at || null)
        cleanup()
      }
    } catch {
      // Silently continue polling on error
    }

    pollCountRef.current += 1
  }, [messageId, cleanup])

  useEffect(() => {
    if (!enabled || !messageId) {
      setStatus('idle')
      cleanup()
      return
    }

    setStatus('polling')
    startTimeRef.current = Date.now()
    pollCountRef.current = 0

    // Initial poll
    poll()

    // Determine interval based on visibility
    const getInterval = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') {
        return BACKGROUND_INTERVAL
      }
      // Use initial interval for first 5 polls, then active interval
      return pollCountRef.current < 5 ? INITIAL_INTERVAL : ACTIVE_INTERVAL
    }

    // Start polling with adaptive interval
    const startPolling = () => {
      cleanup()
      intervalRef.current = setInterval(() => {
        poll()
      }, getInterval())
    }

    startPolling()

    // Adjust interval on visibility change
    const handleVisibilityChange = () => {
      if (status !== 'resolved') {
        startPolling()
      }
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)

    return () => {
      cleanup()
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [messageId, enabled])

  return { status, staffAnswer, respondedAt }
}
