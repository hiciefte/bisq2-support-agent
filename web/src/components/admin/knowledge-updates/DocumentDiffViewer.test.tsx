import { fireEvent, render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { useState } from "react";
import { DocumentDiffViewer } from "@/components/admin/knowledge-updates/DocumentDiffViewer";

type DiffRows = ComponentProps<typeof DocumentDiffViewer>["rows"];

function DiffEditorHarness() {
  const [rows, setRows] = useState<DiffRows>([
    {
      kind: "add",
      beforeLine: null,
      afterLine: 1,
      text: "Original proposed line",
    },
  ]);

  return (
    <DocumentDiffViewer
      rows={rows}
      editingLine={1}
      onEditLine={jest.fn()}
      onChangeLine={(lineNumber, value) => {
        setRows([
          {
            kind: "context",
            beforeLine: 1,
            afterLine: lineNumber,
            text: value,
          },
        ]);
      }}
      onStopEditing={jest.fn()}
    />
  );
}

describe("DocumentDiffViewer", () => {
  it("keeps the active textarea mounted when diff classification changes while editing", () => {
    render(<DiffEditorHarness />);

    const editor = screen.getByLabelText("Edit proposed markdown line 1");

    fireEvent.change(editor, {
      target: {
        value: "Updated proposed line",
      },
    });

    expect(screen.getByLabelText("Edit proposed markdown line 1")).toBe(editor);
  });
});
