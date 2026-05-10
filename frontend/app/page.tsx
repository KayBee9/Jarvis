"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  BookmarkPlus,
  Check,
  Library,
  Loader2,
  Mic,
  MicOff,
  Send,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";

import { useVoice } from "@/hooks/useVoice";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
};

type ChatResponse = {
  conversation_id: string;
  assistant_message: string;
  response_id: string | null;
};

type Memory = {
  id: string;
  content: string;
  created_at: string;
};

type PendingDelete = {
  memory: Memory;
  timeoutId: ReturnType<typeof setTimeout>;
};

// TODO: when refreshing the page, and only refreshing the page, reload the messages
// from that session.


const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Hi, I am Jarvis. Phase 1 is text chat: ask me something and I will keep the conversation going.",
    },
  ]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedMessageIds, setSavedMessageIds] = useState<Set<string>>(new Set());
  const [savingMessageIds, setSavingMessageIds] = useState<Set<string>>(new Set());
  const [memoryDraft, setMemoryDraft] = useState<
    { messageId: string; content: string } | null
  >(null);
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);
  const formRef = useRef<HTMLFormElement>(null);

  const visibleMemories = useMemo(
    () => memories.filter((m) => m.id !== pendingDelete?.memory.id),
    [memories, pendingDelete],
  );

  async function loadMemories() {
    setIsLoadingMemories(true);
    try {
      const response = await fetch(`${apiBaseUrl}/api/memories`);
      if (!response.ok) {
        throw new Error(`Load failed with ${response.status}`);
      }
      const data = (await response.json()) as Memory[];
      setMemories(data);
    } catch (loadError) {
      setError(
        loadError instanceof Error ? loadError.message : "Could not load memories.",
      );
    } finally {
      setIsLoadingMemories(false);
    }
  }

  async function commitDelete(memoryId: string) {
    try {
      const response = await fetch(`${apiBaseUrl}/api/memories/${memoryId}`, {
        method: "DELETE",
      });
      if (!response.ok) {
        throw new Error(`Delete failed with ${response.status}`);
      }
      setMemories((current) => current.filter((m) => m.id !== memoryId));
    } catch (deleteError) {
      setError(
        deleteError instanceof Error ? deleteError.message : "Could not delete memory.",
      );
    }
  }

  function handleDelete(memory: Memory) {
    if (pendingDelete) {
      clearTimeout(pendingDelete.timeoutId);
      void commitDelete(pendingDelete.memory.id);
    }
    const timeoutId = setTimeout(() => {
      void commitDelete(memory.id);
      setPendingDelete(null);
    }, 5000);
    setPendingDelete({ memory, timeoutId });
  }

  function handleUndo() {
    if (!pendingDelete) return;
    clearTimeout(pendingDelete.timeoutId);
    setPendingDelete(null);
  }

  useEffect(() => {
    if (isPanelOpen) {
      void loadMemories();
    }
  }, [isPanelOpen]);

  async function saveMemory(messageId: string, content: string) {
    setSavingMessageIds((current) => new Set(current).add(messageId));
    try {
      const response = await fetch(`${apiBaseUrl}/api/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) {
        throw new Error(`Save failed with ${response.status}`);
      }
      setSavedMessageIds((current) => new Set(current).add(messageId));
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : "Could not save memory.",
      );
    } finally {
      setSavingMessageIds((current) => {
        const next = new Set(current);
        next.delete(messageId);
        return next;
      });
    }
  }

  const handleTranscript = useCallback((text: string) => {
    setInput(text);
  }, []);

  const { isListening, isSupported, startListening, stopListening, speak } =
    useVoice(handleTranscript);

  const canSend = useMemo(
    () => input.trim().length > 0 && !isSending,
    [input, isSending],
  );

  async function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const message = input.trim();
    if (!message) {
      return;
    }

    setError(null);
    setInput("");
    setIsSending(true);

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: message,
    };
    setMessages((current) => [...current, userMessage]);

    try {
      const response = await fetch(`${apiBaseUrl}/api/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
        }),
      });

      if (!response.ok) {
        throw new Error(`Chat request failed with ${response.status}`);
      }

      const data = (await response.json()) as ChatResponse;
      setConversationId(data.conversation_id);
      setMessages((current) => [
        ...current,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content: data.assistant_message,
        },
      ]);
      speak(data.assistant_message);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Something went wrong.",
      );
    } finally {
      setIsSending(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col bg-background">
      <header className="border-b border-border bg-background/90 px-5 py-4">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Sparkles className="h-5 w-5" aria-hidden="true" />
            </div>
            <div>
              <h1 className="text-lg font-semibold leading-tight">Jarvis</h1>
              <p className="text-sm text-muted-foreground">Core text agent</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Button
              aria-label="Open memories"
              onClick={() => setIsPanelOpen(true)}
              size="icon"
              type="button"
              variant="ghost"
            >
              <Library className="h-4 w-4" aria-hidden="true" />
            </Button>
            <div className="hidden rounded-md border border-border px-3 py-1 text-xs text-muted-foreground sm:block">
              Phase 1
            </div>
          </div>
        </div>
      </header>

      <section className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-5">
        <div className="flex-1 space-y-4 overflow-y-auto rounded-md border border-border bg-white p-4 shadow-sm">
          {messages.map((message) => {
            const isSaved = savedMessageIds.has(message.id);
            const isSaving = savingMessageIds.has(message.id);
            const showSaveButton = message.id !== "welcome";

            return (
              <article
                className={cn(
                  "flex flex-col gap-1",
                  message.role === "user" ? "items-end" : "items-start",
                )}
                key={message.id}
              >
                <div
                  className={cn(
                    "max-w-[min(760px,85%)] rounded-md px-4 py-3 text-sm leading-6",
                    message.role === "user"
                      ? "bg-primary text-primary-foreground"
                      : "border border-border bg-background text-foreground",
                  )}
                >
                  {message.content}
                </div>
                {showSaveButton && (
                  <button
                    aria-label={isSaved ? "Saved to memory" : "Save to memory"}
                    className={cn(
                      "flex items-center gap-1 px-2 py-1 text-xs text-muted-foreground transition-colors",
                      isSaved ? "text-green-600" : "hover:text-foreground",
                    )}
                    disabled={isSaved || isSaving}
                    onClick={() =>
                      setMemoryDraft({ messageId: message.id, content: message.content })
                    }
                    type="button"
                  >
                    {isSaving ? (
                      <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                    ) : isSaved ? (
                      <Check className="h-3 w-3" aria-hidden="true" />
                    ) : (
                      <BookmarkPlus className="h-3 w-3" aria-hidden="true" />
                    )}
                    {isSaved ? "Saved" : isSaving ? "Saving..." : "Save to memory"}
                  </button>
                )}
              </article>
            );
          })}
          {isSending ? (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-md border border-border bg-background px-4 py-3 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                Thinking
              </div>
            </div>
          ) : null}
        </div>

        {error ? (
          <p className="mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </p>
        ) : null}

        <form
          className="mt-4 flex flex-col gap-3 rounded-md border border-border bg-white p-3 shadow-sm"
          onSubmit={submitMessage}
          ref={formRef}
        >
          <Textarea
            aria-label="Message Jarvis"
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
                formRef.current?.requestSubmit();
              }
            }}
            placeholder="Message Jarvis..."
            value={input}
          />
          <div className="flex items-center justify-between gap-3">
            <p className="text-xs text-muted-foreground">
              {isSupported ? "Ctrl+Enter to send · mic to speak" : "Ctrl+Enter to send"}
            </p>
            <div className="flex items-center gap-2">
              {isSupported && (
                <Button
                  aria-label={isListening ? "Stop listening" : "Start voice input"}
                  onClick={isListening ? stopListening : startListening}
                  size="icon"
                  type="button"
                  variant="ghost"
                  className={isListening ? "text-red-500 animate-pulse" : ""}
                >
                  {isListening ? (
                    <MicOff className="h-4 w-4" aria-hidden="true" />
                  ) : (
                    <Mic className="h-4 w-4" aria-hidden="true" />
                  )}
                </Button>
              )}
              <Button disabled={!canSend} type="submit">
                {isSending ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
                ) : (
                  <Send className="mr-2 h-4 w-4" aria-hidden="true" />
                )}
                Send
              </Button>
            </div>
          </div>
        </form>
      </section>

      {isPanelOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/40"
          onClick={() => setIsPanelOpen(false)}
        >
          <aside
            aria-label="Memories panel"
            className="fixed right-0 top-0 flex h-screen w-full max-w-md flex-col border-l border-border bg-white shadow-xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-base font-semibold">Memories</h2>
              <Button
                aria-label="Close memories"
                onClick={() => setIsPanelOpen(false)}
                size="icon"
                type="button"
                variant="ghost"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {isLoadingMemories ? (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />
                  Loading...
                </div>
              ) : visibleMemories.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  No memories yet. Save one from the chat.
                </p>
              ) : (
                <ul className="space-y-2">
                  {visibleMemories.map((memory) => (
                    <li
                      className="flex items-start justify-between gap-3 rounded-md border border-border p-3"
                      key={memory.id}
                    >
                      <div className="flex-1 text-sm">
                        <p className="leading-6">{memory.content}</p>
                        <p className="mt-1 text-xs text-muted-foreground">
                          {new Date(memory.created_at).toLocaleDateString()}
                        </p>
                      </div>
                      <Button
                        aria-label="Delete memory"
                        onClick={() => handleDelete(memory)}
                        size="icon"
                        type="button"
                        variant="ghost"
                      >
                        <Trash2 className="h-4 w-4" aria-hidden="true" />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </aside>
        </div>
      )}

      {pendingDelete && (
        <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-md border border-border bg-white px-4 py-2 text-sm shadow-lg">
          <span>Memory deleted</span>
          <Button
            onClick={handleUndo}
            size="default"
            type="button"
            variant="ghost"
          >
            Undo
          </Button>
        </div>
      )}

      {memoryDraft && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          onClick={() => setMemoryDraft(null)}
        >
          <div
            className="w-full max-w-md rounded-md border border-border bg-white p-4 shadow-lg"
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="text-base font-semibold">Save to memory</h2>
            <p className="mt-1 text-xs text-muted-foreground">
              Edit this into a clean fact you want Jarvis to remember.
            </p>
            <Textarea
              autoFocus
              className="mt-3"
              onChange={(event) =>
                setMemoryDraft((current) =>
                  current ? { ...current, content: event.target.value } : current,
                )
              }
              value={memoryDraft.content}
            />
            <div className="mt-3 flex items-center justify-end gap-2">
              <Button
                onClick={() => setMemoryDraft(null)}
                type="button"
                variant="ghost"
              >
                Cancel
              </Button>
              <Button
                disabled={!memoryDraft.content.trim()}
                onClick={async () => {
                  const draft = memoryDraft;
                  setMemoryDraft(null);
                  await saveMemory(draft.messageId, draft.content.trim());
                }}
                type="button"
              >
                Save
              </Button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
