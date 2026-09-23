import { redirect } from "next/navigation";

import { routes } from "@/config/routes";

/**
 * The root sends you to the overview.
 *
 * Every zone of the product has a named path — /overview included — so the
 * registry in config/routes.ts describes the whole information architecture
 * without one entry having to be "the one with no path of its own".
 */
export default function Index() {
  redirect(routes.overview());
}
