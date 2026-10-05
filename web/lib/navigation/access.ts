/**
 * What a person may see, and what they may open.
 *
 * Two different questions, deliberately answered by two functions:
 *
 *   canOpen            the page itself. A "no" shows the refusal state, in
 *                      the shell, so the person knows the page exists and
 *                      who to ask.
 *   visibleNavigation  what the sidebar and the palette offer
 *                      (lib/navigation/tree.ts). A page they may never open
 *                      is not offered at all — a list of links that refuse
 *                      is a list nobody trusts.
 *
 * NEITHER IS A SECURITY BOUNDARY. Hiding a link hides a link. The data
 * behind it is protected by the API, which checks the same permissions
 * server side and refuses whatever the browser believes.
 */

import type { RouteEntry } from "@/config/routes";

export function canOpen(route: RouteEntry, permissions: readonly string[]): boolean {
  return route.requiredPermission === undefined || permissions.includes(route.requiredPermission);
}
