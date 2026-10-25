"use client";

import { ChevronDown, CreditCard, Globe, LogOut, Plug, Settings, ShieldCheck, User, Users } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

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
import { useMainNav } from "@/components/shell/main-nav";
import { useCurrentUser, usePermissions } from "@/components/shell/shell-provider";
import { language as languageOf } from "@/lib/i18n/languages";
import { routeById, routes } from "@/config/routes";
import { canOpen } from "@/lib/navigation/access";
import { useDictionary, useLanguage } from "@/lib/i18n/locale-provider";
import { auth, markSignedOut } from "@/lib/auth";

/** The pages of running the workspace (LEKA-494), each to who may open it. */
const MANAGEMENT = [
  { id: "sources", icon: Plug, href: routes.sources() },
  { id: "governance", icon: ShieldCheck, href: routes.governance() },
  { id: "team", icon: Users, href: routes.team() },
  { id: "billing", icon: CreditCard, href: routes.billing() },
] as const;

/**
 * The account, in the header: who you are, the pages of running the
 * workspace (LEKA-494), settings and the way out — and, on a phone, where
 * the header has no room for them, the main pages.
 *
 * The language lives here as well as in Settings because it is the one
 * preference someone changes before they can read the settings page. It
 * opens the picker of every language LEKA offers (components/language).
 */
export function UserMenu({ contract = false }: { contract?: boolean } = {}) {
  const t = useDictionary();
  const router = useRouter();
  const user = useCurrentUser();
  const permissions = usePermissions() ?? [];
  const main = useMainNav();
  const managed = MANAGEMENT.filter((page) => {
    const route = routeById(page.id);
    return route !== undefined && canOpen(route, permissions);
  });
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
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-start transition-colors outline-none hover:bg-brand-violet-soft/60 focus-visible:ring-3 focus-visible:ring-brand-violet/40"
        >
          <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-brand-violet text-xs font-semibold text-white">
            {initials}
          </span>
          {/* The name only where the header has room beside its pages. */}
          <span className="hidden truncate text-sm font-medium text-shell-nav capitalize sm:block xl:hidden 2xl:block">
            {name}
          </span>
          <ChevronDown className="size-4 shrink-0 text-shell-muted" aria-hidden="true" />
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
          {/* The header's pages, where it has no room for them. */}
          {main.length > 0 ? (
            <DropdownMenuGroup className="xl:hidden">
              <DropdownMenuSeparator />
              {main.map((entry) => (
                <DropdownMenuItem key={entry.id} onClick={() => router.push(entry.href)} data-testid={`menu-${entry.id}`}>
                  <span className="min-w-0 flex-1 truncate">{entry.label}</span>
                  {entry.count > 0 ? <span className="text-shell-muted">{entry.count}</span> : null}
                </DropdownMenuItem>
              ))}
            </DropdownMenuGroup>
          ) : null}
          {managed.length > 0 ? (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuGroup>
                {managed.map((page) => (
                  <DropdownMenuItem key={page.id} onClick={() => router.push(page.href)} data-testid={`menu-${page.id}`}>
                    <page.icon className="size-4" aria-hidden="true" />
                    {/* Under an Enterprise contract (2026-10-25): « Contrat », never a bill. */}
                    {page.id === "billing" && contract ? t.shell.contract : t.nav[page.id]}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuGroup>
            </>
          ) : null}
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
