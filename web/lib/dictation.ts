"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Speaking an intention instead of typing it (2026-10-29: the « Dictée »
 * button said « Bientôt »). The browser's own speech recognition: nothing
 * to install, no key, no cost — Chrome, Edge and Safari have it; where a
 * browser has none, nothing is offered.
 *
 * What is said is written where the text stands: after what was already
 * typed, a space between, the words heard so far shown as they come and
 * replaced by the final ones. Speaking again goes on from there.
 */

/** What the browser's recognition gives back, as much as is read here. */
interface Heard {
  readonly isFinal: boolean;
  readonly 0: { readonly transcript: string };
}
interface HeardEvent {
  readonly resultIndex: number;
  readonly results: ArrayLike<Heard>;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: HeardEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
}
type RecognitionClass = new () => Recognition;

function recognitionClass(): RecognitionClass | null {
  if (typeof window === "undefined") return null;
  const found = window as unknown as {
    SpeechRecognition?: RecognitionClass;
    webkitSpeechRecognition?: RecognitionClass;
  };
  return found.SpeechRecognition ?? found.webkitSpeechRecognition ?? null;
}

/** True when this browser can dictate. */
export function canDictate(): boolean {
  return recognitionClass() !== null;
}

/** Why dictation stopped short, as the composer says it. */
export type DictationProblem = "denied" | "no_microphone" | "no_speech" | "network" | "failed";

const PROBLEMS: Record<string, DictationProblem> = {
  "not-allowed": "denied",
  "service-not-allowed": "denied",
  "audio-capture": "no_microphone",
  "no-speech": "no_speech",
  network: "network",
};

/** `before`, then `said`: a space between when both have words. */
export function joined(before: string, said: string): string {
  const words = said.trim();
  if (!words) return before;
  if (!before.trim()) return words;
  return /\s$/.test(before) ? before + words : `${before} ${words}`;
}

export function useDictation({
  language,
  text,
  onText,
}: {
  /** The language it is spoken in: « fr-FR », « en-US »… */
  language: string;
  /** The text as it stands when dictation starts. */
  text: () => string;
  /** The text with what was said so far. */
  onText: (value: string) => void;
}) {
  const [listening, setListening] = useState(false);
  const [problem, setProblem] = useState<DictationProblem | null>(null);
  const recognition = useRef<Recognition | null>(null);

  // Never left listening once the composer is gone.
  useEffect(() => () => recognition.current?.abort(), []);

  const stop = useCallback(() => recognition.current?.stop(), []);

  const start = useCallback(() => {
    const Found = recognitionClass();
    if (!Found || recognition.current) return;
    const heard = new Found();
    heard.lang = language;
    heard.continuous = true;
    heard.interimResults = true;
    const before = text();
    let final = "";
    heard.onresult = (event) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) final = joined(final, result[0].transcript);
        else interim = joined(interim, result[0].transcript);
      }
      onText(joined(before, joined(final, interim)));
    };
    heard.onerror = (event) => {
      // Stopped by hand: no problem to tell.
      if (event.error === "aborted") return;
      setProblem(PROBLEMS[event.error] ?? "failed");
    };
    heard.onend = () => {
      recognition.current = null;
      setListening(false);
    };
    recognition.current = heard;
    setProblem(null);
    try {
      heard.start();
      setListening(true);
    } catch {
      recognition.current = null;
      setProblem("failed");
    }
  }, [language, onText, text]);

  return { listening, problem, start, stop };
}
