/**
 * Confidence badge component with semantic labels and progressive disclosure
 * Follows Apple/Vercel/shadcn design principles:
 * - Speed Through Subtraction: Single unified confidence signal
 * - Progressive Disclosure: Details revealed on interaction
 * - Spatial Consistency: Uses theme tokens consistently
 */

"use client"

import * as React from "react"
import { CheckCircle, AlertCircle, HelpCircle, ChevronDown } from "lucide-react"
import { cn } from "@/lib/utils"
import {
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
} from "@/components/ui/collapsible"

interface ConfidenceConfig {
    label: string
    description: string
    icon: typeof CheckCircle
    className: string
    bgClassName: string
}

/**
 * Get semantic confidence configuration based on score
 * - >=85%: Verified (official documentation)
 * - >=70%: Likely accurate (community knowledge)
 * - >=50%: Needs verification
 * - <50%: Community response
 */
const getConfidenceConfig = (confidence: number): ConfidenceConfig => {
    if (confidence >= 0.85) {
        return {
            label: "Verified",
            description: "Answer drawn from official Bisq documentation",
            icon: CheckCircle,
            className: "text-primary",
            bgClassName: "hover:bg-primary/10",
        }
    }
    if (confidence >= 0.70) {
        return {
            label: "Likely accurate",
            description: "Based on community support knowledge",
            icon: CheckCircle,
            className: "text-muted-foreground",
            bgClassName: "hover:bg-muted/50",
        }
    }
    if (confidence >= 0.50) {
        return {
            label: "Needs verification",
            description: "Consider verifying with the Bisq community",
            icon: AlertCircle,
            className: "text-amber-500 dark:text-amber-400",
            bgClassName: "hover:bg-amber-500/10",
        }
    }
    return {
        label: "Community response",
        description: "Based on general knowledge, not verified documentation",
        icon: HelpCircle,
        className: "text-muted-foreground",
        bgClassName: "hover:bg-muted/50",
    }
}

interface ConfidenceBadgeProps {
    confidence: number
    version?: string
    className?: string
}

export function ConfidenceBadge({
    confidence,
    version,
    className,
}: ConfidenceBadgeProps) {
    const [isOpen, setIsOpen] = React.useState(false)
    const config = getConfidenceConfig(confidence)
    const Icon = config.icon

    return (
        <Collapsible open={isOpen} onOpenChange={setIsOpen} className="relative">
            <CollapsibleTrigger asChild>
                <button
                    className={cn(
                        "inline-flex items-center gap-1.5 px-2 py-1 rounded-md",
                        "text-xs font-medium transition-all duration-200",
                        "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
                        "min-h-[28px]",
                        config.className,
                        config.bgClassName,
                        className
                    )}
                    aria-label={`Confidence: ${config.label}. Click for details.`}
                    aria-expanded={isOpen}
                >
                    <Icon className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
                    <span>{config.label}</span>
                    {version && (
                        <span className="text-muted-foreground font-normal">
                            for {version}
                        </span>
                    )}
                    <ChevronDown
                        className={cn(
                            "h-3 w-3 text-muted-foreground transition-transform duration-200",
                            isOpen && "rotate-180"
                        )}
                        aria-hidden="true"
                    />
                </button>
            </CollapsibleTrigger>
            <CollapsibleContent
                className={cn(
                    "absolute left-0 top-full z-10 mt-1",
                    "bg-popover border border-border rounded-md shadow-md",
                    "overflow-hidden",
                    "data-[state=open]:animate-in data-[state=closed]:animate-out",
                    "data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0",
                    "data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95"
                )}
            >
                <p
                    className="text-xs text-muted-foreground p-2 max-w-[280px]"
                    id={`confidence-desc-${confidence}`}
                >
                    {config.description}
                    {confidence < 0.70 && (
                        <span className="block mt-1 text-amber-500 dark:text-amber-400">
                            Consider asking in Bisq community for confirmation.
                        </span>
                    )}
                </p>
            </CollapsibleContent>
        </Collapsible>
    )
}

export { getConfidenceConfig }
