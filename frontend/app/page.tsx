"use client";

import { FormEvent, useCallback, useMemo, useRef, useState } from "react";
import { Loader2, Mic, MicOff, Send, Sparkles } from "lucide-react";

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
  const formRef = useRef<HTMLFormElement>(null);

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
          <div className="hidden rounded-md border border-border px-3 py-1 text-xs text-muted-foreground sm:block">
            Phase 1
          </div>
        </div>
      </header>

      <section className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-5 py-5">
        <div className="flex-1 space-y-4 overflow-y-auto rounded-md border border-border bg-white p-4 shadow-sm">
          {messages.map((message) => (
            <article
              className={cn(
                "flex",
                message.role === "user" ? "justify-end" : "justify-start",
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
            </article>
          ))}
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
    </main>
  );
}
