"use client";

import { ChevronDown, LogOut, Settings, User } from "lucide-react";
import { cn } from "cn";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useCurrentUser, useCurrentWorkspace } from "@/components/shell/shell-provider";
import { LOCALES, type Locale } from "@/lib/i18n/dictionaries";
import { useDictionary, useLocale } from "@/lib/i18n/locale-provider";
import { auth } from "@/lib/auth";

/**
 * The account, and the two things anyone looks for in it: settings and the
 * way out.
 *
 * The same component twice, because the mockups show the person in two
 * places: at the foot of the sidebar, with their role, and in the header
 * beside the notifications. One menu, two shapes, so the two cannot drift.
 *
 * The language lives here rather than in Settings because it is the one
 * preference someone changes before they can read the settings page.
 */
export function UserMenu({
  variant,
  collapsed = false,
}: {
  variant: "sidebar" | "header";
  /** On the rail there is room for the avatar and nothing else. */
  collapsed?: boolean;
}) {
  const t = useDictionary();
  const user = useCurrentUser();
  const workspace = useCurrentWorkspace();
  const { locale, setLocale } = useLocale();

  const email = user?.email ?? "";
  // No display name exists yet — the account is an e-mail address until
  // LEKA-330 grows profiles. The part before the @ is what a person
  // recognises, and the initial is what fits in a circle.
  const name = email.split("@")[0] || t.shell.account;
  const initials = name.slice(0, 1).toUpperCase() || "?";

  async function signOut() {
    try {
      await auth.logout();
    } catch {
      // The call can fail for reasons that have nothing to do with the
      // session — the API restarting, a dropped connection. Someone who
      // asked to leave must not be left sitting inside the application
      // because of it, so the navigation below is not conditional on the
      // answer. If the session outlived the attempt they land on the form
      // and sign in again, which is honest; before LEKA-337 they stayed on
      // the page with no sign that anything had happened.
    }
    // A full page load rather than router.push. Two reasons, one of them
    // not about tests: the App Router keeps rendered pages in a client
    // cache, and a soft navigation leaves the screens of the session we
    // just ended sitting in it, one Back away from being painted again.
    // This drops the whole tab. It also lands on exactly /login instead of
    // racing the /login?next= redirect lib/api.ts fires when a call 401s.
    window.location.assign("/login");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={t.shell.account}
        data-testid="user-menu"
        className={cn(
          "flex items-center gap-2 rounded-lg text-left transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
          variant === "sidebar"
            ? "w-full px-2 py-2 hover:bg-brand-violet-soft/60"
            : "px-2 py-1.5 hover:bg-brand-violet-soft/60",
          collapsed && "justify-center px-0",
        )}
      >
        <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-brand-violet/10 text-xs font-semibold text-brand-violet">
          {initials}
        </span>
        {collapsed ? null : variant === "sidebar" ? (
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-shell-nav capitalize">
              {name}
            </span>
            <span className="block truncate text-xs text-shell-muted">
              {workspace?.role ?? ""}
            </span>
          </span>
        ) : (
          <>
            <span className="hidden truncate text-sm font-medium text-shell-nav capitalize sm:block">
              {name}
            </span>
            <ChevronDown className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
          </>
        )}
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-60">
        {/* Every label belongs to a group: base-ui reads its context, and a
            label on its own throws when the menu opens — which a build never
            sees, and a test does. */}
        <DropdownMenuGroup>
          <DropdownMenuLabel className="truncate font-normal text-shell-muted">
            {email}
          </DropdownMenuLabel>
          <DropdownMenuItem>
            <User className="size-4" aria-hidden="true" />
            {t.shell.profile}
          </DropdownMenuItem>
          <DropdownMenuItem>
            <Settings className="size-4" aria-hidden="true" />
            {t.nav.settings}
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuRadioGroup
          value={locale}
          onValueChange={(next: string) => setLocale(next as Locale)}
        >
          <DropdownMenuLabel className="text-shell-muted">{t.shell.language}</DropdownMenuLabel>
          {LOCALES.map((candidate) => (
            <DropdownMenuRadioItem key={candidate} value={candidate}>
              {t.languages[candidate]}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={signOut} data-testid="sign-out">
            <LogOut className="size-4" aria-hidden="true" />
            {t.shell.signOut}
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
