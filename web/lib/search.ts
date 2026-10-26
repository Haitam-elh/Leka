/**
 * Where the palette's results come from.
 *
 * The seam, and since LEKA-369 the company model's search behind it: the
 * palette finds things and goes to them. Answering about them is the
 * Context Engine's job (LEKA-371 and after).
 *
 * THE RULE. The palette finds and goes. It never answers. A question typed
 * into it — "pourquoi l'API de paiement est lente ?" — is not a search, it
 * is an intention, and the palette offers to create one rather than
 * inventing an answer beside the product's actual workflow.
 */

export interface SearchResult {
  id: string;
  /** What the person reads. */
  label: string;
  /** "Service", "Document", "Source"… — what kind of thing this is. */
  kind: string;
  href: string;
}

export type SearchProvider = (query: string) => Promise<readonly SearchResult[]>;

/** Finds nothing: the palette before it is given the knowledge search. */
export const emptySearchProvider: SearchProvider = async () => [];

/**
 * The company model's search (LEKA-369): the entities whose names — then
 * whose other words — match what was typed, each to its page. Two letters
 * at least; a failure finds nothing rather than breaking the palette. What
 * a question is still goes to an intention, first in the palette.
 */
export function knowledgeSearchProvider(
  label: (type: string) => string,
  href: (entity: { id: string; type: string }) => string,
  search: (q: string) => Promise<{ entities: readonly SearchHitLike[] }>,
): SearchProvider {
  return async (query) => {
    const typed = query.trim();
    if (typed.length < 2) return [];
    try {
      const found = await search(typed);
      return found.entities.map(({ entity, holder }) => ({
        id: entity.id,
        label: holder ? `${entity.name} · ${holder.name}` : entity.name,
        kind: label(entity.type),
        href: href(entity),
      }));
    } catch {
      return [];
    }
  };
}

interface SearchHitLike {
  entity: { id: string; type: string; name: string };
  holder?: { name: string } | null;
}

/**
 * Whether what was typed reads as a question rather than a lookup.
 *
 * Used to put "créer une intention" first: someone asking why something is
 * slow wants the analysis, not a list of files whose name contains "slow".
 */
export function looksLikeAQuestion(query: string): boolean {
  const trimmed = query.trim();
  if (trimmed.length === 0) return false;
  if (trimmed.endsWith("?")) return true;
  if (trimmed.split(/\s+/).length >= 4) return true;
  return /^(pourquoi|comment|quand|qui|que|quel|quelle|est-ce|why|how|when|who|what|which|is|are)\b/i.test(
    trimmed,
  );
}
