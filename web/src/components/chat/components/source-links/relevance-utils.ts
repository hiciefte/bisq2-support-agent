/**
 * Utility functions for source relevance scoring and grouping
 */

import type { Source } from "../../types/chat.types"

export type RelevanceLevel = "high" | "medium" | "supporting"

export interface RelevanceConfig {
    level: RelevanceLevel
    label: string
    className: string
}

/**
 * Get relevance configuration based on similarity score
 * @param score - Similarity score from 0.0 to 1.0
 * @returns RelevanceConfig with level, label, and Tailwind classes
 */
export function getRelevanceConfig(score: number | undefined): RelevanceConfig {
    if (score === undefined || score === null) {
        return {
            level: "supporting",
            label: "Supporting",
            className: "bg-muted text-muted-foreground",
        }
    }

    if (score >= 0.75) {
        return {
            level: "high",
            label: "High relevance",
            className: "bg-green-500/10 text-green-600 dark:text-green-400",
        }
    }

    if (score >= 0.5) {
        return {
            level: "medium",
            label: "Medium",
            className: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
        }
    }

    return {
        level: "supporting",
        label: "Supporting",
        className: "bg-muted text-muted-foreground",
    }
}

/**
 * Grouped source for display (multiple chunks from same article)
 */
export interface GroupedSource {
    title: string
    url?: string
    type: "wiki" | "faq"
    sections: Array<{
        section?: string
        content: string
        similarity_score?: number
    }>
    maxScore: number
}

/**
 * Group sources by article title to avoid repetition
 * @param sources - Array of Source objects
 * @returns Array of GroupedSource objects sorted by max score
 */
export function groupSourcesByArticle(sources: Source[]): GroupedSource[] {
    const grouped = new Map<string, GroupedSource>()

    for (const source of sources) {
        const key = `${source.type}:${source.title}`

        if (!grouped.has(key)) {
            grouped.set(key, {
                title: source.title,
                url: source.url,
                type: source.type as "wiki" | "faq",
                sections: [],
                maxScore: source.similarity_score || 0,
            })
        }

        const group = grouped.get(key)!
        group.sections.push({
            section: source.section,
            content: source.content,
            similarity_score: source.similarity_score,
        })
        group.maxScore = Math.max(group.maxScore, source.similarity_score || 0)
    }

    // Sort by max score descending
    return Array.from(grouped.values()).sort((a, b) => b.maxScore - a.maxScore)
}
