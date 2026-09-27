/**
 * A source's events in the timeline's words.
 *
 * What these protect: an event whose label has blanks gets them filled —
 * never "{version}" on screen — and every event type has its label.
 */

import { describe, expect, it } from "vitest";

import { timelineEvent } from "@/components/sources/source-panel";
import { DICTIONARIES } from "@/lib/i18n/dictionaries";
import type { SourceEvent } from "@/lib/sources";

function event(type: SourceEvent["type"], payload: Record<string, unknown>): SourceEvent {
  return {
    id: "e-1",
    source_id: "s-1",
    type,
    actor_user_id: null,
    payload,
    created_at: "2026-09-28T08:00:00Z",
  } as SourceEvent;
}

describe("timelineEvent", () => {
  it("names the settings version a change made", () => {
    const fr = timelineEvent(DICTIONARIES.fr, event("settings_changed", { version: 3 }));
    const en = timelineEvent(DICTIONARIES.en, event("settings_changed", { version: 3 }));

    expect(fr.title).toBe("Périmètre ou correspondances modifiés (version 3)");
    expect(en.title).toBe("Scope or mapping changed (version 3)");
  });

  it("leaves no blank unfilled for any event type", () => {
    const types = Object.keys(DICTIONARIES.en.sources.events) as SourceEvent["type"][];
    for (const type of types) {
      const title = timelineEvent(
        DICTIONARIES.en,
        event(type, { version: 1, previous: "healthy", current: "failing" }),
      ).title;
      expect(title, type).not.toMatch(/[{}]/);
    }
  });
});
