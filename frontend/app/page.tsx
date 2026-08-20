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

type PendingChange = {
  id: string;
  action: "REPLACE" | "DELETE";
  target_memory_id: string;
  target_content: string;
  proposed_content: string | null;
  created_at: string;
};

// UUID v4 generator using crypto.getRandomValues so it works over plain HTTP
// (crypto.randomUUID requires a secure context — HTTPS or localhost).
function generateId(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // UUID v4 marker
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // UUID variant marker
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

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
  // List of pending changes
  const [pendingChanges, setPendingChanges] = useState<PendingChange[]>([]);
  // Tracks which changes have in-flight approve/skip request, so we avoid double clicking
  const [processingChangeIds, setProcessingChangeIds] = useState<Set<string>>(new Set());


  // Whether the Memorie itself is open or not, in order to delete it
  const [openMemoryId, setOpenMemoryId] = useState<string | null>(null);
  // Memories currently being deleted (for loading state)
  const [deletingMemoryIds, setDeletingMemoryIds] = useState<Set<string>>(new Set());
  // A memory currently in the "deleted but undoable" window
  const [pendingDelete, setPendingDelete] = useState<{
    memory: Memory;
    timeoutId: ReturnType<typeof setTimeout>;
  } | null>(null);

  // Wether the mic is currently capturing
  const [isRecording, setIsRecording] = useState(false);
  // Holds the active MediaRecorder instance so stopRecording() can reach it
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  // Holds audio chunks as they're emitted during recording
  const audioChunksRef = useRef<Blob[]>([]);
  // Holds the active timeout for the VAD, so it can be cleared and restarted on every new audio chunk
  const vadIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Persistent audio element that gets "unlocked" on the first user gesture.
  // iOS Safari requires audio playback to be attributed to a recent trap;
  // after the first play(), the element is trusted for the rest of the session
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // ref for pending greeting
  const pendingGreetingRef = useRef<string | null>(null);


  useEffect(() => {
    const unlock = () => {
      if (audioRef.current) return;
      const audio = new Audio();
      // Tiny silent WAV - enough to satisfy the autoplay policy
      audio.src = 
        "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA=";
      audio.play().catch(() => {});
      audioRef.current = audio;

      // If a greeting was queued while audio was locked, speak it now
      if (pendingGreetingRef.current) {
        void SpeakText(pendingGreetingRef.current);
        pendingGreetingRef.current = null;
      }
    };
    document.addEventListener("touchstart", unlock, { once: true });
    document.addEventListener("mousedown", unlock, { once: true });
    return () => {
      document.removeEventListener("touchstart", unlock);
      document.removeEventListener("mousedown", unlock);
    }
  }, []);

  // Whenever messages change, scroll that bottom element into view.
  useEffect(() => {
  messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  // On mount, chack if any device is currently active. If so, join the convo
  useEffect(() => {
    async function loadInitial() {
      try {
        // Refresh case: sessionStorage still has the last conversation ID
        const storedId = sessionStorage.getItem("conversationId");
        if (storedId) {
          const response = await fetch(`${apiBaseUrl}/api/conversations/${storedId}`);
          if (response.ok) {
            const data = await response.json();
            setConversationId(data.id);
            setMessages(
              data.messages.map(
                (m: { id: string; role: string; content: string }) => ({
                  id: m.id,
                  role: m.role === "assistant" ? "jarvis" : "user",
                  content: m.content,
                }),
              ),
            );
            return;
          }
          sessionStorage.removeItem("conversationId"); // stale, clean up
        }


        // Tab-close case OR fresh install: check if any another device is active
        const activeResponse = await fetch(`${apiBaseUrl}/api/conversations/active`);
        if (activeResponse.ok) {
          const data = await activeResponse.json();
          if (data) {
            setConversationId(data.id);
            const loaded: Message[] = data.messages.map(
              (m: { id: string; role: string; content: string }) => ({
                id: m.id,
                role: m.role === "assistant" ? "jarvis" : "user",
                content: m.content,
              }),
            );
            setMessages(loaded);
            return;
          }
        }
        
        // No conversation to resume - show the startup greeting if there is one
        const greetingResponse = await fetch(`${apiBaseUrl}/api/greeting`);
        if (!greetingResponse.ok) return;
        const { greeting } = await greetingResponse.json();
        if (!greeting) return;

        setMessages([
          {
            id: `greeting-${Date.now()}`,
            role: "jarvis",
            content: greeting,
          },
        ]);

        // Speak the greeting: now if audio is unlocked, else queue for first gesture
        if (audioRef.current) {
          void SpeakText(greeting);
        } else {
          pendingGreetingRef.current = greeting;
        }
      } catch (error) {
        console.error(error);
      }
    }
    void loadInitial();
  }, []);

  useEffect(() => {
    if (conversationId) {
      sessionStorage.setItem("conversationId", conversationId);
    }
  }, [conversationId]);

  // Subscribe to SSE for current convo. Reopens when conversation_id changes.
  useEffect(() => {
    if (!conversationId) return;

    const eventSource = new EventSource(
      `${apiBaseUrl}/api/conversations/${conversationId}/stream`,
    );

    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data) as {
        id: string;
        role: string;
        content: string;
      };
      const newMessage: Message = {
        id: data.id,
        role: data.role === "assistant" ? "jarvis" : "user",
        content: data.content,
      };
      // Dedupe: don't append if we already have this message (e.g., our own send)
      setMessages((current) => {
        // Content-based dedupe: if any of the last few messages matches by role+content,
        // it's an echo of our optimistic add - skip.
        const recent = current.slice(-5);
        if (recent.some((m) => m.role === newMessage.role && m.content === newMessage.content)) {
          return current;
        }
        return [...current, newMessage];
      });
    };

    eventSource.onerror = (error) => {
      console.error("SSE error:", error);
      // EventSource auto-reconnects, no explicit reconnect logic needed
    }

    return () => eventSource.close();
  }, [conversationId]);

  // Append the input to the messages list and clear the field.
  async function sendMessage(text : string) {
    const trimmed = text.trim();
    if (!trimmed) return;

    const userMessage: Message = {
      id: generateId(),
      role: "user",
      content: trimmed,
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
        id: generateId(),
        role: "jarvis",
        content: data.assistant_message,
      };
      setMessages((current) => [...current, jarvisMessage]);
      void SpeakText(data.assistant_message);
    } catch (error) {
      console.error(error);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await sendMessage(input);
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

  // Function to actually delete the memory on server. Called from a delayed timeout,
  // or immediately if a new delete arrives before the previous one expires.
  async function commitDelete(memoryId: string) {
    setDeletingMemoryIds((current) => new Set(current).add(memoryId));
    try{
      const response = await fetch(`${apiBaseUrl}/api/memories/${memoryId}`, {
        method: "DELETE",
      });
      if (!response.ok) throw new Error(`Failed to delete Memory ${response.status}`);
    } catch (error) {
      console.error(error);
    } finally {
      setDeletingMemoryIds((current) => {
        const next = new Set(current);
        next.delete(memoryId);
        return next;
      });
    }
  }

  // Removes the memory from the panel and calls commitDelete after 5 seconds
  function softDeleteMemory(memory: Memory) {
    // If another delete is pending, commit immediately
    if (pendingDelete){
      clearTimeout(pendingDelete.timeoutId);
      void commitDelete(pendingDelete.memory.id);
    }

    // Remove from the Panel immediately
    setMemories((current) => current.filter((m) => m.id !== memory.id));
    setOpenMemoryId(null);

    // Schedule the real delete in 5s
    const timeoutId = setTimeout(() => {
      void commitDelete(memory.id);
      setPendingDelete(null);
    }, 5000);

    setPendingDelete({ memory, timeoutId });
  }

  // Cancels the pending delete and restores the memory to the panel to it's original position
  function undoDelete() {
    if (!pendingDelete) return;
    clearTimeout(pendingDelete.timeoutId);
    setMemories((current) => 
      [...current, pendingDelete.memory].sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    );
    setPendingDelete(null);
  }

  // function for Jarvis to speak every response
  async function SpeakText(text: string) {
    try {
      const response = await fetch(`${apiBaseUrl}/api/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!response.ok) throw new Error(`Speak request failed with ${response.status}`);
      const Blob = await response.blob();
      const url = URL.createObjectURL(Blob);
      // Reuse the pre-unlocked audio element (safe on iOS after first tap)
      const audio = audioRef.current ?? new Audio();
      audio.src = url;
      audio.onended = () => URL.revokeObjectURL(url);
      await audio.play();
    } catch (error) {
      console.error(error);
    }
  } 

  // Function to start recording audio from the user's microphone
  async function startRecording() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);

      // --- VAD setup ---
      const audioContext = new AudioContext();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const silenceThreshold = 8;   // RMS amplitude below this = "silence"
      const silenceDuration = 2000; // ms of silence before auto-stop
      let lastSpeechTime: number | null = null;
      let hasDetectedSpeech = false;

      audioChunksRef.current = [];

      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) audioChunksRef.current.push(event.data);
      };

      recorder.onstop = async () => {
        stream.getTracks().forEach((track) => track.stop());
        void audioContext.close();
        if (vadIntervalRef.current) {
          clearInterval(vadIntervalRef.current);
          vadIntervalRef.current = null;
        }
        setIsRecording(false);

        // Don't send if user clicked stop before speaking
        if (!hasDetectedSpeech) return;

        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        const formData = new FormData();
        formData.append("file", blob, "recording.webm");

        try {
          const response = await fetch(`${apiBaseUrl}/api/transcribe`, {
            method: "POST",
            body: formData,
          });
          if (!response.ok) throw new Error(`Transcription failed ${response.status}`);
          const data = (await response.json()) as { text: string };
          if (data.text.trim()) {
            await sendMessage(data.text);
          }
        } catch (error) {
          console.error(error);
        }
      };

      // --- VAD polling loop ---
      vadIntervalRef.current = setInterval(() => {
        analyser.getByteTimeDomainData(dataArray);

        // Compute RMS (root-mean-square) — a proxy for volume
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          const value = dataArray[i] - 128; // center waveform around 0
          sum += value * value;
        }
        const rms = Math.sqrt(sum / dataArray.length);

        const now = Date.now();
        if (rms > silenceThreshold) {
          hasDetectedSpeech = true;
          lastSpeechTime = now;
        } else if (
          hasDetectedSpeech &&
          lastSpeechTime !== null &&
          now - lastSpeechTime > silenceDuration
        ) {
          recorder.stop();
        }
      }, 50);

      recorder.start();
      mediaRecorderRef.current = recorder;
      setIsRecording(true);
    } catch (error) {
      console.error("Could not access microphone", error);
    }
  }

  // Function to stop the active recording
  function stopRecording() {
    if (vadIntervalRef.current) {
    clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
      mediaRecorderRef.current?.stop();
    }

  // Function to load Pending Changes
  async function loadPendingChanges() {
    try {
      const response = await fetch(`${apiBaseUrl}/api/memory-changes`);
      if (!response.ok) throw new Error(`Failed to load pending changes: ${response.status}`);
      const data = (await response.json()) as PendingChange[];
      setPendingChanges(data);
    } catch (error) {
      console.error(error);
    }
  }

  // Memory change APPROVE functions

  async function approveChange(id: string) {
    setProcessingChangeIds((current) => new Set(current).add(id));
    try {
      const response = await fetch(`${apiBaseUrl}/api/memory-changes/${id}/approve`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(`Approve failed: ${response.status}`);
      // Remove from local pending list and refresh memories (since one changed).
      setPendingChanges((current) => current.filter((c) => c.id !== id));
      await loadMemories();
    } catch (error) {
      console.error(error);
    } finally {
      setProcessingChangeIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  // Memory change SKIP function
  async function skipChange(id: string) {
    setProcessingChangeIds((current) => new Set(current).add(id));
    try {
      const response = await fetch(`${apiBaseUrl}/api/memory-changes/${id}/skip`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(`Skip failed: ${response.status}`);
      setPendingChanges((current) => current.filter((c) => c.id !== id));
    } catch (error) {
      console.error(error);
    } finally {
      setProcessingChangeIds((current) => {
        const next = new Set(current);
        next.delete(id);
        return next;
      });
    }
  }

  //whenever the panel opens, fetch fresh memories.
  useEffect(() => {
    if (isPanelOpen) {
      void loadMemories();
      void loadPendingChanges();
    }
  }, [isPanelOpen]);

  return (
    <main className="flex flex-1 min-h-0 flex-col items-center">
      <div className="jarvis-orb" aria-hidden="true" />

      <button 
        type="button"
        onClick={() => setIsPanelOpen(true)}
        className="fixed top-4 right-4 z-30 rounded-full border border-border bg-background px-4 py-2 text-xs text-muted hover:text-foreground"
      >
        Memories
      </button>

      <div className="flex w-full max-w-3xl flex-1 min-h-0 flex-col px-4 pt-16 pb-[max(1.5rem,env(safe-area-inset-bottom))]">
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
                  {m.role === "user" && (
                    <button
                      type="button"
                      onClick={() => setMemoryDraft({ memoryId: m.id, content: m.content })}
                      disabled={isSaved || isSaving}
                      className="text-xs text-muted hover:text-foreground disabled:cursor-default px-2"
                    >
                      {isSaved ? "✓ Saved" : isSaving ? "Saving..." : "Save to memory"}
                    </button>
                  )}
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
            className="flex-1 resize-none bg-transparent outline-none placeholder:text-muted field-sizing-content max-h-32 text-base"
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
          type="button"
          onClick={isRecording ? stopRecording : startRecording}
          className={
            isRecording
              ? "rounded-full bg-red-500 px-3 py-1.5 text-sm text-white animate-pulse"
              : "rounded-full border border-border px-3 py-1.5 text-sm text-foreground"
          }
          aria-label={isRecording ? "Stop recording" : "Start recording"}
        >
          {isRecording ? "⏹" : "🎤"}
        </button>
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
            className="fixed right-0 top-0 flex h-[100dvh] w-full max-w-md flex-col border border-border bg-background shadow-2xl"
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
            <div className="flex-1 min-h-0 overflow-y-auto p-10">
              {/* === Pending changes section (NEW) === */}
              {pendingChanges.length > 0 && (
                <div className="mb-4 space-y-2">
                  <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">
                    Pending Changes
                  </h3>
                  {pendingChanges.map((change) => {
                    const isProcessing = processingChangeIds.has(change.id);
                    return (
                      <div
                        key={change.id}
                        className="rounded-xl border border-yellow-600/40 bg-yellow-950/20 p-3 text-sm"
                      >
                        <div className="mb-2 flex items-center gap-2">
                          <span className="rounded-full bg-yellow-600/30 px-2 py-0.5 text-xs font-medium text-yellow-200">
                            {change.action}
                          </span>
                        </div>
                        <p className="text-muted line-through">{change.target_content}</p>
                        {change.proposed_content && (
                          <p className="mt-1 text-foreground">{change.proposed_content}</p>
                        )}
                        <div className="mt-3 flex gap-2">
                          <button
                            type="button"
                            onClick={() => approveChange(change.id)}
                            disabled={isProcessing}
                            className="rounded-full bg-foreground px-3 py-1 text-xs text-background disabled:opacity-50"
                          >
                            ✓ Approve
                          </button>
                          <button
                            type="button"
                            onClick={() => skipChange(change.id)}
                            disabled={isProcessing}
                            className="rounded-full border border-border px-3 py-1 text-xs text-muted hover:text-foreground disabled:opacity-50"
                          >
                            ✗ Skip
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Existing memory list*/}
              {isLoadingMemories ? (
                <p className="text-sm text-muted">Loading...</p>
              ) : memories.length === 0 ? (
                <p className="text-sm text-muted">No memories yet. Save some from the chat!</p>
              ) : (
                <ul className="space-y-3">
                  {memories.map((memory) => {
                    const isOpen = openMemoryId === memory.id;
                    const isDeleting = deletingMemoryIds.has(memory.id);
                    return (
                    <li
                      key={memory.id}
                      className="relative overflow-hidden rounded-xl border border-border"
                    >
                      {/* Delete button sits behind, revealed when content slides left */}
                      <button
                        type="button"
                        onClick={() => softDeleteMemory(memory)}
                        disabled={isDeleting}
                        className="absolute right-0 top-0 bottom-0 w-20 bg-red-600 text-sm text-white"
                      >
                        {isDeleting ? "..." : "Delete"}
                      </button>
                      {/* Content - clicking toggles to the side */}
                      <div
                        onClick={() =>
                          setOpenMemoryId((current) => (current === memory.id ? null : memory.id))
                        }
                        className={`relative bg-background p-3 text-sm cursor-pointer transition-transform ${
                          isOpen ? "-translate-x-20" : ""
                        }`}
                      >
                        <p className="whitespace-pre-wrap break-words">{memory.content}</p>
                        <p className="mt-2 text-xs text-muted">
                          {new Date(memory.created_at).toLocaleDateString()}
                        </p>
                      </div>
                    </li>
                  );
                })}
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

    {pendingDelete && (
      <div className="fixed bottom-4 left-1/2 z-50 flex -translate-x-1/2 items-center gap-3 rounded-full border border-border bg-background px-4 py-2 text-sm shadow-lg">
        <span>Memory deleted</span>
        <button
          type="button"
          onClick={undoDelete}
          className="font-medium text-foreground hover:underline"
        >
          Undo
        </button>
      </div>
    )}

  </main>
  );
}
