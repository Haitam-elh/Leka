import { retrieverName } from "@/components/intelligence/context-used";
import type { IntentGap } from "@/lib/context";
import { fill } from "@/lib/i18n/dictionaries";
import type { useDictionary } from "@/lib/i18n/locale-provider";

/**
 * What an intention's reading found missing (LEKA-373), in words — from
 * its kind and what it was read from. Its own module: step 2 and the
 * context's quality (LEKA-375) both say it.
 */

type Dictionary = ReturnType<typeof useDictionary>;

/** A gap in words, from its kind and what it was read from. */
export function gapSaid(t: Dictionary, gap: IntentGap): string {
  const w = t.intent.gaps.kinds as Record<string, string>;
  const detail = (gap.detail ?? {}) as Record<string, unknown>;
  const list = (value: unknown) => (Array.isArray(value) ? value.map(String) : []);
  const capabilities = t.intent.capabilities as Record<string, string>;
  switch (gap.kind) {
    case "no_subject": {
      const maybe = list(detail.maybe);
      return maybe.length
        ? `${w.no_subject} ${fill(t.intent.gaps.maybe, { names: maybe.join(", ") })}`
        : w.no_subject;
    }
    case "ambiguous_subject":
      return fill(w.ambiguous_subject, {
        said: String(detail.said ?? ""),
        count: Array.isArray(detail.things) ? detail.things.length : 0,
      });
    case "unknown_service":
      return fill(w.unknown_service, { count: list(detail.ids).length });
    case "unknown_environment":
      return fill(w.unknown_environment, { environment: String(detail.environment ?? "") });
    case "no_source_for":
      return fill(w.no_source_for, {
        needs: list(detail.needs)
          .map((need) => capabilities[need] ?? need)
          .join(", "),
      });
    case "no_event_anchor": {
      const anchors = t.intent.anchors as Record<string, string>;
      const anchor = String(detail.anchor ?? "");
      return fill(w.no_event_anchor, { anchor: anchors[anchor] ?? anchor });
    }
    case "model_stale":
      return fill(w.model_stale, { hours: Number(detail.hours ?? 0) });
    case "retriever_failed":
      return fill(w.retriever_failed, {
        retriever: retrieverName(t, String(detail.retriever ?? "")),
      });
    case "disputed_subject":
      return fill(w.disputed_subject, { about: String(detail.about ?? "") });
    default:
      return w[gap.kind] ?? gap.said;
  }
}
