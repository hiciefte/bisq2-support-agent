import { act, cleanup, renderHook } from "@testing-library/react";
import { ReadableStream as NodeReadableStream } from "node:stream/web";
import {
  TextDecoder as NodeTextDecoder,
  TextEncoder as NodeTextEncoder,
} from "node:util";

import { useChatMessages } from "./use-chat-messages";
import type { Message } from "../types/chat.types";

const CHAT_STORAGE_KEY = "bisq_chat_messages";

type ChatHistoryEntry = { role: string; content: string };
type ChatQueryBody = { question: string; chat_history: ChatHistoryEntry[] };

const jsonResponse = (
  body: unknown,
  init?: { ok?: boolean; status?: number },
): Response =>
  ({
    ok: init?.ok ?? true,
    status: init?.status ?? 200,
    json: async () => body,
  }) as unknown as Response;

const streamEvent = (event: string, data: unknown): string =>
  `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

const streamResponse = (events: string[]): Response =>
  ({
    ok: true,
    status: 200,
    body: new NodeReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new NodeTextEncoder();
        for (const event of events) {
          controller.enqueue(encoder.encode(event));
        }
        controller.close();
      },
    }),
  }) as unknown as Response;

const finalStreamResponse = (body: unknown): Response =>
  streamResponse([streamEvent("final", body)]);

describe("useChatMessages", () => {
  beforeAll(() => {
    Object.assign(globalThis, {
      TextDecoder: NodeTextDecoder,
      TextEncoder: NodeTextEncoder,
    });
  });

  afterEach(() => {
    // Unmount before clearing storage: RTL's automatic cleanup would run
    // after this hook and the unmount flush would repopulate localStorage.
    cleanup();
    jest.useRealTimers();
    jest.restoreAllMocks();
    localStorage.clear();
  });

  describe("chat_history payload", () => {
    let queryResponses: Response[];
    let fetchMock: jest.Mock;

    beforeEach(() => {
      queryResponses = [];
      fetchMock = jest.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/chat/query/stream")) {
          const next = queryResponses.shift();
          if (!next) {
            throw new Error(`Unexpected /chat/query/stream call: ${url}`);
          }
          return next;
        }
        if (url.includes("/chat/stats")) {
          return jsonResponse({});
        }
        throw new Error(`Unexpected fetch: ${url}`);
      });
      global.fetch = fetchMock as unknown as typeof fetch;
    });

    const getQueryBodies = (): ChatQueryBody[] =>
      fetchMock.mock.calls
        .filter(([input]) => String(input).includes("/chat/query/stream"))
        .map(([, init]) => JSON.parse(String((init as RequestInit).body)));

    test("marks client-generated error bubbles with isError while keeping them visible", async () => {
      queryResponses.push(
        jsonResponse({ detail: "upstream exploded" }, { ok: false, status: 500 }),
      );

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("first question");
      });

      const errorMessage = result.current.messages.at(-1);
      expect(errorMessage?.role).toBe("assistant");
      expect(errorMessage?.content).toContain("upstream exploded");
      expect(errorMessage?.isError).toBe(true);
    });

    test("excludes client error bubbles from the chat_history sent to the API", async () => {
      queryResponses.push(
        jsonResponse({ detail: "upstream exploded" }, { ok: false, status: 500 }),
        finalStreamResponse({ answer: "All good now" }),
      );

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("first question");
      });
      await act(async () => {
        await result.current.sendMessage("second question");
      });

      const bodies = getQueryBodies();
      expect(bodies).toHaveLength(2);
      expect(bodies[1].chat_history).toEqual([
        { role: "user", content: "first question" },
        { role: "user", content: "second question" },
      ]);
    });

    test("excludes error bubbles restored from localStorage from chat_history", async () => {
      localStorage.setItem(
        CHAT_STORAGE_KEY,
        JSON.stringify([
          {
            id: "u1",
            role: "user",
            content: "older question",
            timestamp: "2026-07-01T10:00:00.000Z",
          },
          {
            id: "e1",
            role: "assistant",
            content: "Error: previous failure",
            timestamp: "2026-07-01T10:00:05.000Z",
            isError: true,
          },
        ]),
      );
      queryResponses.push(finalStreamResponse({ answer: "Fresh answer" }));

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("new question");
      });

      const bodies = getQueryBodies();
      expect(bodies).toHaveLength(1);
      expect(bodies[0].chat_history).toEqual([
        { role: "user", content: "older question" },
        { role: "user", content: "new question" },
      ]);
    });

    test("clearChatHistory aborts active request and ignores late responses", async () => {
      let resolveQuery: (response: Response) => void = () => {};
      let querySignal: AbortSignal | undefined;
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/chat/query/stream")) {
          querySignal = init?.signal as AbortSignal | undefined;
          return new Promise<Response>((resolve) => {
            resolveQuery = resolve;
          });
        }
        if (url.includes("/chat/stats")) {
          return jsonResponse({});
        }
        throw new Error(`Unexpected fetch: ${url}`);
      });

      const { result } = renderHook(() => useChatMessages());
      let request: Promise<void> = Promise.resolve();

      act(() => {
        request = result.current.sendMessage("question before clear");
      });

      expect(result.current.messages).toHaveLength(1);

      act(() => {
        result.current.clearChatHistory();
      });

      expect(querySignal?.aborted).toBe(true);

      await act(async () => {
        resolveQuery(finalStreamResponse({ answer: "Late answer" }));
        await request;
      });

      expect(result.current.messages).toEqual([]);
      expect(result.current.isLoading).toBe(false);
    });

    test("cancelCurrentRequest aborts active request and ignores late responses", async () => {
      let resolveQuery: (response: Response) => void = () => {};
      let querySignal: AbortSignal | undefined;
      fetchMock.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/chat/query/stream")) {
          querySignal = init?.signal as AbortSignal | undefined;
          return new Promise<Response>((resolve) => {
            resolveQuery = resolve;
          });
        }
        if (url.includes("/chat/stats")) {
          return jsonResponse({});
        }
        throw new Error(`Unexpected fetch: ${url}`);
      });

      const { result } = renderHook(() => useChatMessages());
      let request: Promise<void> = Promise.resolve();

      act(() => {
        request = result.current.sendMessage("question before cancel");
      });

      act(() => {
        result.current.cancelCurrentRequest();
      });

      expect(querySignal?.aborted).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.messages.map((message) => message.content)).toEqual([
        "question before cancel",
        "Request canceled.",
      ]);

      await act(async () => {
        resolveQuery(finalStreamResponse({ answer: "Late answer" }));
        await request;
      });

      expect(result.current.messages.map((message) => message.content)).toEqual([
        "question before cancel",
        "Request canceled.",
      ]);
    });

    test("streams tokens and replaces the draft with final metadata", async () => {
      queryResponses.push(
        streamResponse([
          streamEvent("token", { content: "Partial " }),
          streamEvent("token", { content: "answer" }),
          streamEvent("final", {
            message_id: "web_final-message",
            answer: "Final answer",
            sources: [
              {
                title: "Bisq guide",
                type: "wiki",
                content: "Source content",
                protocol: "all",
              },
            ],
            response_time: 1.2,
            token_count: 42,
            confidence: 0.91,
            detected_version: "bisq2",
            version_confidence: 0.83,
            routing_action: "auto_send",
            ui_labels: {
              helpful_prompt: "Was this helpful?",
              helpful_thank_you: "Thanks for the feedback.",
              staff_helpful_prompt: "Was the staff response helpful?",
              staff_response_label: "Staff response",
              support_team_notified: "Support team notified.",
            },
          }),
        ]),
      );

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("stream question");
      });

      const streamCall = fetchMock.mock.calls.find(([input]) =>
        String(input).includes("/chat/query/stream"),
      );
      expect(streamCall?.[0]).toContain("/chat/query/stream");
      expect(result.current.messages).toHaveLength(2);
      const assistantMessage = result.current.messages[1];
      expect(assistantMessage.id).toBe("web_final-message");
      expect(assistantMessage.content).toBe("Final answer");
      expect(assistantMessage.sources?.[0].title).toBe("Bisq guide");
      expect(assistantMessage.metadata?.response_time).toBe(1.2);
      expect(assistantMessage.metadata?.token_count).toBe(42);
      expect(assistantMessage.confidence).toBe(0.91);
      expect(assistantMessage.detected_version).toBe("bisq2");
      expect(assistantMessage.version_confidence).toBe(0.83);
      expect(assistantMessage.routing_action).toBe("auto_send");
      expect(assistantMessage.ui_labels?.staff_response_label).toBe(
        "Staff response",
      );
    });

    test("uses final stream answer for human escalation messages", async () => {
      queryResponses.push(
        streamResponse([
          streamEvent("token", { content: "Draft answer" }),
          streamEvent("final", {
            message_id: "web_escalated-message",
            answer: "Support team notified.",
            sources: [],
            response_time: 0.7,
            requires_human: true,
            escalation_message_id: "web_escalated-message",
            user_language: "de",
          }),
        ]),
      );

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("needs human");
      });

      const assistantMessage = result.current.messages[1];
      expect(assistantMessage.content).toBe("Support team notified.");
      expect(assistantMessage.requires_human).toBe(true);
      expect(assistantMessage.escalation_message_id).toBe("web_escalated-message");
      expect(assistantMessage.escalation_user_language).toBe("de");
    });

    test("replaces a streamed draft with an error event message", async () => {
      queryResponses.push(
        streamResponse([
          streamEvent("token", { content: "Partial draft" }),
          streamEvent("error", { detail: "backend failed" }),
        ]),
      );

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("stream fails");
      });

      expect(result.current.messages).toHaveLength(2);
      const assistantMessage = result.current.messages[1];
      expect(assistantMessage.content).toContain("backend failed");
      expect(assistantMessage.isError).toBe(true);
    });

    test("replaces a streamed draft when the stream ends without final", async () => {
      queryResponses.push(
        streamResponse([
          streamEvent("token", { content: "Partial draft" }),
        ]),
      );

      const { result } = renderHook(() => useChatMessages());

      await act(async () => {
        await result.current.sendMessage("stream ends early");
      });

      expect(result.current.messages).toHaveLength(2);
      const assistantMessage = result.current.messages[1];
      expect(assistantMessage.content).toContain(
        "Response stream ended before the final event",
      );
      expect(assistantMessage.isError).toBe(true);
    });
  });

  describe("localStorage persistence", () => {
    beforeEach(() => {
      jest.useFakeTimers();
      // Keep the stats request pending so it never updates state mid-test.
      global.fetch = jest.fn(
        () => new Promise<Response>(() => {}),
      ) as unknown as typeof fetch;
    });

    const makeMessage = (content: string): Message => ({
      id: "m1",
      content,
      role: "assistant",
      timestamp: new Date(),
    });

    test("debounces steady-state saves", () => {
      const { result } = renderHook(() => useChatMessages());

      act(() => {
        result.current.setMessages([makeMessage("Debounced answer")]);
      });

      expect(localStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();

      act(() => {
        jest.advanceTimersByTime(1_000);
      });

      const stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? "[]");
      expect(stored).toHaveLength(1);
      expect(stored[0].content).toBe("Debounced answer");
    });

    test("flushes the pending save when unmounted before the debounce fires", () => {
      const { result, unmount } = renderHook(() => useChatMessages());

      act(() => {
        result.current.setMessages([makeMessage("Almost lost answer")]);
      });

      expect(localStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();

      unmount();

      const stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? "[]");
      expect(stored).toHaveLength(1);
      expect(stored[0].content).toBe("Almost lost answer");
    });

    test("flushes the pending save on pagehide", () => {
      const { result } = renderHook(() => useChatMessages());

      act(() => {
        result.current.setMessages([makeMessage("Answer before refresh")]);
      });

      expect(localStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();

      act(() => {
        window.dispatchEvent(new Event("pagehide"));
      });

      const stored = JSON.parse(localStorage.getItem(CHAT_STORAGE_KEY) ?? "[]");
      expect(stored).toHaveLength(1);
      expect(stored[0].content).toBe("Answer before refresh");
    });

    test("does not resurrect cleared messages on unmount", () => {
      const { result, unmount } = renderHook(() => useChatMessages());

      act(() => {
        result.current.setMessages([makeMessage("Soon cleared")]);
      });
      act(() => {
        result.current.clearChatHistory();
      });

      unmount();

      expect(localStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();
    });

    test("does not resurrect cleared messages when unmounted before effects run", () => {
      const { result, unmount } = renderHook(() => useChatMessages());

      act(() => {
        // Fire-and-forget: the mocked fetch never resolves, so only the
        // synchronous user-message state update lands and schedules the
        // debounced save.
        void result.current.sendMessage("Sensitive question");
      });

      // Debounce has not fired yet; the save is only pending in memory.
      expect(localStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();

      act(() => {
        // Clear and unmount in the same act so the unmount cleanup flush
        // runs before the emptied-messages effect could cancel the save.
        result.current.clearChatHistory();
        unmount();
      });

      expect(localStorage.getItem(CHAT_STORAGE_KEY)).toBeNull();
    });

    test("merges messages from another tab by message id", () => {
      const { result } = renderHook(() => useChatMessages());

      const localMessage: Message = {
        id: "local-message",
        content: "Local answer",
        role: "assistant",
        timestamp: new Date("2026-07-01T10:00:00.000Z"),
      };
      const remoteMessage = {
        id: "remote-message",
        content: "Remote answer",
        role: "assistant",
        timestamp: "2026-07-01T10:01:00.000Z",
      };

      act(() => {
        result.current.setMessages([localMessage]);
      });

      act(() => {
        window.dispatchEvent(
          new StorageEvent("storage", {
            key: CHAT_STORAGE_KEY,
            newValue: JSON.stringify([remoteMessage]),
          }),
        );
      });

      expect(result.current.messages.map((message) => message.id)).toEqual([
        "local-message",
        "remote-message",
      ]);
    });

    test("ignores storage removals from another tab", () => {
      const { result } = renderHook(() => useChatMessages());

      act(() => {
        result.current.setMessages([makeMessage("Still visible")]);
      });

      act(() => {
        window.dispatchEvent(
          new StorageEvent("storage", {
            key: CHAT_STORAGE_KEY,
            newValue: null,
          }),
        );
      });

      expect(result.current.messages).toHaveLength(1);
      expect(result.current.messages[0].content).toBe("Still visible");
    });
  });
});
