"use client";

/**
 * A voice, recorded (2026-10-29): what « Dictée » sends to LEKA to be
 * written. The browser's own speech recognition wrote nothing in some
 * browsers; recording works in every one. Kept as WAV — 16 kHz, one
 * channel — the one format every transcription provider reads.
 */

const RATE = 16_000;

type AudioContextClass = typeof AudioContext;

function audioContext(): AudioContextClass | null {
  if (typeof window === "undefined") return null;
  const found = window as unknown as { AudioContext?: AudioContextClass; webkitAudioContext?: AudioContextClass };
  return found.AudioContext ?? found.webkitAudioContext ?? null;
}

/** True when this browser can record a voice. */
export function canRecord(): boolean {
  if (typeof window === "undefined" || typeof navigator === "undefined") return false;
  return (
    typeof navigator.mediaDevices?.getUserMedia === "function" &&
    typeof window.MediaRecorder === "function" &&
    audioContext() !== null
  );
}

/** Why recording could not start. */
export class RecordingRefused extends Error {
  constructor(readonly why: "denied" | "no_microphone" | "failed") {
    super(why);
  }
}

export interface Recording {
  /** Stopped: what was said, as WAV. */
  stop: () => Promise<Blob>;
  /** Dropped: nothing kept. */
  cancel: () => void;
}

export async function startRecording(): Promise<Recording> {
  let stream: MediaStream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (error) {
    const name = error instanceof DOMException ? error.name : "";
    throw new RecordingRefused(
      name === "NotAllowedError" || name === "SecurityError"
        ? "denied"
        : name === "NotFoundError" || name === "OverconstrainedError"
          ? "no_microphone"
          : "failed",
    );
  }
  const recorder = new MediaRecorder(stream);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size) chunks.push(event.data);
  };
  const release = () => stream.getTracks().forEach((track) => track.stop());
  recorder.start(250);
  return {
    stop: () =>
      new Promise<Blob>((resolve, reject) => {
        recorder.onstop = () => {
          release();
          toWav(new Blob(chunks, { type: recorder.mimeType || "audio/webm" })).then(resolve, reject);
        };
        recorder.stop();
      }),
    cancel: () => {
      recorder.onstop = release;
      if (recorder.state !== "inactive") recorder.stop();
      else release();
    },
  };
}

/** A recording, as 16-bit WAV at RATE Hz, one channel. */
export async function toWav(recorded: Blob): Promise<Blob> {
  const Context = audioContext();
  if (!Context) throw new RecordingRefused("failed");
  const context = new Context();
  let decoded: AudioBuffer;
  try {
    decoded = await context.decodeAudioData(await recorded.arrayBuffer());
  } finally {
    void context.close();
  }
  const length = Math.max(1, Math.ceil(decoded.duration * RATE));
  const offline = new OfflineAudioContext(1, length, RATE);
  const source = offline.createBufferSource();
  source.buffer = decoded;
  source.connect(offline.destination);
  source.start();
  const samples = (await offline.startRendering()).getChannelData(0);
  return wav(samples, RATE);
}

/** PCM samples (-1…1), as a WAV file. */
export function wav(samples: Float32Array, rate: number): Blob {
  const bytes = new DataView(new ArrayBuffer(44 + samples.length * 2));
  const text = (at: number, said: string) => {
    for (let i = 0; i < said.length; i++) bytes.setUint8(at + i, said.charCodeAt(i));
  };
  text(0, "RIFF");
  bytes.setUint32(4, 36 + samples.length * 2, true);
  text(8, "WAVE");
  text(12, "fmt ");
  bytes.setUint32(16, 16, true);
  bytes.setUint16(20, 1, true); // PCM
  bytes.setUint16(22, 1, true); // one channel
  bytes.setUint32(24, rate, true);
  bytes.setUint32(28, rate * 2, true);
  bytes.setUint16(32, 2, true);
  bytes.setUint16(34, 16, true);
  text(36, "data");
  bytes.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, i) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    bytes.setInt16(44 + i * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
  });
  return new Blob([bytes.buffer], { type: "audio/wav" });
}
