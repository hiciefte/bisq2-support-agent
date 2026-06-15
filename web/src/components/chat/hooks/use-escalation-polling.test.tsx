import { act, render, screen, waitFor } from "@testing-library/react";

import { useEscalationPolling } from "./use-escalation-polling";

const MESSAGE_ID = "12345678-1234-1234-1234-123456789abc";

class MockEventSource {
  static instances: MockEventSource[] = [];

  readonly url: string;
  readonly close = jest.fn();
  private readonly listeners = new Map<string, Array<(event: MessageEvent) => void>>();

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  addEventListener(eventName: string, listener: (event: MessageEvent) => void) {
    const listeners = this.listeners.get(eventName) ?? [];
    listeners.push(listener);
    this.listeners.set(eventName, listeners);
  }

  emit(eventName: string, data: unknown) {
    const event = { data: JSON.stringify(data) } as MessageEvent;
    for (const listener of this.listeners.get(eventName) ?? []) {
      listener(event);
    }
  }
}

function Harness({
  enabled = true,
  messageId = MESSAGE_ID,
}: {
  enabled?: boolean;
  messageId?: string | null;
}) {
  const result = useEscalationPolling(messageId, enabled);

  return (
    <div>
      <div data-testid="status">{result.status}</div>
      <div data-testid="answer">{result.staffAnswer ?? ""}</div>
      <div data-testid="resolution">{result.resolution ?? ""}</div>
      <div data-testid="rate-token">{result.rateToken ?? ""}</div>
    </div>
  );
}

describe("useEscalationPolling", () => {
  beforeEach(() => {
    MockEventSource.instances = [];
    Object.defineProperty(window, "EventSource", {
      configurable: true,
      writable: true,
      value: MockEventSource,
    });
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
    delete (window as Window & { EventSource?: typeof EventSource }).EventSource;
  });

  test("resolves immediately from the escalation SSE stream", async () => {
    render(<Harness />);

    expect(MockEventSource.instances).toHaveLength(1);
    expect(MockEventSource.instances[0].url).toBe(
      `/api/escalations/${MESSAGE_ID}/events`,
    );

    act(() => {
      MockEventSource.instances[0].emit("escalation", {
        status: "resolved",
        staff_answer: "Staff answer",
        responded_at: "2026-06-12T10:00:00Z",
        resolution: "responded",
        rate_token: "signed-token",
      });
    });

    await waitFor(() =>
      expect(screen.getByTestId("answer")).toHaveTextContent("Staff answer"),
    );
    expect(screen.getByTestId("status")).toHaveTextContent("resolved");
    expect(screen.getByTestId("resolution")).toHaveTextContent("responded");
    expect(screen.getByTestId("rate-token")).toHaveTextContent("signed-token");
    expect(MockEventSource.instances[0].close).toHaveBeenCalledTimes(1);
    expect(global.fetch).not.toHaveBeenCalled();
  });

  test("falls back to polling when EventSource is unavailable", async () => {
    delete (window as Window & { EventSource?: typeof EventSource }).EventSource;
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        status: "resolved",
        staff_answer: "Fallback answer",
        responded_at: "2026-06-12T10:00:00Z",
        resolution: "responded",
      }),
    });

    render(<Harness />);

    await waitFor(() =>
      expect(screen.getByTestId("answer")).toHaveTextContent("Fallback answer"),
    );
    expect(global.fetch).toHaveBeenCalledWith(
      `/api/escalations/${MESSAGE_ID}/response`,
    );
  });
});
