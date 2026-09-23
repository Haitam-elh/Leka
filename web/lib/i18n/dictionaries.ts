/**
 * Every word the interface puts on screen, in each language it speaks.
 *
 * FRENCH IS THE DEFAULT. The product is sold in French and the mockups are in
 * French; English exists beside it so that adding a market later is a
 * translation rather than a refactor of fifty components.
 *
 * A LANGUAGE CANNOT FALL BEHIND. `en` is typed as `Dictionary`, so a key
 * added here and forgotten there fails `npm run typecheck`. A navigation
 * label with no translation fails `config/routes.test.ts`.
 *
 * Deliberately not a library. next-intl drops in behind `useDictionary()` the
 * day a screen needs plurals, dates or locale-prefixed URLs.
 */

export const LOCALES = ["fr", "en"] as const;

export type Locale = (typeof LOCALES)[number];

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (LOCALES as readonly string[]).includes(value);
}

const fr = {
  /** One key per route in config/routes.ts. */
  nav: {
    overview: "Vue d'ensemble",
    newIntention: "Nouvelle intention",
    intentions: "Intentions",
    intentionDetail: "Intention",
    approvals: "À valider",
    approvalDetail: "Élément à valider",
    activity: "Activité",
    environment: "Mon environnement",
    entityDetail: "Entité",
    sources: "Sources",
    sourceDetail: "Source",
    capabilities: "Capacités",
    capabilityDetail: "Capacité",
    governance: "Sécurité & gouvernance",
    team: "Équipe & accès",
    billing: "Facturation",
    settings: "Paramètres",
  },
  /** The blocks of the sidebar. The first entry stands alone, above them. */
  groups: {
    work: "Travail",
    knowledge: "Connaissance",
    admin: "Administration",
  },
  shell: {
    tagline: "Understand. Decide. Act.",
    mainNavigation: "Navigation principale",
    breadcrumb: "Fil d'Ariane",
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
    notFoundTitle: "Page introuvable",
    emptyPage: "Rien ici pour l'instant.",
    soon: "Bientôt",
    planGated: "Inclus dans une offre supérieure",
    /** Appended to the entry's label: "À valider, 3 éléments en attente". */
    pendingApprovals: "{count} éléments en attente",
  },
  /** The tabs of a detail page. Their ids are URL segments — see config/routes.ts. */
  tabs: {
    overview: "Vue d'ensemble",
    analysis: "Analyse",
    evidence: "Preuves",
    actions: "Actions",
    history: "Historique",
    metrics: "Métriques",
    dependencies: "Dépendances",
    incidents: "Incidents",
    deployments: "Déploiements",
    logs: "Logs",
    configuration: "Configuration",
    documentation: "Documentation",
  },
  /** What a page says when it has nothing to show, or refuses to show it. */
  states: {
    emptyTitle: "Rien à afficher pour l'instant",
    emptyBody: "Cet espace se remplira dès que LEKA aura de quoi vous montrer.",
    unavailableTitle: "Cette page arrive bientôt",
    unavailableBody:
      "Cette partie de LEKA est en cours de construction. Elle apparaîtra ici dès qu'elle sera prête.",
    planGatedBody:
      "Cette partie de LEKA est incluse dans une offre supérieure à la vôtre.",
    seeBilling: "Voir les offres",
    forbiddenTitle: "Vous n'avez pas accès à cette page",
    forbiddenBody:
      "Votre rôle dans ce workspace ne permet pas d'ouvrir cette page. Un administrateur peut vous l'accorder.",
    requestAccess: "Demander l'accès",
    notFoundBody: "Cette adresse ne correspond à aucune page de LEKA.",
    backToOverview: "Retour à la vue d'ensemble",
    goBack: "Revenir en arrière",
  },
  /** The command palette: find and go, never answer. */
  palette: {
    open: "Ouvrir la recherche",
    placeholder: "Rechercher, ou décrire une intention…",
    actions: "Actions",
    navigation: "Navigation",
    results: "Résultats",
    createIntention: "Créer une intention",
    createIntentionWith: "Créer une intention : « {query} »",
    noResults: "Aucun résultat.",
    searchHint: "LEKA répond aux questions dans une intention, pas ici.",
    close: "Fermer",
  },
  /**
   * What a form says, whatever the form is for.
   *
   * Optional is marked rather than required: on a screen where most fields
   * must be filled, an asterisk on each of them is noise, and the one that
   * matters is the exception.
   */
  forms: {
    optional: "(optionnel)",
    charCount: "{count} / {max}",
    save: "Enregistrer",
    saving: "Enregistrement…",
    cancel: "Annuler",
    discard: "Annuler les modifications",
    /** Only shown past three errors, so the plural is always right. */
    errorSummaryTitle: "{count} champs demandent une correction",
    submitFailed: "Impossible d'enregistrer. Vérifiez votre connexion puis réessayez.",
    unsavedTitle: "Quitter sans enregistrer ?",
    unsavedBody: "Les modifications de ce formulaire seront perdues.",
    unsavedLeave: "Quitter sans enregistrer",
    unsavedStay: "Continuer l'édition",
    selectPlaceholder: "Sélectionner…",
    searchPlaceholder: "Rechercher…",
    loading: "Chargement…",
    noResults: "Aucun résultat.",
    loadFailed: "Le chargement a échoué. Réessayez.",
    retry: "Réessayer",
    clear: "Effacer",
    remove: "Retirer {label}",
    selectAll: "Tout sélectionner",
    clearSelection: "Tout désélectionner",
    maxReached: "{max} au maximum",
    selectedCount: "{count} sélectionné(s)",
    pickDate: "Choisir une date",
    dateFrom: "Du",
    dateTo: "Au",
    period24h: "Dernières 24 heures",
    period7d: "Derniers 7 jours",
    period30d: "Derniers 30 jours",
    periodCustom: "Personnalisé…",
  },
  /**
   * Validation messages.
   *
   * A component never writes one. The zod error map in lib/validation emits
   * a key and its numbers, and the field resolves it here — which is what
   * makes the same rule read the same way on every screen, in both
   * languages.
   */
  validation: {
    required: "Ce champ est obligatoire.",
    tooShortString: "Au moins {min} caractères.",
    tooLongString: "{max} caractères au maximum.",
    tooFewItems: "Choisissez au moins {min} éléments.",
    tooManyItems: "{max} éléments au maximum.",
    tooSmallNumber: "La valeur minimale est {min}.",
    tooBigNumber: "La valeur maximale est {max}.",
    email: "Indiquez une adresse e-mail valide.",
    url: "Indiquez une adresse web valide.",
    invalidFormat: "Ce format n'est pas reconnu.",
    invalid: "Cette valeur n'est pas valide.",
  },
  /** Confirming, cancelling, and acting on a selection. */
  interactions: {
    cancel: "Annuler",
    confirm: "Confirmer",
    typeToConfirm: "Pour confirmer, saisissez {name}",
    impactTitle: "Ce que cela change",
    selectionCount: "{count} action(s) sélectionnée(s)",
    clearSelection: "Tout désélectionner",
    dismiss: "Fermer",
  },
  languages: {
    fr: "Français",
    en: "English",
  },
};

export type Dictionary = typeof fr;

/** The keys config/routes.ts is allowed to point at. */
export type NavKey = keyof Dictionary["nav"];

/** And the group titles it may use. */
export type GroupKey = keyof Dictionary["groups"];

/** The tab segments config/routes.ts may declare. */
export type TabKey = keyof Dictionary["tabs"];

const en: Dictionary = {
  nav: {
    overview: "Overview",
    newIntention: "New intention",
    intentions: "Intentions",
    intentionDetail: "Intention",
    approvals: "To approve",
    approvalDetail: "Item to approve",
    activity: "Activity",
    environment: "My environment",
    entityDetail: "Entity",
    sources: "Sources",
    sourceDetail: "Source",
    capabilities: "Capabilities",
    capabilityDetail: "Capability",
    governance: "Security & governance",
    team: "Team & access",
    billing: "Billing",
    settings: "Settings",
  },
  groups: {
    work: "Work",
    knowledge: "Knowledge",
    admin: "Administration",
  },
  shell: {
    tagline: "Understand. Decide. Act.",
    mainNavigation: "Main navigation",
    breadcrumb: "Breadcrumb",
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
    notFoundTitle: "Page not found",
    emptyPage: "Nothing here yet.",
    soon: "Soon",
    planGated: "Included in a higher plan",
    pendingApprovals: "{count} items waiting",
  },
  tabs: {
    overview: "Overview",
    analysis: "Analysis",
    evidence: "Evidence",
    actions: "Actions",
    history: "History",
    metrics: "Metrics",
    dependencies: "Dependencies",
    incidents: "Incidents",
    deployments: "Deployments",
    logs: "Logs",
    configuration: "Configuration",
    documentation: "Documentation",
  },
  states: {
    emptyTitle: "Nothing to show yet",
    emptyBody: "This space fills up as soon as LEKA has something to show you.",
    unavailableTitle: "This page is on its way",
    unavailableBody:
      "This part of LEKA is being built. It will appear here as soon as it is ready.",
    planGatedBody: "This part of LEKA is included in a plan above yours.",
    seeBilling: "See the plans",
    forbiddenTitle: "You do not have access to this page",
    forbiddenBody:
      "Your role in this workspace does not open this page. An administrator can grant it.",
    requestAccess: "Request access",
    notFoundBody: "This address matches no page in LEKA.",
    backToOverview: "Back to the overview",
    goBack: "Go back",
  },
  palette: {
    open: "Open search",
    placeholder: "Search, or describe an intention…",
    actions: "Actions",
    navigation: "Navigation",
    results: "Results",
    createIntention: "Create an intention",
    createIntentionWith: 'Create an intention: "{query}"',
    noResults: "No results.",
    searchHint: "LEKA answers questions inside an intention, not here.",
    close: "Close",
  },
  forms: {
    optional: "(optional)",
    charCount: "{count} / {max}",
    save: "Save",
    saving: "Saving…",
    cancel: "Cancel",
    discard: "Discard changes",
    errorSummaryTitle: "{count} fields need correcting",
    submitFailed: "Could not save. Check your connection and try again.",
    unsavedTitle: "Leave without saving?",
    unsavedBody: "The changes in this form will be lost.",
    unsavedLeave: "Leave without saving",
    unsavedStay: "Keep editing",
    selectPlaceholder: "Select…",
    searchPlaceholder: "Search…",
    loading: "Loading…",
    noResults: "No results.",
    loadFailed: "Loading failed. Try again.",
    retry: "Try again",
    clear: "Clear",
    remove: "Remove {label}",
    selectAll: "Select all",
    clearSelection: "Clear selection",
    maxReached: "{max} at most",
    selectedCount: "{count} selected",
    pickDate: "Pick a date",
    dateFrom: "From",
    dateTo: "To",
    period24h: "Last 24 hours",
    period7d: "Last 7 days",
    period30d: "Last 30 days",
    periodCustom: "Custom…",
  },
  validation: {
    required: "This field is required.",
    tooShortString: "At least {min} characters.",
    tooLongString: "{max} characters at most.",
    tooFewItems: "Choose at least {min} items.",
    tooManyItems: "{max} items at most.",
    tooSmallNumber: "The minimum is {min}.",
    tooBigNumber: "The maximum is {max}.",
    email: "Enter a valid email address.",
    url: "Enter a valid web address.",
    invalidFormat: "That format is not recognised.",
    invalid: "That value is not valid.",
  },
  interactions: {
    cancel: "Cancel",
    confirm: "Confirm",
    typeToConfirm: "To confirm, type {name}",
    impactTitle: "What this changes",
    selectionCount: "{count} action(s) selected",
    clearSelection: "Clear selection",
    dismiss: "Dismiss",
  },
  languages: {
    fr: "Français",
    en: "English",
  },
};

export const DICTIONARIES: Record<Locale, Dictionary> = { fr, en };

/** Replaces `{name}` placeholders. The whole templating this product needs. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) =>
    key in values ? String(values[key]) : whole,
  );
}
