/**
 * Shared formatting utilities for consistent display across components
 */

export function formatResponseTime(seconds: number): string {
    if (seconds < 60) {
        const rounded = Math.round(seconds)
        return `${rounded} ${rounded === 1 ? 'second' : 'seconds'}`
    }
    const rounded = Math.round(seconds / 60)
    return `${rounded} ${rounded === 1 ? 'minute' : 'minutes'}`
}

export function formatTimeAgo(timestamp: string | Date): string {
    const date = typeof timestamp === 'string' ? new Date(timestamp) : timestamp

    // Guard against invalid timestamps
    if (isNaN(date.getTime())) {
        return 'unknown'
    }

    const now = new Date()
    const diffMs = now.getTime() - date.getTime()

    // Guard against future timestamps (clock skew)
    if (diffMs < 0) {
        return 'just now'
    }

    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 1) return 'just now'
    if (diffMins < 60) return `${diffMins}m ago`
    const diffHours = Math.floor(diffMins / 60)
    if (diffHours < 24) return `${diffHours}h ago`
    const diffDays = Math.floor(diffHours / 24)
    return `${diffDays}d ago`
}
