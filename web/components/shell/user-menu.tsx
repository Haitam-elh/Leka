"use client";

import { ChevronDown, Globe, LogOut, Settings, User } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { cn } from "cn";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useChooseLanguage } from "@/components/language/account-language";
import { LanguageDialog } from "@/components/language/language-picker";
import { ProfileDialog } from "@/components/shell/profile-dialog";
import { useCurrentUser, useCurrentWorkspace } from "@/components/shell/shell-provider";
import { language as languageOf } from "@/lib/i18n/languages";
import { routes } from "@/config/routes";
import { useDictionary, useLanguage } from "@/lib/i18n/locale-provider";
import { auth, markSignedOut } from "@/lib/auth";

/**
 * The account, and the two things anyone looks for in it: settings and the
 * way out.
 *
 * The same component twice, because the mockups show the person in two
 * places: at the foot of the sidebar, with their role, and in the header
 * beside the notifications. One menu, two shapes, so the two cannot drift.
 *
 * The language lives here as well as in Settings because it is the one
 * preference someone changes before they can read the settings page. It
 * opens the picker of every language LEKA offers (components/language).
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
  const router = useRouter();
  const user = useCurrentUser();
  const workspace = useCurrentWorkspace();
  const { language } = useLanguage();
  const choose = useChooseLanguage();
  const [profileOpen, setProfileOpen] = useState(false);
  const [languageOpen, setLanguageOpen] = useState(false);
  const current = languageOf(language);

  const email = user?.email ?? "";
  // The name given at registration. An account made before registration
  // asked has none: the part before the @ is what a person recognises.
  const given = [user?.first_name, user?.last_name].filter(Boolean).join(" ");
  const name = given || email.split("@")[0] || t.shell.account;
  const initials =
    [user?.first_name, user?.last_name]
      .map((part) => part?.trim().slice(0, 1).toUpperCase() ?? "")
      .join("") ||
    name.slice(0, 1).toUpperCase() ||
    "?";

  async function signOut() {
    try {
      await auth.logout();
    } catch {
      // The call can fail for reasons that have nothing to do with the
      // session — the API restarting, a dropped connection. Someone who
      // asked to leave must not be left sitting inside the application
      // because of it, so the navigation below is not conditional on the
      // answer. If the session outlived the attempt, the site's "Se
      // connecter" shows them the form rather than letting them straight
      // back in (markSignedOut); before LEKA-337 they stayed on the page
      // with no sign that anything had happened.
    }
    // A full page load rather than router.push. Two reasons, one of them
    // not about tests: the App Router keeps rendered pages in a client
    // cache, and a soft navigation leaves the screens of the session we
    // just ended sitting in it, one Back away from being painted again.
    // This drops the whole tab.
    //
    // To leka-core.com's home page, the site: that is where people come
    // from, and where "Se connecter" takes them back in.
    markSignedOut();
    window.location.assign("/");
  }

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          aria-label={t.shell.account}
          data-testid="user-menu"
          className={cn(
            "flex items-center gap-2 rounded-lg text-start transition-colors outline-none focus-visible:ring-3 focus-visible:ring-brand-violet/40",
            variant === "sidebar"
              ? "w-full gap-4 px-3 py-2 hover:bg-brand-violet-soft/60"
              : "px-2 py-1.5 hover:bg-brand-violet-soft/60",
            collapsed && "justify-center px-0",
          )}
        >
          <span
            className={cn(
              "flex shrink-0 items-center justify-center rounded-full font-semibold",
              // The mockup's foot of the sidebar: a navy disc, white initial.
              variant === "sidebar"
                ? "size-[38px] bg-brand-navy text-sm text-white"
                : "size-9 bg-brand-violet text-xs text-white",
            )}
          >
            {initials}
          </span>
          {collapsed ? null : variant === "sidebar" ? (
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-medium text-shell-nav capitalize">
                {name}
              </span>
              <span className="block truncate text-xs text-shell-muted">
                {workspace ? roleLabel(t, workspace.role) : ""}
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
            <DropdownMenuItem onClick={() => setProfileOpen(true)} data-testid="profile">
              <User className="size-4" aria-hidden="true" />
              {t.shell.profile}
            </DropdownMenuItem>
            {/* It went nowhere: an item with nothing to do (2026-10-14). */}
            <DropdownMenuItem onClick={() => router.push(routes.settings())} data-testid="settings">
              <Settings className="size-4" aria-hidden="true" />
              {t.nav.settings}
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onClick={() => setLanguageOpen(true)} data-testid="language">
              <Globe className="size-4" aria-hidden="true" />
              <span className="min-w-0 flex-1 truncate">{t.shell.language}</span>
              <span lang={current?.tag} dir={current?.dir} className="truncate text-shell-muted">
                {current?.native ?? language}
              </span>
            </DropdownMenuItem>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuGroup>
            <DropdownMenuItem onClick={signOut} data-testid="sign-out">
              <LogOut className="size-4" aria-hidden="true" />
              {t.shell.signOut}
            </DropdownMenuItem>
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
      {/* Outside the menu: it closes as the dialog opens, and would take a
          dialog rendered inside it along. */}
      <ProfileDialog open={profileOpen} onOpenChange={setProfileOpen} />
      <LanguageDialog
        open={languageOpen}
        onOpenChange={setLanguageOpen}
        onChoose={(chosen) => void choose(chosen)}
      />
    </>
  );
}

/** The API's role name, in the interface's language — never the raw word. */
function roleLabel(t: ReturnType<typeof useDictionary>, role: string): string {
  const roles: Record<string, string> = t.shell.roles;
  return roles[role] ?? role;
}
