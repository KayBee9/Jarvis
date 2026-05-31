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

// Shape of a memory as returned bz GET /api/memories
type Memory = {
  id: string;
  content: string;
  created_at: string;
};

// Home page component. Renders the chat UI and manages its state.
export default function Home() {
  // Current text in the input field.
  const [input, setInput] = useState("");
  // All messages sent so far, in chronological order.
  const [messages, setMessages] = useState<Message[]>([]);

  // Conversation ID returned by the backend on the first message, reused on every subsequent message for context
  const [conversationId, setConversationId] = useState<string | null>(null);

  // ID of the memory are successfully saved
  const [savedMemoryId, setSavedMemoryId] = useState<Set<string>>(new Set());
  // ID of the memory that is currently being saved
  const [savingMemoryIds, setSavingMemoryIds] = useState<Set<string>>(new Set());
  // The current "Save to memory" button state, or null if it's closed (design choice to only allow one memory draft at a time for simplicity)
  const [memoryDraft, setMemoryDraft] = useState<{ memoryId: string; content: string } | null>(null);
  
  // Reference to an invisible element at the bottom of the message list.
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Wether the memories panel is open
  const [isPanelOpen, setIsPanelOpen] = useState(false);
  // All  memories fetched from the backend
  const [memories, setMemories] = useState<Memory[]>([]);
  // True while a fetch is in flight
  const [isLoadingMemories, setIsLoadingMemories] = useState(false);

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
          conversation_id: conversationId,
        }),
      });
      if (!response.ok) throw new Error(`Chat request failed with ${response.status}`);
      const data = await response.json();
      // React automatically sets the ID only once if it's always the same
      setConversationId(data.conversation_id);


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
  
  // Function to save a memory, 
  // called when the user clicks "Save" in the memory draft modal
  async function saveMemory(memoryId: string, content: string) {
    setSavingMemoryIds((current) => new Set(current).add(memoryId));
    try {
      const response = await fetch(`${apiBaseUrl}/api/memories`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      if (!response.ok) throw new Error(`Memory save failed with ${response.status}`);
      setSavedMemoryId((current) => new Set(current).add(memoryId));
    } catch (error) {
      console.error(error);
    } finally {
      setSavingMemoryIds((current) => {
        const next = new Set(current);
        next.delete(memoryId);
        return next;
      });
    }
  }

  // Function to load memories, called when the user opens the memories panel
  async function loadMemories() {
    setIsLoadingMemories(true);
    try{
      const response = await fetch(`${apiBaseUrl}/api/memories`);
      if (!response.ok) throw new Error(`Failed to load Memories ${response.status}`);
      const data = await response.json();
      setMemories(data);
    } catch (error) {
      console.error(error);
    } finally {
      setIsLoadingMemories(false);
    }
  }

  //whenever the panel opens, fetch fresh memories.
  useEffect(() => {
    if (isPanelOpen) {
      void loadMemories();
    }
  }, [isPanelOpen]);

  return (
    <main className="flex flex-1 flex-col items-center">
      <div className="jarvis-orb" aria-hidden="true" />

      <button 
        type="button"
        onClick={() => setIsPanelOpen(true)}
        className="fixed top-4 right-4 z-30 rounded-full border border-border bg-background px-4 py-2 text-xs text-muted hover:text-foreground"
      >
        Memories
      </button>

      <div className="flex w-full max-w-3xl flex-1 flex-col px-4 pt-16 pb-6">
        <div className="flex-1 min-h-0 overflow-y-auto space-y-3">
          {
            messages.map((m) => {
              const isSaved = savedMemoryId.has(m.id);
              const isSaving = savingMemoryIds.has(m.id);
              return (
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
                  <button
                    type="button"
                    onClick={() => setMemoryDraft({ memoryId: m.id, content: m.content })}
                    disabled={isSaved || isSaving}
                    className="text-xs text-muted hover:text-foreground disabled:cursor-default px-2"
                  >
                    {isSaved ? "✓ Saved" : isSaving ? "Saving..." : "Save to memory"}
                  </button>
                </div>
              );
            })}
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
      
      {/* Memory panel, shown when the user clicks the "Memories" button*/}
      {isPanelOpen && (
        <div
        className = "fixed inset-0 z-40 bg-black/40"
        onClick={() => setIsPanelOpen(false)}
        >
          <aside
            className="fixed right-0 top-0 flex h-screen w-full max-w-md flex-col border-1 border-border bg-background shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <h2 className="text-sm font-semibold">Memories</h2>
              <button 
                type="button"
                onClick={() => setIsPanelOpen(false)}
                className="text-muted hover:text-foreground"
                aria-label="Close panel"
              >
                ×
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-10">
              {isLoadingMemories ? (
                <p className="text-sm text-muted">Loading...</p>
              ) : memories.length === 0 ? (
                <p className="text-sm text-muted">No memories yet. Save some from the chat!</p>
              ) : (
                <ul className="space-y-3">
                  {memories.map((memory) => (
                    <li
                      key={memory.id}
                      className="rounded-xl border border-border p-3 text-sm"
                    >
                      <p className="whitespace-pre-wrap break-words">{memory.content}</p>
                      <p className="mt-2 text-xs text-muted">
                        {new Date(memory.created_at).toLocaleDateString()}
                      </p>
                    </li>
                  ))}
                </ul> 
              )}
            </div>
          </aside>
        </div>
      )}

      {/* Modal for "Save to memory" with textarea to edit the content before saving, 
          only shown when memoryDraft is not null
      */}
      {memoryDraft && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
          onClick={() => setMemoryDraft(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl border border-border bg-background p-5"
            onClick={(e) => e.stopPropagation()}
          >
            <h2 className="text-base font-semibold">Save to memory</h2>
            <p className="mt-1 text-xs text-muted">
              Edit this into a clean fact you want Jarvis to remember.
            </p>
            <textarea
              autoFocus
              className="mt-3 w-full resize-none rounded-xl border border-border bg-background p-3 text-sm outline-none field-sizing-content max-h-48"
              value={memoryDraft.content}
              onChange={(e) =>
                setMemoryDraft((current) => 
                  current ? { ...current, content: e.target.value } : current,
                )
              }
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setMemoryDraft(null)}
                className="rounded-full px-4 py-1.5 text-sm text-muted hover:text-foreground"
              >
                Cancel
              </button>
              <button
              type="button"
              disabled={!memoryDraft.content.trim()}
              onClick={async() => {
                const draft = memoryDraft;
                setMemoryDraft(null);
                await saveMemory(draft.memoryId, draft.content.trim());
              }}
              className="rounded-full bg-foreground px-4 py-1.5 text-sm text-background disabled:opacity-50"
            >
              Save
            </button>
          </div>
        </div>
      </div>

    )}  
  </main>
  );
}
