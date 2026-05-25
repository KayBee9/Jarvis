// Opt in to client-side rendering so we can use React state and event handlers.
"use client";

import { useEffect, useRef, useState } from "react";

const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
// Shape of one chat message held in component state.
type Message = {
  id: string;
  role: "user" | "jarvis";
  content: string;
};

// Home page component. Renders the chat UI and manages its state.
export default function Home() {
  // Current text in the input field.
  const [input, setInput] = useState("");
  // All messages sent so far, in chronological order.
  const [messages, setMessages] = useState<Message[]>([]);
  // Reference to an invisible element at the bottom of the message list.
  const messagesEndRef = useRef<HTMLDivElement>(null);
  // Whenever messages change, scroll that bottom element into view.
  useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // Append the input to the messages list and clear the field.
  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (!input.trim()) return;

    const userMessage: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: input,
    };
    setMessages((current) => [...current, userMessage]);
    setInput("");
  

    try {
      const response = await fetch(`${apiBaseUrl}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          message: userMessage.content,
          conversation_id: null,
        }),
      });
      if (!response.ok) throw new Error(`Chat request failed with ${response.status}`);
      const data = await response.json();

      const jarvisMessage: Message = {
        id: crypto.randomUUID(),
        role: "jarvis",
        content: data.assistant_message,
      };
      setMessages((current) => [...current, jarvisMessage]);
    } catch (error) {
      console.error(error);
    }
  }

  return (
    <main className="flex flex-1 flex-col items-center">
      <div className="jarvis-orb" aria-hidden="true" />
      <div className="flex w-full max-w-3xl flex-1 flex-col px-4 py-6">
        <div className="flex-1 min-h-0 overflow-y-auto space-y-3">
          {
            messages.map((m) => (
              <div 
                key={m.id} 
                className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}
              >
                <div 
                  className={
                    m.role === "user"
                      ? "max-w-[75%] whitespace-pre-wrap break-words rounded-2xl border border-border px-4 py-2 text-sm"
                      : "max-w-[85%] whitespace-pre-wrap break-words text-sm leading-6"
                  }
                >
                  {m.content}
                </div>
              </div>
            ))
          }
          <div ref={messagesEndRef} />
        </div>

        <form 
          className="mt-4 flex items-center gap-2 rounded-2xl border border-border bg-background px-4 py-3" 
          onSubmit={handleSubmit}  
        >  
          <textarea
            className="flex-1 resize-none bg-transparent outline-none placeholder:text-muted field-sizing-content max-h-32"
            placeholder="Message Jarvis..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={1}
            //makes sure the Enter key submits and shift+Enter creates a new line
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSubmit(e);
              }
            }}
          />
        <button
          className="rounded-full bg-foreground px-4 py-1.5 text-sm text-background"
          type="submit"
        >
          Send
        </button>
        </form>
      </div>  
    </main>
  );
}
