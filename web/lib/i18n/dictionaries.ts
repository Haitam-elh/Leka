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
    sidebar: "Barre latérale",
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
    // Loading, failure and connectivity (LEKA-343). Each failure says what
    // happened AND what to do; none of them repeats an error's own message.
    loading: "Chargement…",
    retry: "Réessayer",
    reference: "Référence : {id}",
    errorTitle: "Cette page n'a pas pu s'afficher",
    errorBody:
      "Réessayez. Si le problème continue, revenez à la vue d'ensemble et prévenez votre administrateur.",
    serverTitle: "Une erreur est survenue de notre côté",
    serverBody:
      "Vous n'y êtes pour rien. Réessayez dans quelques instants ; si cela persiste, transmettez la référence ci-dessous à votre administrateur.",
    unreachableTitle: "LEKA ne répond pas",
    unreachableBody:
      "Le service est momentanément injoignable. Rien n'est perdu : réessayez dans quelques instants.",
    offlineTitle: "Vous êtes hors ligne",
    offlineBody:
      "Vérifiez votre connexion. La page se rechargera d'elle-même dès qu'elle sera revenue.",
    offlineBanner:
      "Vous êtes hors ligne. Ce qui est affiché peut ne plus être à jour, et rien ne sera enregistré avant le retour de la connexion.",
    backOnline: "Connexion rétablie.",
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
    selectionRegion: "Actions sur la sélection",
    selectionCount: "{count} action(s) sélectionnée(s)",
    clearSelection: "Tout désélectionner",
    dismiss: "Fermer",
  },
  /** The intention composer: the one box the whole product is about. */
  composer: {
    label: "Votre intention",
    placeholder: "Pourquoi l'API de paiement est-elle plus lente depuis hier ?",
    compactTitle: "Que voulez-vous accomplir aujourd'hui ?",
    submit: "Lancer l'analyse",
    submitHint: "⌘↵ pour lancer",
    sidePanel: "Contexte et périmètre",
    tooShortHint: "Encore {count} caractère(s) pour pouvoir lancer",
    attach: "Joindre un fichier",
    dictate: "Dictée",
    soon: "Bientôt",
    suggestions: "Suggestions",
    suggestIncident: "Analyser un incident",
    suggestIncidentTemplate: "Pourquoi {} est-il plus lent depuis hier ?",
    suggestChange: "Comprendre un changement",
    suggestChangeTemplate: "Qu'est-ce qui a changé sur {} cette semaine ?",
    suggestRisk: "Évaluer un risque",
    suggestRiskTemplate: "Quel est le risque à déployer {} en production ?",
    replaceTitle: "Remplacer ce que vous avez écrit ?",
    replaceBody: "Le texte en cours sera remplacé par le modèle choisi.",
    replaceConfirm: "Remplacer le texte",
    abandonTitle: "Abandonner cette intention ?",
    abandonBody: "Le texte saisi sera perdu.",
    abandonConfirm: "Abandonner",
    fileTooBig: "{name} dépasse {max} Mo.",
    fileTypeRefused: "{name} n'est pas d'un type accepté.",
    removeFile: "Retirer {name}",
    contextTitle: "Contexte qui sera analysé",
    whySources: "Pourquoi ces sources ?",
    whySourcesBody:
      "LEKA ne lit que les sources cochées. Moins de sources, c'est une analyse plus rapide et moins de contexte inutile.",
    scopeTitle: "Périmètre de l'analyse",
    environment: "Environnement",
    period: "Période",
    services: "Services",
    edit: "Modifier",
  },
  /** The workspace settings form, and the decision step's actions. */
  settings: {
    generalTitle: "Général du workspace",
    name: "Nom du workspace",
    slug: "Identifiant",
    slugHint: "Minuscules, chiffres et tirets. Il apparaît dans les URL.",
    timezone: "Fuseau horaire",
    defaultEnvironment: "Environnement par défaut",
    defaultPeriod: "Période d'analyse par défaut",
    saved: "Modifications enregistrées",
    savedBody: "Votre workspace a été mis à jour.",
    simulateError: "Simuler une erreur serveur",
  },
  decision: {
    title: "Recommandations",
    approve: "Valider et passer à l'action",
    approveTitle: "Appliquer les actions sélectionnées ?",
    approveBody: "LEKA appliquera ces changements sur votre infrastructure.",
    reject: "Refuser la sélection",
    rejectTitle: "Refuser la sélection ?",
    rejectBody: "Ces recommandations ne seront pas appliquées.",
    rejectReason: "Raison du refus",
    approved: "Actions envoyées",
    rejected: "Sélection refusée",
  },
  /**
   * The screens before signing in (LEKA-330), in the product's language
   * since LEKA-343. The errors say what to do next; none repeats the API's
   * own message, which is English and written for whoever debugs.
   */
  auth: {
    email: "Adresse e-mail",
    password: "Mot de passe",
    newPassword: "Nouveau mot de passe",
    signIn: "Se connecter",
    signingIn: "Connexion…",
    signInTitle: "Connexion",
    signInDescription: "Accédez à votre workspace.",
    noAccount: "Pas encore de compte ?",
    createOne: "En créer un",
    forgot: "Mot de passe oublié ?",
    resendConfirmation: "Renvoyer le lien de confirmation",
    confirmationResent: "Si cette adresse doit être confirmée, un nouveau lien est en route.",
    registerTitle: "Créer un compte",
    registerDescription: "Commencez à cartographier votre environnement.",
    alreadyHaveOne: "Déjà un compte ?",
    createAccount: "Créer le compte",
    creating: "Création…",
    passwordRule:
      "Au moins {min} caractères. Une phrase facile à retenir vaut mieux qu'un mot court et compliqué.",
    passwordRuleShort: "Au moins {min} caractères.",
    checkInbox: "Consultez votre boîte de réception",
    registerSent: "Si cette adresse peut être inscrite, un lien de confirmation est en route.",
    registerLinkLife: "Le lien est valable 24 heures, une seule fois.",
    backToSignIn: "Retour à la connexion",
    forgotTitle: "Réinitialiser votre mot de passe",
    forgotDescription: "Nous vous enverrons un lien par e-mail.",
    sendResetLink: "Envoyer le lien",
    sending: "Envoi…",
    resetSent: "Si un compte existe pour cette adresse, un lien de réinitialisation est en route.",
    resetLinkLife: "Le lien est valable une heure, une seule fois.",
    linkIncompleteTitle: "Lien incomplet",
    linkIncompleteDescription: "Cette page a besoin du lien reçu par e-mail.",
    linkIncompleteBody:
      "Ouvrez le lien exactement tel qu'il apparaît dans le message : certaines messageries coupent les liens longs en deux.",
    askNewLink: "Demander un nouveau lien",
    resetTitle: "Choisir un nouveau mot de passe",
    resetDescription: "Tous vos autres appareils connectés seront déconnectés.",
    setNewPassword: "Enregistrer le mot de passe",
    saving: "Enregistrement…",
    verifyingTitle: "Confirmation de votre adresse…",
    verifyingBody: "Cela prend un instant.",
    verifiedTitle: "Adresse confirmée",
    verifiedDescription: "Votre compte est prêt.",
    verifiedBody: "Vous pourrez fermer cet onglet une fois connecté.",
    verifyInvalidTitle: "Ce lien n'est plus valable",
    verifyInvalidDescription: "Les liens de confirmation durent 24 heures et ne servent qu'une fois.",
    verifyInvalidBody:
      "Connectez-vous avec votre adresse et votre mot de passe : nous vous proposerons d'envoyer un nouveau lien.",
    verifyFailedTitle: "Impossible de confirmer pour le moment",
    errors: {
      invalidCredentials: "Adresse e-mail ou mot de passe incorrect.",
      accountUnverified:
        "Confirmez votre adresse e-mail avant de vous connecter. Consultez votre boîte de réception : nous pouvons renvoyer un lien.",
      rateLimited: "Trop de tentatives. Patientez quelques minutes avant de réessayer.",
      tokenInvalid: "Ce lien n'est plus valable. Demandez-en un nouveau.",
      passwordTooShort: "Ce mot de passe est trop court : au moins {min} caractères.",
      passwordBreached:
        "Ce mot de passe figure dans une fuite de données connue. Choisissez-en un que vous n'utilisez nulle part ailleurs.",
      sessionExpired:
        "Votre session a expiré pendant que cette page était ouverte. Rechargez-la puis réessayez.",
      invalid: "Vérifiez les informations saisies puis réessayez.",
      offline: "Vous êtes hors ligne. Vérifiez votre connexion puis réessayez.",
      unreachable: "LEKA ne répond pas pour le moment. Réessayez dans quelques instants.",
      server: "Une erreur est survenue de notre côté. Réessayez dans quelques instants.",
      unknown: "La demande n'a pas abouti. Réessayez.",
    },
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
    sidebar: "Sidebar",
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
    loading: "Loading…",
    retry: "Try again",
    reference: "Reference: {id}",
    errorTitle: "This page could not be displayed",
    errorBody:
      "Try again. If it keeps happening, go back to the overview and let your administrator know.",
    serverTitle: "Something went wrong on our side",
    serverBody:
      "Nothing you did caused this. Try again in a moment; if it persists, pass the reference below to your administrator.",
    unreachableTitle: "LEKA is not responding",
    unreachableBody:
      "The service cannot be reached right now. Nothing is lost: try again in a moment.",
    offlineTitle: "You are offline",
    offlineBody: "Check your connection. The page will reload on its own once it is back.",
    offlineBanner:
      "You are offline. What you see may be out of date, and nothing will be saved until the connection is back.",
    backOnline: "Connection restored.",
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
    selectionRegion: "Actions on the selection",
    selectionCount: "{count} action(s) selected",
    clearSelection: "Clear selection",
    dismiss: "Dismiss",
  },
  composer: {
    label: "Your intention",
    placeholder: "Why has the payment API been slower since yesterday?",
    compactTitle: "What would you like to do today?",
    submit: "Start the analysis",
    submitHint: "⌘↵ to start",
    sidePanel: "Context and scope",
    tooShortHint: "{count} more character(s) before you can start",
    attach: "Attach a file",
    dictate: "Dictation",
    soon: "Soon",
    suggestions: "Suggestions",
    suggestIncident: "Look into an incident",
    suggestIncidentTemplate: "Why has {} been slower since yesterday?",
    suggestChange: "Understand a change",
    suggestChangeTemplate: "What changed on {} this week?",
    suggestRisk: "Weigh a risk",
    suggestRiskTemplate: "What is the risk of shipping {} to production?",
    replaceTitle: "Replace what you have written?",
    replaceBody: "The current text will be replaced by the template.",
    replaceConfirm: "Replace the text",
    abandonTitle: "Abandon this intention?",
    abandonBody: "The text you typed will be lost.",
    abandonConfirm: "Abandon",
    fileTooBig: "{name} is larger than {max} MB.",
    fileTypeRefused: "{name} is not an accepted file type.",
    removeFile: "Remove {name}",
    contextTitle: "Context that will be analysed",
    whySources: "Why these sources?",
    whySourcesBody:
      "LEKA only reads the sources you tick. Fewer sources means a faster analysis and less irrelevant context.",
    scopeTitle: "Scope of the analysis",
    environment: "Environment",
    period: "Period",
    services: "Services",
    edit: "Edit",
  },
  settings: {
    generalTitle: "Workspace general",
    name: "Workspace name",
    slug: "Identifier",
    slugHint: "Lowercase, digits and dashes. It appears in URLs.",
    timezone: "Time zone",
    defaultEnvironment: "Default environment",
    defaultPeriod: "Default analysis period",
    saved: "Changes saved",
    savedBody: "Your workspace has been updated.",
    simulateError: "Simulate a server error",
  },
  decision: {
    title: "Recommendations",
    approve: "Approve and act",
    approveTitle: "Apply the selected actions?",
    approveBody: "LEKA will apply these changes to your infrastructure.",
    reject: "Reject the selection",
    rejectTitle: "Reject the selection?",
    rejectBody: "These recommendations will not be applied.",
    rejectReason: "Reason for rejecting",
    approved: "Actions sent",
    rejected: "Selection rejected",
  },
  auth: {
    email: "Email",
    password: "Password",
    newPassword: "New password",
    signIn: "Sign in",
    signingIn: "Signing in…",
    signInTitle: "Sign in",
    signInDescription: "Access your workspace.",
    noAccount: "No account?",
    createOne: "Create one",
    forgot: "Forgot it?",
    resendConfirmation: "Send a new confirmation link",
    confirmationResent: "If that address needs confirming, a new link is on its way.",
    registerTitle: "Create an account",
    registerDescription: "Start mapping your environment.",
    alreadyHaveOne: "Already have one?",
    createAccount: "Create account",
    creating: "Creating…",
    passwordRule: "At least {min} characters. A memorable phrase beats a short, complicated word.",
    passwordRuleShort: "At least {min} characters.",
    checkInbox: "Check your inbox",
    registerSent: "If that address can be registered, a confirmation link is on its way.",
    registerLinkLife: "The link works for 24 hours, and once only.",
    backToSignIn: "Back to sign in",
    forgotTitle: "Reset your password",
    forgotDescription: "We will email you a link.",
    sendResetLink: "Send reset link",
    sending: "Sending…",
    resetSent: "If an account exists for that address, a reset link is on its way.",
    resetLinkLife: "The link works for one hour, and once only.",
    linkIncompleteTitle: "Link incomplete",
    linkIncompleteDescription: "This page needs the link from your email.",
    linkIncompleteBody:
      "Open the link exactly as it appears in the message — some email clients cut long links in half.",
    askNewLink: "Ask for a new link",
    resetTitle: "Choose a new password",
    resetDescription: "Every other signed-in device will be signed out.",
    setNewPassword: "Set new password",
    saving: "Saving…",
    verifyingTitle: "Confirming your address…",
    verifyingBody: "This takes a moment.",
    verifiedTitle: "Address confirmed",
    verifiedDescription: "Your account is ready.",
    verifiedBody: "You can close this tab once you have signed in.",
    verifyInvalidTitle: "This link is no longer valid",
    verifyInvalidDescription: "Confirmation links last 24 hours and work once.",
    verifyInvalidBody:
      "Sign in with your email and password, and we will offer to send a new link.",
    verifyFailedTitle: "Your address cannot be confirmed right now",
    errors: {
      invalidCredentials: "Invalid email or password.",
      accountUnverified:
        "Confirm your email address before signing in. Check your inbox — we can send another link.",
      rateLimited: "Too many attempts. Wait a few minutes before trying again.",
      tokenInvalid: "This link is no longer valid. Ask for a new one.",
      passwordTooShort: "This password is too short: at least {min} characters.",
      passwordBreached:
        "This password appears in a known data breach. Choose one you have not used elsewhere.",
      sessionExpired: "Your session expired while this page was open. Reload and try again.",
      invalid: "Check what you entered and try again.",
      offline: "You are offline. Check your connection and try again.",
      unreachable: "LEKA is not responding right now. Try again in a moment.",
      server: "Something went wrong on our side. Try again in a moment.",
      unknown: "That did not go through. Try again.",
    },
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
