/**
 * Hook for managing chat messages, API communication, and message state
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { v4 as uuidv4 } from "uuid";
import { API_BASE_URL } from "@/lib/config";
import type { McpToolUsage, Message, Source } from "../types/chat.types";

const MAX_CHAT_HISTORY_LENGTH = 8;
const CHAT_STORAGE_KEY = "bisq_chat_messages";
const REQUEST_TIMEOUT_MS = 600_000;
const LOCAL_STORAGE_DEBOUNCE_MS = 1_000;
const GLOBAL_STATS_FALLBACK_SECONDS = 12;

type JsonRecord = Record<string, unknown>;

const isJsonRecord = (value: unknown): value is JsonRecord =>
    typeof value === "object" && value !== null;

const isFiniteNumber = (value: unknown): value is number =>
    typeof value === "number" && Number.isFinite(value);

const generateUUID = (): string => {
    try {
        if (
            typeof globalThis !== "undefined" &&
            globalThis.crypto &&
            typeof globalThis.crypto.randomUUID === "function"
        ) {
            return globalThis.crypto.randomUUID();
        }
        return uuidv4();
    } catch {
        return uuidv4();
    }
};

const cleanupResponse = (text: string): string => text.replace(/```+\s*$/, "").trim();

const loadingMessages = [
    "Hang tight, our AI's flexing on a potato CPU-your answer's dropping in {time}!",
    "Grandma's dial-up soup takes longer than this-AI's got you in {time}!",
    "Chill, the AI's meditating with a modem for {time} before it enlightens you!",
    "Hamster union break! The AI's back in {time} with your fix!",
    "AI's procrastinating like a champ-give it {time} to stumble over!",
    "Turtles in molasses? That's our CPUs-your reply's {time} out!",
    "AI's sharpening its crayon-your answer's scribbled in {time}!",
    "Coffee break with a 56k vibe-AI's buzzing back in {time}!",
    "Sloth-mode AI: slow, steady, and {time} from brilliance!",
    "CPUs moonwalking your request-give 'em {time} to slide in!",
    "Drunk penguin AI waddling your way- ETA {time}!",
    "AI's arguing with a floppy disk-your turn's in {time}!",
    "Running on Wi-Fi fumes-AI's coughing up an answer in {time}!",
    "Mini-vacay time! AI's wrestling a calculator for {time}!",
    "Stuck in a 90s dial-up loop-AI escapes in {time}!",
    "Snail rave on the CPUs-your answer drops in {time}!",
    "AI's teaching a toaster binary-your toast pops in {time}!",
    "Smoking with a Commodore 64-AI hacks back in {time}!",
    "One-handed juggling with a brick-AI's ready in {time}!",
    "Unicycle CPU uphill grind-your answer's {time} away!",
];

const formatResponseTime = (seconds: number): string =>
    seconds < 60 ? `${Math.round(seconds)} seconds` : `${Math.round(seconds / 60)} minutes`;

const getRandomLoadingMessage = (avgTime: number): string => {
    const randomIndex = Math.floor(Math.random() * loadingMessages.length);
    return loadingMessages[randomIndex].replace("{time}", formatResponseTime(avgTime));
};

const parseSource = (value: unknown): Source | null => {
    if (!isJsonRecord(value)) {
        return null;
    }

    const { title, type, content } = value;
    if (
        typeof title !== "string" ||
        (type !== "wiki" && type !== "faq") ||
        typeof content !== "string"
    ) {
        return null;
    }

    return {
        title,
        type,
        content,
        protocol:
            value.protocol === "bisq_easy" ||
            value.protocol === "multisig_v1" ||
            value.protocol === "all"
                ? value.protocol
                : undefined,
        url: typeof value.url === "string" ? value.url : undefined,
        section: typeof value.section === "string" ? value.section : undefined,
        similarity_score: isFiniteNumber(value.similarity_score)
            ? value.similarity_score
            : undefined,
    };
};

const parseSources = (value: unknown): Source[] | undefined => {
    if (!Array.isArray(value)) {
        return undefined;
    }
    const parsed = value.map(parseSource).filter((source): source is Source => source !== null);
    return parsed.length > 0 ? parsed : undefined;
};

const parseMcpTools = (value: unknown): McpToolUsage[] | undefined => {
    if (!Array.isArray(value)) {
        return undefined;
    }

    const tools = value
        .filter(isJsonRecord)
        .filter((tool) => typeof tool.tool === "string" && typeof tool.timestamp === "string")
        .map((tool) => ({
            tool: tool.tool as string,
            timestamp: tool.timestamp as string,
            result: typeof tool.result === "string" ? tool.result : undefined,
        }));

    return tools.length > 0 ? tools : undefined;
};

const parseStoredMessage = (value: unknown): Message | null => {
    if (!isJsonRecord(value)) {
        return null;
    }

    if (
        typeof value.id !== "string" ||
        typeof value.content !== "string" ||
        (value.role !== "user" && value.role !== "assistant")
    ) {
        return null;
    }

    const timestamp =
        typeof value.timestamp === "string" && !Number.isNaN(Date.parse(value.timestamp))
            ? new Date(value.timestamp)
            : new Date();

    const metadata =
        isJsonRecord(value.metadata) &&
        isFiniteNumber(value.metadata.response_time) &&
        isFiniteNumber(value.metadata.token_count)
            ? {
                  response_time: value.metadata.response_time,
                  token_count: value.metadata.token_count,
              }
            : undefined;

    return {
        id: value.id,
        content: value.content,
        role: value.role,
        timestamp,
        rating: isFiniteNumber(value.rating) ? value.rating : undefined,
        sources: parseSources(value.sources),
        metadata,
        confidence: isFiniteNumber(value.confidence) ? value.confidence : undefined,
        detected_version:
            typeof value.detected_version === "string" ? value.detected_version : undefined,
        version_confidence: isFiniteNumber(value.version_confidence)
            ? value.version_confidence
            : undefined,
        isThankYouMessage:
            typeof value.isThankYouMessage === "boolean" ? value.isThankYouMessage : undefined,
        mcp_tools_used: parseMcpTools(value.mcp_tools_used),
        routing_action: typeof value.routing_action === "string" ? value.routing_action : undefined,
        requires_human:
            typeof value.requires_human === "boolean" ? value.requires_human : undefined,
        escalation_message_id:
            typeof value.escalation_message_id === "string"
                ? value.escalation_message_id
                : undefined,
        staff_response: parseStaffResponse(value.staff_response),
    };
};

const parseStaffResponse = (
    value: unknown,
): { answer: string; responded_at: string } | undefined => {
    if (!isJsonRecord(value)) {
        return undefined;
    }
    if (typeof value.answer === "string" && typeof value.responded_at === "string") {
        return { answer: value.answer, responded_at: value.responded_at };
    }
    return undefined;
};

const parseStoredMessages = (rawValue: string | null): Message[] => {
    if (!rawValue) {
        return [];
    }

    try {
        const parsed: unknown = JSON.parse(rawValue);
        if (!Array.isArray(parsed)) {
            return [];
        }
        return parsed
            .map(parseStoredMessage)
            .filter((message): message is Message => message !== null);
    } catch {
        return [];
    }
};

export const useChatMessages = () => {
    // Start empty to keep server/client first render consistent, then hydrate from storage on mount.
    const [messages, setMessages] = useState<Message[]>([]);
    const [storageHydrated, setStorageHydrated] = useState(false);

    const [input, setInput] = useState("");
    const [isLoading, setIsLoading] = useState(false);
    const [loadingMessage, setLoadingMessage] = useState("");
    const [globalAverageResponseTime, setGlobalAverageResponseTime] = useState<number>(300);

    const messagesRef = useRef<Message[]>([]);
    const saveTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        messagesRef.current = messages;
    }, [messages]);

    const debouncedSaveToLocalStorage = useCallback((msgs: Message[]) => {
        if (saveTimeoutRef.current) {
            clearTimeout(saveTimeoutRef.current);
        }
        saveTimeoutRef.current = setTimeout(() => {
            if (typeof window === "undefined") {
                return;
            }
            try {
                localStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(msgs));
            } catch {
                // Ignore quota/storage exceptions to keep chat functional.
            }
        }, LOCAL_STORAGE_DEBOUNCE_MS);
    }, []);

    useEffect(() => {
        if (typeof window === "undefined") {
            return;
        }

        try {
            setMessages(parseStoredMessages(localStorage.getItem(CHAT_STORAGE_KEY)));
        } finally {
            setStorageHydrated(true);
        }
    }, []);

    useEffect(() => {
        if (!storageHydrated || typeof window === "undefined") {
            return;
        }

        if (messages.length > 0) {
            debouncedSaveToLocalStorage(messages);
        } else {
            try {
                localStorage.removeItem(CHAT_STORAGE_KEY);
            } catch {
                // Ignore storage exceptions to avoid breaking UI interactions.
            }
        }

        return () => {
            if (saveTimeoutRef.current) {
                clearTimeout(saveTimeoutRef.current);
            }
        };
    }, [messages, debouncedSaveToLocalStorage, storageHydrated]);

    useEffect(() => {
        const controller = new AbortController();
        let isCancelled = false;

        const fetchGlobalStats = async () => {
            try {
                const response = await fetch(`${API_BASE_URL}/chat/stats`, {
                    signal: controller.signal,
                });

                if (!response.ok) {
                    if (!isCancelled) {
                        setGlobalAverageResponseTime(GLOBAL_STATS_FALLBACK_SECONDS);
                    }
                    return;
                }

                const stats: unknown = await response.json();
                if (!isJsonRecord(stats)) {
                    if (!isCancelled) {
                        setGlobalAverageResponseTime(GLOBAL_STATS_FALLBACK_SECONDS);
                    }
                    return;
                }

                const avgTime = isFiniteNumber(stats.last_24h_average_response_time)
                    ? stats.last_24h_average_response_time
                    : isFiniteNumber(stats.average_response_time)
                      ? stats.average_response_time
                      : GLOBAL_STATS_FALLBACK_SECONDS;

                if (!isCancelled) {
                    setGlobalAverageResponseTime(avgTime);
                }
            } catch (error) {
                if (
                    !isCancelled &&
                    !(error instanceof DOMException && error.name === "AbortError")
                ) {
                    setGlobalAverageResponseTime(GLOBAL_STATS_FALLBACK_SECONDS);
                }
            }
        };

        fetchGlobalStats();

        return () => {
            isCancelled = true;
            controller.abort();
        };
    }, []);

    const avgResponseTime = useMemo(() => {
        const responseTimes = messages
            .filter(
                (msg) =>
                    msg.role === "assistant" && isFiniteNumber(msg.metadata?.response_time),
            )
            .map((msg) => msg.metadata!.response_time);

        if (responseTimes.length === 0) {
            return globalAverageResponseTime;
        }

        return responseTimes.reduce((acc, time) => acc + time, 0) / responseTimes.length;
    }, [messages, globalAverageResponseTime]);

    useEffect(() => {
        if (isLoading) {
            setLoadingMessage(getRandomLoadingMessage(avgResponseTime));
        }
    }, [isLoading, avgResponseTime]);

    const sendMessage = useCallback(
        async (text: string) => {
            const normalizedText = text.trim();
            if (!normalizedText || isLoading) {
                return;
            }

            const userMessage: Message = {
                id: generateUUID(),
                content: normalizedText,
                role: "user",
                timestamp: new Date(),
            };

            const messageSnapshot = [...messagesRef.current, userMessage];
            messagesRef.current = messageSnapshot;
            setMessages(messageSnapshot);

            setInput("");
            setIsLoading(true);

            try {
                const controller = new AbortController();
                const timeoutId = setTimeout(
                    () => controller.abort(),
                    REQUEST_TIMEOUT_MS,
                );

                const chatHistory = messageSnapshot
                    .map((msg) => ({
                        role: msg.role,
                        content: msg.content,
                    }))
                    .slice(-MAX_CHAT_HISTORY_LENGTH);

                let response: Response;
                try {
                    response = await fetch(`${API_BASE_URL}/chat/query`, {
                        method: "POST",
                        headers: {
                            "Content-Type": "application/json",
                        },
                        body: JSON.stringify({
                            question: normalizedText,
                            chat_history: chatHistory,
                        }),
                        signal: controller.signal,
                    });
                } finally {
                    clearTimeout(timeoutId);
                }

                if (!response.ok) {
                    let detail = `Server returned ${response.status}. Please try again.`;
                    try {
                        const errorBody: unknown = await response.json();
                        if (isJsonRecord(errorBody) && typeof errorBody.detail === "string") {
                            detail = errorBody.detail;
                        }
                    } catch {
                        // Keep default detail when error body cannot be parsed.
                    }

                    setMessages((prev) => [
                        ...prev,
                        {
                            id: generateUUID(),
                            content: `Error: ${detail}`,
                            role: "assistant",
                            timestamp: new Date(),
                        },
                    ]);
                    return;
                }

                const data: unknown = await response.json();
                const payload = isJsonRecord(data) ? data : {};
                const answer = typeof payload.answer === "string" ? payload.answer : "";

                const assistantMessage: Message = {
                    id: generateUUID(),
                    content: cleanupResponse(answer),
                    role: "assistant",
                    timestamp: new Date(),
                    sources: parseSources(payload.sources),
                    metadata: {
                        response_time: isFiniteNumber(payload.response_time)
                            ? payload.response_time
                            : 0,
                        token_count: isFiniteNumber(payload.token_count)
                            ? payload.token_count
                            : 0,
                    },
                    confidence: isFiniteNumber(payload.confidence) ? payload.confidence : undefined,
                    detected_version:
                        typeof payload.detected_version === "string"
                            ? payload.detected_version
                            : undefined,
                    version_confidence: isFiniteNumber(payload.version_confidence)
                        ? payload.version_confidence
                        : undefined,
                    mcp_tools_used: parseMcpTools(payload.mcp_tools_used),
                    routing_action:
                        typeof payload.routing_action === "string"
                            ? payload.routing_action
                            : undefined,
                    requires_human:
                        typeof payload.requires_human === "boolean"
                            ? payload.requires_human
                            : undefined,
                    escalation_message_id:
                        typeof payload.escalation_message_id === "string"
                            ? payload.escalation_message_id
                            : undefined,
                };

                setMessages((prev) => [...prev, assistantMessage]);
            } catch (error: unknown) {
                let errorContent = "An error occurred while processing your request.";

                if (
                    (error instanceof DOMException && error.name === "AbortError") ||
                    (error instanceof Error && error.name === "AbortError")
                ) {
                    errorContent =
                        "The request took too long to complete. The server might be busy processing your question. Please try again later or ask a simpler question.";
                } else if (error instanceof Error && process.env.NODE_ENV !== "production") {
                    errorContent = `An error occurred: ${error.name} - ${error.message}. Please try again.`;
                }

                setMessages((prev) => [
                    ...prev,
                    {
                        id: generateUUID(),
                        content: cleanupResponse(errorContent),
                        role: "assistant",
                        timestamp: new Date(),
                    },
                ]);
            } finally {
                setIsLoading(false);
            }
        },
        [isLoading],
    );

    const clearChatHistory = useCallback(() => {
        messagesRef.current = [];
        setMessages([]);
        setInput("");
    }, []);

    return {
        messages,
        setMessages,
        input,
        setInput,
        isLoading,
        loadingMessage,
        avgResponseTime,
        sendMessage,
        clearChatHistory,
    };
};
