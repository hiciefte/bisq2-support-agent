"use client";

import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

export interface DiffRow {
  kind: "context" | "add" | "remove";
  beforeLine: number | null;
  afterLine: number | null;
  text: string;
}

export function DocumentDiffViewer({
  rows,
  editingLine,
  onEditLine,
  onChangeLine,
  onStopEditing,
}: {
  rows: DiffRow[];
  editingLine: number | null;
  onEditLine: (lineNumber: number) => void;
  onChangeLine: (lineNumber: number, value: string) => void;
  onStopEditing: () => void;
}) {
  const addedCount = rows.filter((row) => row.kind === "add").length;
  const removedCount = rows.filter((row) => row.kind === "remove").length;

  return (
    <div className="overflow-hidden rounded-xl border border-border/70 bg-background">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border/70 bg-muted/20 px-3 py-2">
        <div>
          <p className="text-sm font-medium">Full wiki file: diff & edit</p>
          <p className="text-xs text-muted-foreground">
            Click a proposed line to edit it in place while keeping the diff context visible.
          </p>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span className="rounded-full border border-emerald-500/25 bg-emerald-500/10 px-2 py-0.5 text-emerald-700">
            +{addedCount}
          </span>
          <span className="rounded-full border border-red-500/25 bg-red-500/10 px-2 py-0.5 text-red-700">
            -{removedCount}
          </span>
        </div>
      </div>
      <div className="max-h-[64vh] overflow-auto">
        <table className="w-full border-collapse text-left font-mono text-xs">
          <tbody>
            {rows.map((row, index) => {
              const afterLine = row.afterLine;
              const isEditable = afterLine !== null;
              // Diff kind can change while typing; keep the textarea mounted to preserve selection/caret state.
              const rowKey = isEditable ? `after-${afterLine}` : `before-${row.beforeLine ?? "x"}-${index}`;

              return (
                <tr
                  key={rowKey}
                  onClick={isEditable ? () => onEditLine(afterLine) : undefined}
                  className={cn(
                    "border-b border-border/30",
                    row.kind === "add" && "bg-emerald-500/10",
                    row.kind === "remove" && "bg-red-500/10",
                    isEditable && "cursor-text hover:bg-muted/30",
                  )}
                >
                  <td className="w-10 select-none border-r border-border/40 px-2 py-1 text-right text-muted-foreground">
                    {row.beforeLine ?? ""}
                  </td>
                  <td className="w-10 select-none border-r border-border/40 px-2 py-1 text-right text-muted-foreground">
                    {row.afterLine ?? ""}
                  </td>
                  <td
                    className={cn(
                      "w-7 select-none border-r border-border/40 px-2 py-1 text-center",
                      row.kind === "add" && "text-emerald-700",
                      row.kind === "remove" && "text-red-700",
                      row.kind === "context" && "text-muted-foreground",
                    )}
                  >
                    {row.kind === "add" ? "+" : row.kind === "remove" ? "-" : ""}
                  </td>
                  <td className="min-w-0 px-3 py-1">
                    {isEditable && editingLine === afterLine ? (
                      <Textarea
                        autoFocus
                        value={row.text}
                        onPointerDown={(event) => event.stopPropagation()}
                        onClick={(event) => event.stopPropagation()}
                        onChange={(event) => onChangeLine(afterLine, event.target.value)}
                        onBlur={onStopEditing}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") onStopEditing();
                        }}
                        className="min-h-20 resize-y bg-background font-mono text-xs leading-5"
                        aria-label={`Edit proposed markdown line ${afterLine}`}
                      />
                    ) : (
                      <pre className="whitespace-pre-wrap break-words font-mono leading-5">
                        {row.text || " "}
                      </pre>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
