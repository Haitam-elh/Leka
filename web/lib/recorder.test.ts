/** A recording, as the transcription reads it: WAV, 16-bit, one channel. */

import { describe, expect, it } from "vitest";

import { wav } from "@/lib/recorder";

describe("a recording, as WAV", () => {
  it("is a RIFF file of 16-bit samples, one channel, at its rate", async () => {
    const said = wav(new Float32Array([0, 1, -1, 0.5]), 16_000);
    expect(said.type).toBe("audio/wav");
    const bytes = new DataView(await said.arrayBuffer());
    const text = (at: number) => String.fromCharCode(...new Uint8Array(bytes.buffer, at, 4));
    expect([text(0), text(8), text(12), text(36)]).toEqual(["RIFF", "WAVE", "fmt ", "data"]);
    expect(bytes.getUint16(22, true)).toBe(1);
    expect(bytes.getUint32(24, true)).toBe(16_000);
    expect(bytes.getUint32(40, true)).toBe(8);
    // Loud as it can be, never past what 16 bits hold.
    expect([bytes.getInt16(46, true), bytes.getInt16(48, true)]).toEqual([32767, -32768]);
  });
});
