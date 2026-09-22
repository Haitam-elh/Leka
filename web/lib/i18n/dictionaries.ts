/**
 * Every word the shell puts on screen, in each language it speaks.
 *
 * English is what the product ships in; the mockups are in French, so French
 * exists from the first day rather than being retrofitted once fifty strings
 * are hard-coded in components.
 *
 * A LANGUAGE CANNOT FALL BEHIND. `fr` is typed as `Dictionary`, so a key
 * added to `en` and forgotten here fails `npm run typecheck` — which is the
 * only reason a second language is worth having in the code rather than in a
 * spreadsheet.
 *
 * This is deliberately not a library. What the shell needs is a lookup and a
 * setting; what a library adds — plurals, dates, currencies, locale-prefixed
 * routes — is worth its weight the day a screen formats a number or a date,
 * and next-intl drops in behind this same hook when that day comes.
 */

export const LOCALES = ["en", "fr"] as const;

export type Locale = (typeof LOCALES)[number];

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

const en = {
  /** One entry per line in config/navigation.ts. LEKA-338 owns the wording. */
  nav: {
    overview: "Overview",
    newIntention: "New intention",
    intentions: "Intentions",
    environment: "My environment",
    activity: "Activity",
    approvals: "To approve",
    capabilities: "Capabilities",
    sources: "Sources",
    security: "Security & governance",
    team: "Team & access",
    billing: "Billing",
    settings: "Settings",
  },
  shell: {
    tagline: "Understand. Decide. Act.",
    mainNavigation: "Main navigation",
    skipToContent: "Skip to content",
    searchPlaceholder: "Search an application, a service, a document…",
    notifications: "Notifications",
    openNavigation: "Open the navigation",
    closeNavigation: "Close the navigation",
    collapseSidebar: "Collapse the sidebar",
    expandSidebar: "Expand the sidebar",
    workspace: "Workspace",
    switchWorkspace: "Switch workspace",
    noWorkspace: "No workspace yet",
    account: "Your account",
    profile: "Profile",
    signOut: "Sign out",
    language: "Language",
    loading: "Loading…",
    unreachableTitle: "The API is not responding.",
    emptyPage: "Nothing here yet.",
  },
  languages: {
    en: "English",
    fr: "Français",
  },
};

export type Dictionary = typeof en;

/** The keys `config/navigation.ts` is allowed to point at. */
export type NavKey = keyof Dictionary["nav"];

const fr: Dictionary = {
  nav: {
    overview: "Vue d'ensemble",
    newIntention: "Nouvelle intention",
    intentions: "Intentions",
    environment: "Mon environnement",
    activity: "Activité",
    approvals: "À valider",
    capabilities: "Capacités",
    sources: "Sources",
    security: "Sécurité & gouvernance",
    team: "Équipe & accès",
    billing: "Facturation",
    settings: "Paramètres",
  },
  shell: {
    tagline: "Understand. Decide. Act.",
    mainNavigation: "Navigation principale",
    skipToContent: "Aller au contenu",
    searchPlaceholder: "Rechercher une application, un service, un document…",
    notifications: "Notifications",
    openNavigation: "Ouvrir la navigation",
    closeNavigation: "Fermer la navigation",
    collapseSidebar: "Replier la barre latérale",
    expandSidebar: "Déplier la barre latérale",
    workspace: "Workspace",
    switchWorkspace: "Changer de workspace",
    noWorkspace: "Aucun workspace",
    account: "Votre compte",
    profile: "Profil",
    signOut: "Se déconnecter",
    language: "Langue",
    loading: "Chargement…",
    unreachableTitle: "L'API ne répond pas.",
    emptyPage: "Rien ici pour l'instant.",
  },
  languages: {
    en: "English",
    fr: "Français",
  },
};

export const DICTIONARIES: Record<Locale, Dictionary> = { en, fr };
