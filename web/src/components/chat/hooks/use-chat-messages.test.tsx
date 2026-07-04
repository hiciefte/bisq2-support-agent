import { act, cleanup, renderHook } from "@testing-library/react";

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

describe("useChatMessages", () => {
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
        if (url.includes("/chat/query")) {
          const next = queryResponses.shift();
          if (!next) {
            throw new Error(`Unexpected /chat/query call: ${url}`);
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
        .filter(([input]) => String(input).includes("/chat/query"))
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
        jsonResponse({ answer: "All good now" }),
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
      queryResponses.push(jsonResponse({ answer: "Fresh answer" }));

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
  });
});
