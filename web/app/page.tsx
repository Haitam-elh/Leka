"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { auth, type CurrentUser } from "@/lib/auth";

type Status =
  | { kind: "checking" }
  | { kind: "signed-in"; me: CurrentUser }
  | { kind: "unreachable"; detail: string }
  | { kind: "failed"; detail: string };

/**
 * The page you land on after signing in.
 *
 * Deliberately thin — the application shell (sidebar, header, workspace
 * switcher) is LEKA-337. What this does is close the loop: an anonymous
 * visitor is sent to sign in, a signed-in one sees that they are, and a
 * broken API says so.
 *
 * Every branch renders something. An earlier version returned null when the
 * API was unreachable, which showed as a blank white page with no clue what
 * had happened.
 */
export default function Home() {
  const router = useRouter();
  const [status, setStatus] = useState<Status>({ kind: "checking" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        // redirectOn401: false — this page decides where to send an
        // anonymous visitor itself, rather than being bounced mid-render.
        const me = await auth.me({ redirectOn401: false });
        if (!cancelled) setStatus({ kind: "signed-in", me });
      } catch (caught) {
        if (cancelled) return;
        if (caught instanceof ApiError && caught.isUnauthenticated) {
          router.replace("/login");
          return;
        }
        if (caught instanceof ApiError && caught.isUnreachable) {
          setStatus({ kind: "unreachable", detail: caught.message });
          return;
        }
        setStatus({
          kind: "failed",
          detail: caught instanceof Error ? caught.message : "Unknown error",
        });
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [router]);

  if (status.kind === "checking") {
    return <Centred>Loading…</Centred>;
  }

  if (status.kind === "unreachable") {
    return (
      <Centred>
        <p className="font-medium text-destructive">The API is not responding.</p>
        <p className="mt-2 text-sm text-muted-foreground">{status.detail}</p>
        <pre className="mt-4 rounded bg-muted px-3 py-2 text-left text-xs">
          cd api{"\n"}source .venv/bin/activate{"\n"}uvicorn leka.main:app --reload
        </pre>
      </Centred>
    );
  }

  if (status.kind === "failed") {
    return (
      <Centred>
        <p className="font-medium text-destructive">Something went wrong.</p>
        <p className="mt-2 text-sm text-muted-foreground">{status.detail}</p>
      </Centred>
    );
  }

  const { me } = status;
  const active = me.workspaces.find(
    (workspace) => workspace.id === me.active_workspace_id,
  );

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 px-4">
      <div className="text-center">
        <h1 className="text-2xl font-semibold tracking-tight">LEKA</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Signed in as {me.user.email}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          {active
            ? `Workspace: ${active.name} (${active.role})`
            : me.workspaces.length > 0
              ? "No active workspace — choose one."
              : "No workspace yet."}
        </p>
      </div>

      <Button
        variant="outline"
        onClick={async () => {
          await auth.logout();
          router.push("/login");
        }}
      >
        Sign out
      </Button>
    </main>
  );
}

function Centred({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center px-4">
      <div className="max-w-md text-center text-sm text-muted-foreground">
        {children}
      </div>
    </main>
  );
}
