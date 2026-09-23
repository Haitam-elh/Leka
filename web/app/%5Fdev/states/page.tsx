import { notFound } from "next/navigation";

import { StatesGallery } from "./gallery";

/**
 * Every system state, side by side (LEKA-343).
 *
 * The states that matter most are the ones nobody sees while building a
 * screen: the API down, the connection gone, a page that crashed. Each is
 * rendered here from the real component, so a change to one can be judged
 * before it reaches the screen that will need it at the worst moment.
 *
 * Development only, like /_dev/forms beside it — see that page for why the
 * folder is spelled %5Fdev.
 */
export default function Page() {
  if (process.env.NODE_ENV === "production") notFound();
  return <StatesGallery />;
}
