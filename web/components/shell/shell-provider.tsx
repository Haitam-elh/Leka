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

export type ShellState =
  | { status: "loading" }
  | { status: "ready"; me: CurrentUser; workspace: WorkspaceMembership | null }
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
        if (cancelled) return;
        setState({
          status: "ready",
          me,
          workspace:
            me.workspaces.find((workspace) => workspace.id === me.active_workspace_id) ?? null,
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

/** Every workspace this person may switch to. Empty until LEKA-331 wires the switch. */
export function useWorkspaces(): readonly WorkspaceMembership[] {
  const state = useShellContext();
  return state.status === "ready" ? state.me.workspaces : [];
}
