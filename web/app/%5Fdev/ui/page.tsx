import { notFound } from "next/navigation";

import { UiGallery } from "./gallery";

/**
 * Table, Tabs and Pagination, rendered from the real components (LEKA-339).
 *
 * Development only, like /_dev/forms and /_dev/states beside it — see
 * /_dev/forms/page.tsx for why the folder is spelled %5Fdev.
 */
export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <UiGallery />;
}
