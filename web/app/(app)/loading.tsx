import { LoadingState } from "@/components/states/loading-state";

/**
 * Between a click in the sidebar and the page it opens, inside the shell.
 *
 * Next shows this while the next page's code is fetched. On a laptop that is
 * a few milliseconds and LoadingState shows nothing at all; on a slow
 * connection it is the difference between "loading" and "the click did not
 * register".
 */
export default function Loading() {
  return <LoadingState />;
}
