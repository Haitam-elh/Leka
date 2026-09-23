import { notFound } from "next/navigation";

import { FormsGallery } from "./gallery";

/**
 * Every field, in every state, on one page.
 *
 * It exists because the states that break are the ones nobody looks at: a
 * disabled combobox, a list that failed to load, a counter one character
 * from its limit. A screen that uses a field shows one of its states; this
 * shows all of them, side by side, which is the only way a change to the
 * wrapper can be judged before it reaches four screens.
 *
 * Development only. It is not in config/routes.ts, so it is not in the
 * navigation, not in the palette and not reachable by anything but its
 * address — and in a production build that address is a 404.
 *
 * WHY THE FOLDER IS CALLED %5Fdev. Next treats a folder starting with an
 * underscore as private and leaves it out of routing entirely; `_dev` made
 * this page unreachable in every build, development included, and nobody
 * noticed because nothing linked to it. `%5F` is an encoded underscore:
 * the documented way to get a URL segment that starts with one.
 */
export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <FormsGallery />;
}
