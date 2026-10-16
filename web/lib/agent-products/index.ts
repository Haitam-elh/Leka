import { BUILD } from "@/lib/agent-products/build";
import { FRONT } from "@/lib/agent-products/front";
import { RUN } from "@/lib/agent-products/run";
import type { AgentProduct } from "@/lib/agent-products/types";

export * from "@/lib/agent-products/types";

/** Every agent on sale, said to whoever might buy it (LEKA-471) — one
 * structure, one place. An agent not here (a draft, one not on sale) has
 * no product page of its own: its page says only what the API says. */
export const AGENT_PRODUCTS: Readonly<Record<string, AgentProduct>> = { ...BUILD, ...RUN, ...FRONT };

export function productOf(key: string): AgentProduct | null {
  return AGENT_PRODUCTS[key] ?? null;
}
