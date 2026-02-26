"use client";

import { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { VectorStoreStatusBanner } from "@/components/admin/VectorStoreStatusBanner";
import {
    QueueShortcutFooter,
    type QueueShortcutHint,
} from "@/components/admin/queue/QueueShortcutFooter";

interface AdminQueueShellProps {
    children: ReactNode;
    shortcutHints?: QueueShortcutHint[];
    shortcutTitle?: string;
    showVectorStoreBanner?: boolean;
    className?: string;
    containerClassName?: string;
}

export function AdminQueueShell({
    children,
    shortcutHints = [],
    shortcutTitle,
    showVectorStoreBanner = false,
    className,
    containerClassName,
}: AdminQueueShellProps) {
    return (
        <div className={cn("min-h-screen bg-background", className)}>
            {showVectorStoreBanner && <VectorStoreStatusBanner />}
            <div className={cn("p-4 md:p-8 space-y-6 pt-16 lg:pt-8", containerClassName)}>
                {children}
                {shortcutHints.length > 0 && (
                    <QueueShortcutFooter hints={shortcutHints} title={shortcutTitle} />
                )}
            </div>
        </div>
    );
}
