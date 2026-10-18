"use client";

/**
 * Who is signed in, and in which workspace — asked once for the whole shell.
 *
 * Every authenticated page sits inside this provider, so /auth/me is called
 * once per visit rather than once per screen, and a page that needs the
 * current user asks a hook instead of repeating the fetch, the redirect and
 * the three failure branches.
 *
 * It reads the real session from LEKA-330 (lib/auth.ts). There is no mock
 * here on purpose: a mock would have to be removed later, and the one thing
 * that reliably survives "later" is the mock.
 *
 * TODO LEKA-331: switching workspace. The API returns the memberships and
 * which one is active; changing it is a call this provider will make, and
 * WorkspaceSwitcher already hands it the choice.
 */

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { InDemoContext } from "@/components/demo/in-demo";
import { ApiError } from "@/lib/api";
import { auth, type CurrentUser, type WorkspaceMembership } from "@/lib/auth";
import { useLanguage } from "@/lib/i18n/locale-provider";
import { type CurrentWorkspace, workspace as workspaceApi } from "@/lib/workspace";

export type ShellState =
  | { status: "loading" }
  | {
      status: "ready";
      me: CurrentUser;
      workspace: WorkspaceMembership | null;
      /**
       * What this person may do here, as the API computed it. Empty when
       * they belong to no workspace yet — which hides everything but the
       * pages that need nothing, and that is the right answer.
       */
      permissions: readonly string[];
    }
  /**
   * The shell could not be drawn. The error itself is kept, not its
   * message: ErrorState reads what KIND of failure it was — offline, the
   * API down, a bug — and words it for a person (lib/errors.ts). The
   * message was shown here once, and it read "Cannot reach the API at
   * http://localhost:8000. Is it running?" to people who run nothing.
   */
  | { status: "failed"; error: unknown };

interface ShellContextValue {
  state: ShellState;
  /** Ask again, from the start. The failure screen's "Try again". */
  retry: () => void;
  /** The person as the API answered after they changed their profile. */
  updateUser: (user: CurrentUser["user"]) => void;
  /** The active workspace renamed (LEKA-502): the header and the switcher say it. */
  renameWorkspace: (name: string) => void;
}

const ShellContext = createContext<ShellContextValue | null>(null);

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { adopt, saved } = useLanguage();
  const [state, setState] = useState<ShellState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  const retry = useCallback(() => {
    setState({ status: "loading" });
    setAttempt((previous) => previous + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        // redirectOn401: false — an anonymous visitor is sent to sign in
        // from here, in one place, rather than bounced mid-render by the
        // fetch helper.
        const me = await auth.me({ redirectOn401: false });
        // Asked together: the session says who you are, the workspace says
        // what you may do, and the shell cannot draw itself without both.
        const current: CurrentWorkspace | null =
          me.active_workspace_id === null ? null : await workspaceApi.current();
        if (cancelled) return;
        // The account's language, now known — and a choice made before
        // signing in, which the account takes (lib/i18n/resolve.ts).
        const keep = adopt(me.user, current?.workspace.default_language ?? null);
        if (keep) {
          me.user = await auth.updateProfile({ language: keep }).catch(() => me.user);
          if (me.user.language === keep) saved(keep);
        }
        if (cancelled) return;
        setState({
          status: "ready",
          me,
          workspace:
            me.workspaces.find((membership) => membership.id === me.active_workspace_id) ?? null,
          permissions: current?.permissions ?? [],
        });
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.isUnauthenticated) {
          router.replace("/login");
          return;
        }
        setState({ status: "failed", error: caught });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [router, attempt, adopt, saved]);

  // Another tab signed in as someone else, or moved the session to another
  // workspace: the cookie is the browser's, so this tab's lists already read
  // the new session under the old header (LEKA-469). Back on the tab, ask
  // again; on a change, reload the whole tab, as switching workspace does.
  const held = state.status === "ready" ? state.me : null;
  useEffect(() => {
    if (!held) return;
    const check = () => {
      if (document.visibilityState !== "visible") return;
      auth
        .me({ redirectOn401: false })
        .then((now) => {
          if (now.user.id !== held.user.id || now.active_workspace_id !== held.active_workspace_id) {
            window.location.reload();
          }
        })
        .catch((caught) => {
          if (caught instanceof ApiError && caught.isUnauthenticated) window.location.reload();
        });
    };
    document.addEventListener("visibilitychange", check);
    return () => document.removeEventListener("visibilitychange", check);
  }, [held]);

  // In place, not a reload: the greeting and the menu change with the
  // answer, and the page does not flash through its loading state.
  const updateUser = useCallback((user: CurrentUser["user"]) => {
    setState((previous) =>
      previous.status === "ready" ? { ...previous, me: { ...previous.me, user } } : previous,
    );
  }, []);

  const renameWorkspace = useCallback((name: string) => {
    setState((previous) => {
      if (previous.status !== "ready" || previous.workspace === null) return previous;
      const id = previous.workspace.id;
      const renamed = (w: WorkspaceMembership) => (w.id === id ? { ...w, name } : w);
      return {
        ...previous,
        workspace: renamed(previous.workspace),
        me: { ...previous.me, workspaces: previous.me.workspaces.map(renamed) },
      };
    });
  }, []);

  const value = useMemo(
    () => ({ state, retry, updateUser, renameWorkspace }),
    [state, retry, updateUser, renameWorkspace],
  );
  const inDemo = state.status === "ready" && state.workspace?.demo === true;
  return (
    <ShellContext.Provider value={value}>
      <InDemoContext.Provider value={inDemo}>{children}</InDemoContext.Provider>
    </ShellContext.Provider>
  );
}

function useShellContext(): ShellState {
  return useShellValue().state;
}

function useShellValue(): ShellContextValue {
  const value = useContext(ShellContext);
  if (value === null) {
    throw new Error("The shell hooks must be used inside <ShellProvider>");
  }
  return value;
}

/** The whole state, for the shell itself: it is the one that renders loading and failure. */
export function useShell(): ShellState {
  return useShellContext();
}

/** Start the session check again — what "Try again" does after a failure. */
export function useShellRetry(): () => void {
  return useShellValue().retry;
}

/** Replace the signed-in person with the API's newer answer. */
export function useUpdateCurrentUser(): (user: CurrentUser["user"]) => void {
  return useShellValue().updateUser;
}

/** Say the active workspace's new name, once the API has kept it. */
export function useRenameWorkspace(): (name: string) => void {
  return useShellValue().renameWorkspace;
}

/** The signed-in person, or null while the answer is still on its way. */
export function useCurrentUser(): CurrentUser["user"] | null {
  const state = useShellContext();
  return state.status === "ready" ? state.me.user : null;
}

/** The active workspace, or null: a brand-new account belongs to none yet. */
export function useCurrentWorkspace(): WorkspaceMembership | null {
  const state = useShellContext();
  return state.status === "ready" ? state.workspace : null;
}

/**
 * What the signed-in person may do in the active workspace.
 *
 * Used to hide what they may never open. It is NOT a security boundary:
 * hiding a link hides a link, and the API refuses the request either way.
 */
/** What this person may do — or null while the answer is still on its way.
 *
 * Null rather than an empty list, and the type is the whole point. An empty
 * list is a real answer meaning "may do nothing", and this used to return it
 * for "we have not asked yet" as well. The command palette believed it:
 * anyone quick enough to press Ctrl+K before /auth/me came back got a
 * palette with no navigation in it, where the arrow key wrapped around to
 * "create an intention" and Enter did that instead of going where they
 * asked. It cost nothing on a laptop and showed up as an intermittent CI
 * failure, which is how the two costs of this kind of bug usually split.
 *
 * Whoever adds the next consumer now has to say which of the two they mean,
 * because tsc will not let them past without it.
 */
export function usePermissions(): readonly string[] | null {
  const state = useShellContext();
  return state.status === "ready" ? state.permissions : null;
}

/** Every workspace this person may switch to. Empty until LEKA-331 wires the switch. */
export function useWorkspaces(): readonly WorkspaceMembership[] {
  const state = useShellContext();
  return state.status === "ready" ? state.me.workspaces : [];
}
