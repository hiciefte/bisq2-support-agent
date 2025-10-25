/**
 * Shared types for dashboard period selection and date range filtering
 */

export type Period = "24h" | "7d" | "30d" | "custom";

export interface DateRange {
  from: Date;
  to: Date;
}
