import { createLucideIcon } from "lucide-react";

/**
 * The navigation icons the mockups draw and lucide does not have.
 *
 * Made with lucide's own factory, so they take the same props, stroke and
 * sizing as every other icon in the sidebar and cannot drift from them. Each
 * one is traced from docs/product/mockups/01-vue-ensemble.jpeg; where lucide
 * had a match (the house, the layers, the shield, the magnifier…) it is used
 * as it is, in config/routes.ts.
 */

/** "Mon environnement": one node above, two below — lucide's GitFork, upside down. */
export const EnvironmentIcon = createLucideIcon("leka-environment", [
  ["circle", { cx: "12", cy: "6", r: "3", key: "top" }],
  ["circle", { cx: "6", cy: "18", r: "3", key: "left" }],
  ["circle", { cx: "18", cy: "18", r: "3", key: "right" }],
  ["path", { d: "M6 15v-2c0-.6.4-1 1-1h10c.6 0 1 .4 1 1v2", key: "branch" }],
  ["path", { d: "M12 12V9", key: "stem" }],
]);

/** "Activité": a single soft pulse, not a heartbeat's sharp zigzag. */
export const ActivityIcon = createLucideIcon("leka-activity", [
  ["path", { d: "M2 13h4.5c1.3 0 1.8-7 3.8-7s2.1 12 4.2 12c1.9 0 2.3-5 3.7-5H22", key: "pulse" }],
]);

/** "Capacités": four rounds, two by two. */
export const CapabilitiesIcon = createLucideIcon("leka-capabilities", [
  ["circle", { cx: "7", cy: "7", r: "3.5", key: "a" }],
  ["circle", { cx: "17", cy: "7", r: "3.5", key: "b" }],
  ["circle", { cx: "7", cy: "17", r: "3.5", key: "c" }],
  ["circle", { cx: "17", cy: "17", r: "3.5", key: "d" }],
]);

/** "Facturation": a statement — a frame, its header, a line item. */
export const BillingIcon = createLucideIcon("leka-billing", [
  ["rect", { x: "3", y: "4", width: "18", height: "16", rx: "2", key: "frame" }],
  ["path", { d: "M3 9h18", key: "header" }],
  ["rect", { x: "6.5", y: "12.5", width: "3.5", height: "3.5", rx: ".5", key: "item" }],
  ["path", { d: "M6.5 17.5h5", key: "line" }],
]);
