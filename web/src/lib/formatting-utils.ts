/**
 * Shared formatting utilities for consistent display across components
 */

export function formatResponseTime(seconds: number): string {
    return seconds < 60
        ? `${Math.round(seconds)} seconds`
        : `${Math.round(seconds / 60)} minutes`
}

export function formatTimeAgo(timestamp: string | Date): string {
    const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp
    const now = new Date()
    const diffMs = now.getTime() - date.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
}
