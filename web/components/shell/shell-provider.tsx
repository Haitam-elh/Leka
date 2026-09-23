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
import { createContext, useContext, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import { auth, type CurrentUser, type WorkspaceMembership } from "@/lib/auth";
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
  /** The API is down. Not the same as signed out, and not the same advice. */
  | { status: "unreachable"; detail: string }
  | { status: "failed"; detail: string };

const ShellContext = createContext<ShellState | null>(null);

export function ShellProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [state, setState] = useState<ShellState>({ status: "loading" });

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
        if (caught instanceof ApiError && caught.isUnreachable) {
          setState({ status: "unreachable", detail: caught.message });
          return;
        }
        setState({
          status: "failed",
          detail: caught instanceof Error ? caught.message : "Unknown error",
        });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return <ShellContext.Provider value={state}>{children}</ShellContext.Provider>;
}

function useShellContext(): ShellState {
  const state = useContext(ShellContext);
  if (state === null) {
    throw new Error("The shell hooks must be used inside <ShellProvider>");
  }
  return state;
}

/** The whole state, for the shell itself: it is the one that renders loading and failure. */
export function useShell(): ShellState {
  return useShellContext();
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
