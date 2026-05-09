"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type WindowWithWebkit = typeof window & {
  webkitSpeechRecognition?: typeof SpeechRecognition;
};

export function useVoice(onTranscript: (text: string) => void) {
  const [isListening, setIsListening] = useState(false);
  const [isSupported, setIsSupported] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const onTranscriptRef = useRef(onTranscript);

  useEffect(() => {
    onTranscriptRef.current = onTranscript;
  }, [onTranscript]);

  useEffect(() => {
    const w = window as WindowWithWebkit;
    setIsSupported("SpeechRecognition" in w || "webkitSpeechRecognition" in w);
  }, []);

  const startListening = useCallback(() => {
    const w = window as WindowWithWebkit;
    const Ctor = w.webkitSpeechRecognition ?? window.SpeechRecognition;
    if (!Ctor) return;

    const recognition = new Ctor();
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.lang = "en-US";

    recognition.onresult = (event) => {
      onTranscriptRef.current(event.results[0][0].transcript);
    };
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => setIsListening(false);

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  }, []);

  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
  }, []);

  const speak = useCallback((text: string) => {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }, []);

  return { isListening, isSupported, startListening, stopListening, speak };
}
