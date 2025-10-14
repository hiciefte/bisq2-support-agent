/**
 * Component to display message sources
 */

import { cn } from "@/lib/utils"

interface Source {
    title: string
    type: string
    content: string
}

interface SourceDisplayProps {
    sources: Source[]
}

export const SourceDisplay = ({ sources }: SourceDisplayProps) => {
    if (!sources || sources.length === 0) {
        return null
    }

    // Deduplicate sources by type
    const uniqueTypes = Array.from(new Set(sources.map(source => source.type)))

    return (
        <div className="text-xs text-muted-foreground">
            <div className="flex items-center gap-2">
                <span className="text-xs font-medium">Sources:</span>
                {uniqueTypes.map((sourceType, index) => (
                    <span
                        key={index}
                        className={cn(
                            "px-2 py-1 rounded-md text-xs",
                            sourceType === "wiki" ? "bg-primary/10" : "bg-secondary/50"
                        )}
                    >
                        {sourceType === "wiki" ? "Wiki" : "Support Chat"}
                    </span>
                ))}
            </div>
        </div>
    )
}
