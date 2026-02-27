"use client";

import { cn } from "@/lib/utils";

export interface QueueShortcutHint {
    keyCombo: string;
    label: string;
}

interface QueueShortcutFooterProps {
    hints: QueueShortcutHint[];
    title?: string;
    className?: string;
}

export function QueueShortcutFooter({
    hints,
    title = "Keyboard Shortcuts",
    className,
}: QueueShortcutFooterProps) {
    if (hints.length === 0) {
        return null;
    }

    return (
        <footer className={cn("rounded-lg border border-border/60 bg-card/50 px-3 py-2.5", className)}>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-muted-foreground">
                <span className="text-[11px] font-medium uppercase tracking-wide text-foreground/80">
                    {title}
                </span>
                {hints.map((hint) => (
                    <span key={`${hint.keyCombo}-${hint.label}`} className="inline-flex items-center gap-1.5">
                        <kbd className="rounded border border-border bg-muted px-1.5 py-0.5 text-[11px] font-medium text-foreground">
                            {hint.keyCombo}
                        </kbd>
                        <span>{hint.label}</span>
                    </span>
                ))}
            </div>
        </footer>
    );
}
