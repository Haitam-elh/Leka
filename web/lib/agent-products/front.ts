import { type AgentProduct, w } from "@/lib/agent-products/types";

/** Frontend Craft (LEKA-461): the interfaces, read from their code. */
export const FRONT: Record<string, AgentProduct> = {
  "accessibility-audit": {
    promise: w(
      "Vérifiez que votre application est utilisable par tous : clavier, lecteurs d'écran, contrastes — au regard du WCAG 2.2 et du RGAA.",
      "Check that your application works for everyone: keyboard, screen readers, contrast — against WCAG 2.2 and the RGAA.",
    ),
    problem: w(
      "L'accessibilité se découvre souvent à l'audit final ou par une plainte, quand corriger coûte le plus cher.",
      "Accessibility is often discovered at the final audit or through a complaint, when fixing costs the most.",
    ),
    benefits: [
      {
        icon: "accessibility",
        title: w("WCAG 2.2 et RGAA", "WCAG 2.2 and RGAA"),
        body: w("Chaque constat rattaché à son critère.", "Every finding tied to its criterion."),
      },
      {
        icon: "target",
        title: w("Des corrections précises", "Precise fixes"),
        body: w(
          "Qui est gêné, où dans le code, et la correction proposée.",
          "Who is hindered, where in the code, and the proposed fix.",
        ),
      },
      {
        icon: "check",
        title: w("Ce qui est bien fait", "What is done well"),
        body: w("Les bonnes pratiques à garder, citées.", "The good practices to keep, cited."),
      },
    ],
    does: w(
      "Il lit le code front-end de votre dépôt — écrans, composants, styles et thème — et relève ce qui gêne le clavier, les lecteurs d'écran, les contrastes ou la taille du texte, critère par critère.",
      "It reads your repository's front-end code — screens, components, styles and theme — and reports what hinders keyboards, screen readers, contrast or text size, criterion by criterion.",
    ),
    features: [
      w("Formulaires, boutons, liens, menus et fenêtres passés en revue", "Forms, buttons, links, menus and dialogs reviewed"),
      w("Contrastes, tailles de texte et focus vérifiés", "Contrast, text sizes and focus checked"),
      w("Des constats par sévérité et critère WCAG / RGAA", "Findings by severity and WCAG / RGAA criterion"),
      w("Qui est gêné, et où dans le code", "Who is hindered, and where in the code"),
      w("Une correction proposée pour chaque constat", "A proposed fix for every finding"),
      w("L'audit d'une pull request, sur ce qu'elle change", "A pull request's audit, on what it changes"),
    ],
    useCases: [
      {
        icon: "accessibility",
        title: w("Préparer un audit RGAA", "Prepare an RGAA audit"),
        body: w("Corriger avant l'auditeur.", "Fix before the auditor comes."),
        ask: w("Mon application acme/web est-elle accessible ?", "Is my acme/web application accessible?"),
      },
      {
        icon: "git",
        title: w("Vérifier une pull request", "Check a pull request"),
        body: w("Ne pas introduire de nouveaux obstacles.", "Introduce no new barriers."),
        ask: w(
          "La dernière PR de acme/web casse-t-elle l'accessibilité ?",
          "Does acme/web's latest PR break accessibility?",
        ),
      },
      {
        icon: "eye",
        title: w("Contrôler un parcours clé", "Check a key journey"),
        body: w("Paiement, inscription : utilisables par tous.", "Payment, sign-up: usable by everyone."),
        ask: w(
          "Le formulaire de paiement de acme/web est-il utilisable au clavier ?",
          "Can acme/web's payment form be used with a keyboard?",
        ),
      },
      {
        icon: "palette",
        title: w("Vérifier les contrastes", "Check the contrast"),
        body: w("Des textes lisibles par tous.", "Text everyone can read."),
        ask: w(
          "Les couleurs de acme/web respectent-elles les contrastes WCAG ?",
          "Do acme/web's colours meet WCAG contrast?",
        ),
      },
    ],
    outline: [
      w("Ce qui a été audité", "What was audited"),
      w("Constats", "Findings"),
      w("Ce qui est bien fait", "What is done well"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats d'un audit", "An audit's findings"),
        items: [
          { level: "critical", text: w("Bouton icône sans nom accessible (4.1.2)", "Icon button with no accessible name (4.1.2)") },
          { level: "high", text: w("Contraste du texte secondaire insuffisant (1.4.3)", "Secondary text contrast too low (1.4.3)") },
          { level: "medium", text: w("Fenêtre sans retour du focus (2.4.3)", "Dialog without focus return (2.4.3)") },
          { level: "low", text: w("Langue de la page non déclarée (3.1.1)", "Page language not declared (3.1.1)") },
        ],
      },
      {
        kind: "list",
        title: w("Ce qui est bien fait", "What is done well"),
        items: [
          w("Lien d'évitement présent", "Skip link present"),
          w("Champs de formulaire étiquetés", "Form fields labelled"),
          w("Mouvement réduit respecté", "Reduced motion respected"),
        ],
      },
    ],
    limits: [
      w(
        "Un audit du code ne remplace pas un test avec un lecteur d'écran : le rendu réel et les contrastes non résolus sont à vérifier à la main.",
        "A code audit does not replace a screen reader test: the real rendering and unresolved contrasts are to be checked by hand.",
      ),
    ],
  },

  "design-review": {
    promise: w(
      "Vos écrans suivent-ils votre système de design ? Hiérarchie, espacements, typographie, couleurs et composants passés en revue.",
      "Do your screens follow your design system? Hierarchy, spacing, typography, colours and components reviewed.",
    ),
    problem: w(
      "Au fil des livraisons, les écrans divergent : couleurs en dur, espacements approximatifs, composants réinventés.",
      "Release after release, screens drift: hard-coded colours, approximate spacing, reinvented components.",
    ),
    benefits: [
      {
        icon: "palette",
        title: w("Une interface cohérente", "A consistent interface"),
        body: w("Les écarts au système de design, écran par écran.", "The gaps from the design system, screen by screen."),
      },
      {
        icon: "target",
        title: w("Des corrections précises", "Precise fixes"),
        body: w("Le jeton ou le composant attendu, et où le changer.", "The expected token or component, and where to change it."),
      },
      {
        icon: "layers",
        title: w("Votre référence fait foi", "Your reference rules"),
        body: w(
          "Celle que vous donnez, sinon le système de design du dépôt lui-même.",
          "The one you give, otherwise the repository's own design system.",
        ),
      },
    ],
    does: w(
      "Il lit les jetons et les composants de base de votre dépôt — variables CSS, thème, configuration Tailwind —, puis les écrans du périmètre, et relève ce qui s'écarte de la référence.",
      "It reads your repository's tokens and base components — CSS variables, theme, Tailwind configuration —, then the screens in scope, and reports what departs from the reference.",
    ),
    features: [
      w("La référence identifiée : jetons, composants, documentation", "The reference found: tokens, components, documentation"),
      w("Hiérarchie, espacements et typographie vérifiés", "Hierarchy, spacing and typography checked"),
      w("Couleurs en dur et composants réinventés repérés", "Hard-coded colours and reinvented components spotted"),
      w("Des constats par sévérité, écran par écran", "Findings by severity, screen by screen"),
      w("L'attendu : le jeton ou le composant à utiliser", "The expected: the token or component to use"),
      w("La revue d'une pull request, sur ce qu'elle change", "A pull request's review, on what it changes"),
    ],
    useCases: [
      {
        icon: "palette",
        title: w("Vérifier la cohérence visuelle", "Check visual consistency"),
        body: w("Les écrans au regard du design system.", "The screens against the design system."),
        ask: w(
          "Les écrans de acme/web suivent-ils notre système de design ?",
          "Do acme/web's screens follow our design system?",
        ),
      },
      {
        icon: "git",
        title: w("Relire une pull request d'interface", "Review an interface pull request"),
        body: w("Les écarts introduits par un changement.", "The gaps a change introduces."),
        ask: w(
          "La dernière PR de acme/web respecte-t-elle le design system ?",
          "Does acme/web's latest PR respect the design system?",
        ),
      },
      {
        icon: "layers",
        title: w("Comparer à une maquette", "Compare with a mock-up"),
        body: w("L'écran codé face à la référence donnée.", "The coded screen against the given reference."),
        ask: w(
          "L'écran de paiement de acme/web correspond-il à la maquette ?",
          "Does acme/web's payment screen match the mock-up?",
        ),
      },
      {
        icon: "search",
        title: w("Trouver les valeurs en dur", "Find hard-coded values"),
        body: w("Ce qui contourne les jetons.", "What bypasses the tokens."),
        ask: w("Où acme/web utilise-t-il des couleurs en dur ?", "Where does acme/web use hard-coded colours?"),
      },
    ],
    outline: [
      w("La référence", "The reference"),
      w("Constats", "Findings"),
      w("Ce qui est bien fait", "What is done well"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats d'une revue", "A review's findings"),
        items: [
          { level: "high", text: w("Couleur en dur au lieu du jeton primaire", "Hard-coded colour instead of the primary token") },
          { level: "medium", text: w("Espacement de 14 px hors de l'échelle", "14 px spacing off the scale") },
          { level: "low", text: w("Titre de section hors de l'échelle typographique", "Section title off the type scale") },
        ],
      },
      {
        kind: "list",
        title: w("Ce qui est bien fait", "What is done well"),
        items: [
          w("Boutons issus du composant commun", "Buttons from the shared component"),
          w("Rayons cohérents", "Consistent radii"),
          w("Échelle typographique respectée", "Type scale respected"),
        ],
      },
    ],
    limits: [
      w(
        "Ce qui ne se voit qu'à l'écran rendu — un alignement, un rendu de police — reste à vérifier visuellement.",
        "What only shows on the rendered screen — an alignment, a font rendering — remains to be checked visually.",
      ),
    ],
  },

  "motion-review": {
    promise: w(
      "Des animations utiles, fluides et respectueuses : durées, courbes, mouvement réduit et saccades passés en revue.",
      "Animations that are useful, smooth and considerate: durations, easing, reduced motion and jank reviewed.",
    ),
    problem: w(
      "Une animation trop longue, saccadée ou imposée à ceux qui ont demandé moins de mouvement dégrade l'expérience sans qu'on le voie en revue de code.",
      "An animation too long, janky or forced on people who asked for less motion degrades the experience without showing in code review.",
    ),
    benefits: [
      {
        icon: "move",
        title: w("Des transitions qui servent", "Transitions that help"),
        body: w("Ce qui aide à comprendre l'interface, et ce qui la ralentit.", "What helps understand the interface, and what slows it down."),
      },
      {
        icon: "accessibility",
        title: w("Le mouvement réduit respecté", "Reduced motion respected"),
        body: w("Les réglages prefers-reduced-motion vérifiés.", "The prefers-reduced-motion settings checked."),
      },
      {
        icon: "zap",
        title: w("Plus de fluidité", "Smoother"),
        body: w(
          "Propriétés coûteuses et saccades repérées, correction proposée.",
          "Costly properties and jank spotted, a fix proposed.",
        ),
      },
    ],
    does: w(
      "Il repère où vit le mouvement dans votre code — transitions et animations CSS, Framer Motion, GSAP, Web Animations — et juge chaque animation : utilité, durée, courbe, fluidité et mouvement réduit.",
      "It finds where motion lives in your code — CSS transitions and animations, Framer Motion, GSAP, Web Animations — and judges each animation: usefulness, duration, easing, smoothness and reduced motion.",
    ),
    features: [
      w("Transitions, keyframes et bibliothèques d'animation recensées", "Transitions, keyframes and animation libraries listed"),
      w("Durées et courbes comparées aux jetons du design system", "Durations and easing compared with the design system's tokens"),
      w("Le respect de prefers-reduced-motion", "Whether prefers-reduced-motion is respected"),
      w("Propriétés coûteuses et risques de saccade", "Costly properties and jank risks"),
      w("Ce que ressent la personne, pour chaque constat", "What the person feels, for each finding"),
      w("Une correction proposée : propriété, durée, courbe", "A proposed fix: property, duration, easing"),
    ],
    useCases: [
      {
        icon: "move",
        title: w("Auditer les animations d'une application", "Audit an application's animations"),
        body: w("Toutes ses transitions, jugées.", "All its transitions, judged."),
        ask: w("Les animations de acme/web sont-elles bien réglées ?", "Are acme/web's animations well tuned?"),
      },
      {
        icon: "accessibility",
        title: w("Respecter le mouvement réduit", "Respect reduced motion"),
        body: w("Pour ceux que le mouvement gêne.", "For those motion bothers."),
        ask: w("acme/web respecte-t-il prefers-reduced-motion ?", "Does acme/web respect prefers-reduced-motion?"),
      },
      {
        icon: "zap",
        title: w("Traquer les saccades", "Track down jank"),
        body: w("Ce qui risque de ne pas être fluide.", "What risks not being smooth."),
        ask: w("Quelles animations de acme/web risquent de saccader ?", "Which of acme/web's animations risk jank?"),
      },
      {
        icon: "git",
        title: w("Relire une pull request", "Review a pull request"),
        body: w("Les animations qu'elle ajoute ou change.", "The animations it adds or changes."),
        ask: w(
          "Les transitions ajoutées par la dernière PR de acme/web sont-elles correctes ?",
          "Are the transitions added by acme/web's latest PR right?",
        ),
      },
    ],
    outline: [
      w("Ce qui a été relu", "What was reviewed"),
      w("Constats", "Findings"),
      w("Ce qui est bien fait", "What is done well"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats d'une revue", "A review's findings"),
        items: [
          { level: "high", text: w("Menu animé sans variante mouvement réduit", "Menu animated with no reduced-motion variant") },
          { level: "medium", text: w("Transition de 600 ms sur un simple survol", "600 ms transition on a mere hover") },
          { level: "low", text: w("Courbe linéaire à l'apparition d'une carte", "Linear easing on a card appearing") },
        ],
      },
      {
        kind: "list",
        title: w("Corrections proposées", "Proposed fixes"),
        items: [
          w("Animer transform plutôt que top", "Animate transform rather than top"),
          w("Ramener la durée à 200 ms", "Bring the duration down to 200 ms"),
          w("Ajouter une variante prefers-reduced-motion", "Add a prefers-reduced-motion variant"),
        ],
      },
    ],
    limits: [
      w(
        "Ce qui ne se juge qu'en regardant l'animation jouer, ou en la mesurant, reste à vérifier dans le navigateur.",
        "What can only be judged by watching the animation play, or measuring it, remains to be checked in the browser.",
      ),
    ],
  },

  "ui-quality-review": {
    promise: w(
      "Vos écrans sont-ils vraiment finis ? États de chargement, vide et erreur, téléphone et données extrêmes passés en revue.",
      "Are your screens really finished? Loading, empty and error states, phones and extreme data reviewed.",
    ),
    problem: w(
      "Les écrans sont souvent testés avec des données idéales : un chargement, une liste vide, une erreur réseau ou un texte trop long les cassent en production.",
      "Screens are often tested with ideal data: a load, an empty list, a network error or a text too long breaks them in production.",
    ),
    benefits: [
      {
        icon: "check",
        title: w("Des écrans finis", "Finished screens"),
        body: w("Chargement, vide et erreur traités partout.", "Loading, empty and error handled everywhere."),
      },
      {
        icon: "eye",
        title: w("Vu comme vos utilisateurs", "Seen as your users see it"),
        body: w("Ce que voit la personne quand ça ne va pas.", "What the person sees when things go wrong."),
      },
      {
        icon: "target",
        title: w("Les défauts à la source", "Defects at the source"),
        body: w(
          "Un défaut d'un composant partagé, signalé une fois avec les écrans touchés.",
          "A shared component's defect, reported once with the screens it touches.",
        ),
      },
    ],
    does: w(
      "Il lit les écrans et les composants de votre application, en commençant par les composants partagés, et relève ce qui n'est pas fini : états manquants, comportement sur téléphone, données longues ou absentes.",
      "It reads your application's screens and components, starting with the shared ones, and reports what is unfinished: missing states, behaviour on a phone, long or missing data.",
    ),
    features: [
      w("États de chargement, vide et erreur vérifiés", "Loading, empty and error states checked"),
      w("Le comportement sur téléphone", "Behaviour on a phone"),
      w("Les données longues, manquantes ou inattendues", "Long, missing or unexpected data"),
      w("Les composants partagés passés en revue d'abord", "Shared components reviewed first"),
      w("Des constats par sévérité, avec ce que voit la personne", "Findings by severity, with what the person sees"),
      w("Une correction proposée en une phrase", "A fix proposed in a sentence"),
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Avant une mise en production", "Before going live"),
        body: w("Les écrans prêts, vraiment.", "Screens truly ready."),
        ask: w(
          "Les écrans de acme/web sont-ils prêts pour la production ?",
          "Are acme/web's screens ready for production?",
        ),
      },
      {
        icon: "eye",
        title: w("Vérifier un écran", "Check a screen"),
        body: w("Liste vide, erreur, chargement.", "Empty list, error, loading."),
        ask: w(
          "L'écran des factures de acme/web gère-t-il les listes vides et les erreurs ?",
          "Does acme/web's invoice screen handle empty lists and errors?",
        ),
      },
      {
        icon: "git",
        title: w("Relire une pull request d'interface", "Review an interface pull request"),
        body: w("Les écrans qu'elle ajoute, finis ou non.", "The screens it adds, finished or not."),
        ask: w(
          "Les écrans ajoutés par la dernière PR de acme/web sont-ils finis ?",
          "Are the screens added by acme/web's latest PR finished?",
        ),
      },
      {
        icon: "layers",
        title: w("Contrôler les composants partagés", "Check the shared components"),
        body: w("Corriger une fois, partout.", "Fix once, everywhere."),
        ask: w(
          "Les composants partagés de acme/web gèrent-ils leurs états ?",
          "Do acme/web's shared components handle their states?",
        ),
      },
    ],
    outline: [
      w("Ce qui a été relu", "What was reviewed"),
      w("Constats", "Findings"),
      w("Ce qui est bien fait", "What is done well"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats d'une revue", "A review's findings"),
        items: [
          { level: "high", text: w("Aucun état d'erreur sur la liste des factures", "No error state on the invoice list") },
          { level: "medium", text: w("Tableau qui déborde sur téléphone", "Table overflowing on a phone") },
          { level: "low", text: w("Nom de client long tronqué sans info-bulle", "Long customer name cut with no tooltip") },
        ],
      },
      {
        kind: "list",
        title: w("Ce qui est bien fait", "What is done well"),
        items: [
          w("Squelettes de chargement cohérents", "Consistent loading skeletons"),
          w("Liste vide avec une action", "Empty list with an action"),
          w("Boutons désactivés pendant l'envoi", "Buttons disabled while sending"),
        ],
      },
    ],
    limits: [
      w(
        "Ce qui ne se juge qu'à l'écran rendu reste à vérifier dans le navigateur.",
        "What can only be judged on the rendered screen remains to be checked in the browser.",
      ),
    ],
  },
};
