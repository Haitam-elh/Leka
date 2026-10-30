"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { intentions } from "@/lib/intentions/api";
import { canRecord, type Recording, RecordingRefused, startRecording } from "@/lib/recorder";

/**
 * Speaking an intention instead of typing it. The voice is recorded
 * (lib/recorder) and written by LEKA's transcription (POST
 * /intentions/transcriptions): the browser's own speech recognition wrote
 * nothing in some browsers (2026-10-29: « je clique, je parle, rien ne
 * s'écrit »), a recording works in every one.
 *
 * What is said is written after what was typed, a space between. Two
 * minutes at most: stopped then, and written.
 */

/** True when this browser can dictate. */
export function canDictate(): boolean {
  return canRecord();
}

/** Why dictation stopped short, as the composer says it. */
export type DictationProblem = "denied" | "no_microphone" | "no_speech" | "unavailable" | "failed";

/** Two minutes of speech at most. */
export const MOST_SECONDS = 120;

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
  /** The language it is spoken in: « fr-FR », « en »… */
  language: string;
  /** The text as it stands once what was said is written. */
  text: () => string;
  /** The text with what was said. */
  onText: (value: string) => void;
}) {
  const [listening, setListening] = useState(false);
  const [writing, setWriting] = useState(false);
  const [seconds, setSeconds] = useState(0);
  const [problem, setProblem] = useState<DictationProblem | null>(null);
  const recording = useRef<Recording | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const clock = (on: boolean) => {
    if (timer.current) clearInterval(timer.current);
    timer.current = null;
    if (on) {
      setSeconds(0);
      timer.current = setInterval(() => setSeconds((s) => s + 1), 1000);
    }
  };

  // Never left recording once the composer is gone.
  useEffect(
    () => () => {
      recording.current?.cancel();
      if (timer.current) clearInterval(timer.current);
    },
    [],
  );

  const stop = useCallback(async () => {
    const held = recording.current;
    if (!held) return;
    recording.current = null;
    clock(false);
    setListening(false);
    setWriting(true);
    try {
      const audio = await held.stop();
      const said = (await intentions.transcribe(audio, language)).text;
      if (!said.trim()) setProblem("no_speech");
      else onText(joined(text(), said));
    } catch (error) {
      setProblem(error instanceof ApiError && error.status === 503 ? "unavailable" : "failed");
    } finally {
      setWriting(false);
    }
  }, [language, onText, text]);

  const start = useCallback(async () => {
    if (recording.current || writing) return;
    setProblem(null);
    try {
      recording.current = await startRecording();
    } catch (error) {
      setProblem(error instanceof RecordingRefused ? error.why : "failed");
      return;
    }
    setListening(true);
    clock(true);
  }, [writing]);

  // Two minutes: stopped, and written.
  useEffect(() => {
    if (listening && seconds >= MOST_SECONDS) void stop();
  }, [listening, seconds, stop]);

  return { listening, writing, seconds, problem, start, stop };
}
