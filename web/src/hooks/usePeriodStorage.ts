"use client"

import { useState, useEffect, useRef } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { type Period, type DateRange } from '@/types/dashboard';

interface PeriodState {
  period: Period;
  dateRange?: DateRange;
}

const STORAGE_KEY = 'admin_dashboard_period';

/**
 * Custom hook for persisting period selection in localStorage
 * with URL parameter support for shareability
 */
export function usePeriodStorage(defaultPeriod: Period = "7d") {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [periodState, setPeriodState] = useState<PeriodState>({
    period: defaultPeriod,
  });
  const [isInitialized, setIsInitialized] = useState(false);
  const hasInitializedRef = useRef(false);

  // Initialize from URL params or localStorage on mount
  useEffect(() => {
    if (hasInitializedRef.current) return;

    try {
      // Check URL parameters first (for shareability)
      const urlPeriod = searchParams.get('period') as Period;
      const urlStartDate = searchParams.get('start_date');
      const urlEndDate = searchParams.get('end_date');

      if (urlPeriod && ['24h', '7d', '30d', 'custom'].includes(urlPeriod)) {
        const state: PeriodState = { period: urlPeriod };

        if (urlPeriod === 'custom' && urlStartDate && urlEndDate) {
          state.dateRange = {
            from: new Date(urlStartDate),
            to: new Date(urlEndDate),
          };
        }

        setPeriodState(state);
        hasInitializedRef.current = true;
        setIsInitialized(true);
        return;
      }

      // Fall back to localStorage
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);

        // Parse date strings back to Date objects
        if (parsed.dateRange) {
          parsed.dateRange.from = new Date(parsed.dateRange.from);
          parsed.dateRange.to = new Date(parsed.dateRange.to);
        }

        setPeriodState(parsed);
      }
    } catch (error) {
      console.error('Failed to load period from storage:', error);
    } finally {
      hasInitializedRef.current = true;
      setIsInitialized(true);
    }
  }, [searchParams]);

  // Save to localStorage and update URL whenever period changes
  useEffect(() => {
    if (!isInitialized) return;

    try {
      // Save to localStorage
      localStorage.setItem(STORAGE_KEY, JSON.stringify(periodState));

      // Update URL parameters for shareability
      const params = new URLSearchParams(searchParams.toString());
      params.set('period', periodState.period);

      if (periodState.period === 'custom' && periodState.dateRange) {
        params.set('start_date', periodState.dateRange.from.toISOString());
        params.set('end_date', periodState.dateRange.to.toISOString());
      } else {
        params.delete('start_date');
        params.delete('end_date');
      }

      const nextSearch = params.toString();
      const currentSearch = searchParams.toString();
      if (nextSearch !== currentSearch) {
        const newUrl = nextSearch.length > 0
          ? `${pathname}?${nextSearch}`
          : pathname;
        router.replace(newUrl);
      }
    } catch (error) {
      console.error('Failed to save period to storage:', error);
    }
  }, [isInitialized, pathname, periodState, router, searchParams]);

  const updatePeriod = (period: Period, dateRange?: DateRange) => {
    setPeriodState({ period, dateRange });
  };

  return {
    period: periodState.period,
    dateRange: periodState.dateRange,
    updatePeriod,
    isInitialized,
  };
}
