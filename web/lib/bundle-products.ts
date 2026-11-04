/**
 * A bundle said to whoever might buy it (LEKA-531): one structure for every
 * bundle on sale, in French and in English — its promise, who it is for, the
 * problem it solves, what it brings, when it serves.
 *
 * Written from what its agents do (their SKILL.md, their product pages) and
 * nothing they do not. What changes is never written here: its price, its
 * cadence, its agents, their prices, the saving and whether this workspace
 * owns it are the API's (GET /billing/add-ons, the catalogue). A bundle not
 * here has a page all the same, said from the API only.
 */

import { type ProductIcon, type Words, w } from "@/lib/agent-products/types";

export type BundleProduct = {
  /** What it brings, in a sentence: the page's promise. */
  readonly promise: Words;
  /** Who it is for. */
  readonly audience: Words;
  /** The concrete problem it solves. */
  readonly problem: Words;
  /** « Pourquoi ce bundle ? »: three. */
  readonly benefits: readonly { icon: ProductIcon; title: Words; body: Words }[];
  /** Three situations it serves. */
  readonly useCases: readonly { icon: ProductIcon; title: Words; body: Words }[];
};

export const BUNDLE_PRODUCTS: Readonly<Record<string, BundleProduct>> = {
  engineering: {
    promise: w(
      "Concevez, relisez et testez votre code avec six agents qui lisent vos dépôts : explorer un code inconnu, relire une pull request, savoir quoi tester et ce qu'un changement touche.",
      "Design, review and test your code with six agents that read your repositories: explore unfamiliar code, review a pull request, know what to test and what a change touches.",
    ),
    audience: w(
      "Les équipes de développement qui livrent chaque semaine et veulent des revues et des tests à la hauteur, sans y passer leurs journées.",
      "Development teams that ship every week and want reviews and tests up to the mark, without spending their days on them.",
    ),
    problem: w(
      "Une revue faite trop vite, un test oublié, un changement dont on mesure mal la portée : c'est ce qui casse la production. Relire et préparer les tests prend du temps, et ce temps manque.",
      "A rushed review, a forgotten test, a change whose reach is misjudged: that is what breaks production. Reviewing and planning tests takes time, and that time is short.",
    ),
    benefits: [
      {
        icon: "git",
        title: w("Des revues plus sûres", "Safer reviews"),
        body: w(
          "Chaque pull request relue : ce qu'elle touche, ce qu'elle risque, ce qu'il faut corriger avant de fusionner.",
          "Every pull request reviewed: what it touches, what it risks, what to fix before merging.",
        ),
      },
      {
        icon: "check",
        title: w("Les bons tests", "The right tests"),
        body: w(
          "Ce qu'il faut tester avant et après un changement, et des tests proposés là où il en manque.",
          "What to test before and after a change, and tests proposed where they are missing.",
        ),
      },
      {
        icon: "target",
        title: w("La portée de chaque changement", "Each change's reach"),
        body: w(
          "Ce qu'un changement touche, ce qui en dépend et les régressions possibles, avant la mise en production.",
          "What a change touches, what depends on it and the regressions it may cause, before it ships.",
        ),
      },
    ],
    useCases: [
      {
        icon: "search",
        title: w("Prendre en main un dépôt", "Getting to know a repository"),
        body: w(
          "Son organisation, ses points d'entrée et où vit une fonctionnalité, en quelques minutes.",
          "How it is organised, where it starts and where a feature lives, in minutes.",
        ),
      },
      {
        icon: "git",
        title: w("Relire une pull request", "Reviewing a pull request"),
        body: w(
          "Une revue argumentée, ligne par ligne, et les tests qui manquent pour la fusionner sereinement.",
          "A reasoned review, line by line, and the tests it lacks to be merged with confidence.",
        ),
      },
      {
        icon: "rocket",
        title: w("Préparer une livraison", "Preparing a release"),
        body: w(
          "Ce qu'elle change, ce qu'il faut tester et ce qui a déjà cassé autour.",
          "What it changes, what to test and what already broke around it.",
        ),
      },
    ],
  },
  "ship-safe": {
    promise: w(
      "Livrez sans mauvaise surprise : API, migrations, tests, mise en production et sécurité passés en revue avant chaque livraison.",
      "Ship without bad surprises: APIs, migrations, tests, releases and security reviewed before every release.",
    ),
    audience: w(
      "Les équipes qui mettent souvent en production et pour qui une régression ou une faille coûte cher : plateformes, API publiques, produits réglementés.",
      "Teams that ship often and for whom a regression or a vulnerability is costly: platforms, public APIs, regulated products.",
    ),
    problem: w(
      "Un contrat d'API cassé, une migration risquée, une faille non vue, une livraison mal préparée : on le découvre souvent trop tard, en production.",
      "A broken API contract, a risky migration, an unseen vulnerability, an ill-prepared release: often found too late, in production.",
    ),
    benefits: [
      {
        icon: "rocket",
        title: w("Des livraisons maîtrisées", "Releases under control"),
        body: w(
          "Ce qu'une livraison contient, ce qu'elle risque et ce qu'il faut vérifier avant de la déployer.",
          "What a release holds, what it risks and what to check before deploying it.",
        ),
      },
      {
        icon: "shield",
        title: w("La sécurité dans la boucle", "Security in the loop"),
        body: w(
          "Les failles du code relevées avant la mise en production, chacune avec sa correction.",
          "The code's vulnerabilities raised before release, each with its fix.",
        ),
      },
      {
        icon: "layers",
        title: w("Des API et des migrations sûres", "Safe APIs and migrations"),
        body: w(
          "Les contrats d'API relus et les migrations planifiées étape par étape, avec leur retour arrière.",
          "API contracts reviewed and migrations planned step by step, with their way back.",
        ),
      },
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Avant une mise en production", "Before a release"),
        body: w(
          "Ce qui part, ce qu'il faut tester, les régressions possibles et les failles à corriger d'abord.",
          "What ships, what to test, the possible regressions and the vulnerabilities to fix first.",
        ),
      },
      {
        icon: "code",
        title: w("Faire évoluer une API", "Evolving an API"),
        body: w(
          "Ce qu'un changement casse chez ceux qui l'appellent, et comment le rendre compatible.",
          "What a change breaks for its callers, and how to keep it compatible.",
        ),
      },
      {
        icon: "route",
        title: w("Planifier une migration", "Planning a migration"),
        body: w(
          "Les étapes, leur ordre, leurs risques et le retour arrière de chacune.",
          "The steps, their order, their risks and the way back from each.",
        ),
      },
    ],
  },
  "incident-response": {
    promise: w(
      "Investiguez, diagnostiquez et résolvez vos incidents plus vite : la cause, ce qui est touché et ce qu'il faut faire, depuis vos propres données.",
      "Investigate, diagnose and resolve your incidents faster: the cause, what is affected and what to do, from your own data.",
    ),
    audience: w(
      "Les équipes d'astreinte, SRE et exploitation qui doivent comprendre vite ce qui se passe quand un service tombe ou ralentit.",
      "On-call, SRE and operations teams who must understand fast what is happening when a service goes down or slows down.",
    ),
    problem: w(
      "Pendant un incident, l'information est éparpillée entre les alertes, les déploiements, les logs et la documentation. Remonter à la cause prend du temps, et chaque minute compte.",
      "During an incident, what you need is scattered across alerts, deployments, logs and documentation. Tracing the cause takes time, and every minute counts.",
    ),
    benefits: [
      {
        icon: "search",
        title: w("La cause, plus vite", "The cause, faster"),
        body: w(
          "Ce qui a changé, ce qui dépend de quoi et ce que disent vos sources, rassemblés pour remonter à la cause.",
          "What changed, what depends on what and what your sources say, brought together to trace the cause.",
        ),
      },
      {
        icon: "zap",
        title: w("Les lenteurs expliquées", "Slowdowns explained"),
        body: w(
          "Où le temps se perd et pourquoi, avant que vos clients ne le remarquent.",
          "Where time is lost and why, before your customers notice.",
        ),
      },
      {
        icon: "shield",
        title: w("Moins d'incidents ensuite", "Fewer incidents next"),
        body: w(
          "Les points fragiles relevés après coup, pour que le même incident ne revienne pas.",
          "The weak points raised afterwards, so the same incident does not come back.",
        ),
      },
    ],
    useCases: [
      {
        icon: "alert",
        title: w("Un service est indisponible", "A service is down"),
        body: w(
          "Ce qui a changé juste avant, ce qui en dépend et les pistes de cause, classées.",
          "What changed just before, what depends on it and the likely causes, ranked.",
        ),
      },
      {
        icon: "clock",
        title: w("Une API ralentit", "An API slows down"),
        body: w(
          "Les goulots d'étranglement trouvés et les optimisations proposées.",
          "The bottlenecks found and the optimisations proposed.",
        ),
      },
      {
        icon: "book",
        title: w("Après l'incident", "After the incident"),
        body: w(
          "Ce qui l'a rendu possible et ce qu'il faut renforcer pour qu'il ne se reproduise pas.",
          "What made it possible and what to strengthen so it does not happen again.",
        ),
      },
    ],
  },
  "security-reliability": {
    promise: w(
      "Renforcez la sécurité et la fiabilité de vos systèmes : failles, dépendances, API, bases de données et points de rupture passés en revue.",
      "Strengthen your systems' security and reliability: vulnerabilities, dependencies, APIs, databases and breaking points reviewed.",
    ),
    audience: w(
      "Les équipes sécurité, plateforme et SRE qui veulent un regard régulier sur ce qui expose ou fragilise leurs systèmes.",
      "Security, platform and SRE teams who want a regular look at what exposes or weakens their systems.",
    ),
    problem: w(
      "Une dépendance vulnérable, une API trop permissive, une requête qui ne tiendra pas la charge : ces risques s'accumulent sans bruit, jusqu'au jour où ils coûtent cher.",
      "A vulnerable dependency, an over-permissive API, a query that will not hold the load: these risks pile up quietly, until the day they cost a lot.",
    ),
    benefits: [
      {
        icon: "shield",
        title: w("Les failles avant les attaquants", "Vulnerabilities before attackers"),
        body: w(
          "Le code et ses dépendances passés en revue, chaque faille avec sa gravité et sa correction.",
          "The code and its dependencies reviewed, each vulnerability with its severity and its fix.",
        ),
      },
      {
        icon: "database",
        title: w("Des données qui tiennent", "Data that holds"),
        body: w(
          "Schémas, requêtes et migrations relus pour la performance et l'intégrité.",
          "Schemas, queries and migrations reviewed for performance and integrity.",
        ),
      },
      {
        icon: "target",
        title: w("Les points de rupture connus", "Breaking points known"),
        body: w(
          "Ce qui peut tomber, ce qui en dépend et comment le rendre plus robuste.",
          "What can fail, what depends on it and how to make it more robust.",
        ),
      },
    ],
    useCases: [
      {
        icon: "shield",
        title: w("Un audit de sécurité", "A security audit"),
        body: w(
          "Les failles du code et des dépendances, classées par gravité, avec leur correction.",
          "The code's and dependencies' vulnerabilities, ranked by severity, with their fix.",
        ),
      },
      {
        icon: "database",
        title: w("Une base qui ralentit", "A slowing database"),
        body: w(
          "Les requêtes et index en cause, et ce qu'il faut changer.",
          "The queries and indexes at fault, and what to change.",
        ),
      },
      {
        icon: "layers",
        title: w("Avant une montée en charge", "Before a traffic surge"),
        body: w(
          "Les dépendances fragiles et les points uniques de défaillance à renforcer.",
          "The fragile dependencies and single points of failure to strengthen.",
        ),
      },
    ],
  },
  "frontend-craft": {
    promise: w(
      "La qualité de vos interfaces : rendu, accessibilité, design et animations relus comme le ferait un œil expert.",
      "Your interfaces' quality: rendering, accessibility, design and motion reviewed as an expert eye would.",
    ),
    audience: w(
      "Les équipes produit et front-end qui veulent des interfaces soignées, accessibles et cohérentes, sans attendre une revue design.",
      "Product and front-end teams who want polished, accessible and consistent interfaces, without waiting for a design review.",
    ),
    problem: w(
      "Un contraste insuffisant, un composant incohérent, une animation qui gêne : ces défauts passent souvent les revues de code et finissent devant vos utilisateurs.",
      "Too little contrast, an inconsistent component, a distracting animation: these flaws often get past code reviews and end up in front of your users.",
    ),
    benefits: [
      {
        icon: "accessibility",
        title: w("Accessible à tous", "Accessible to everyone"),
        body: w(
          "Les écarts aux règles d'accessibilité relevés, chacun avec sa correction.",
          "The gaps to accessibility rules raised, each with its fix.",
        ),
      },
      {
        icon: "palette",
        title: w("Un design cohérent", "A consistent design"),
        body: w(
          "Les écarts au système de design, et des maquettes proposées pour les corriger.",
          "The gaps to the design system, and mock-ups proposed to fix them.",
        ),
      },
      {
        icon: "move",
        title: w("Des animations justes", "Motion done right"),
        body: w(
          "Animations et transitions relues : utiles, fluides et respectueuses des préférences de chacun.",
          "Animations and transitions reviewed: useful, smooth and respectful of everyone's preferences.",
        ),
      },
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Avant une sortie", "Before a launch"),
        body: w(
          "Les écrans relus pour le rendu, l'accessibilité et la cohérence.",
          "The screens reviewed for rendering, accessibility and consistency.",
        ),
      },
      {
        icon: "accessibility",
        title: w("Un audit d'accessibilité", "An accessibility audit"),
        body: w(
          "Ce qui empêche certains de vos utilisateurs de se servir du produit, et comment le corriger.",
          "What keeps some of your users from using the product, and how to fix it.",
        ),
      },
      {
        icon: "palette",
        title: w("Harmoniser un produit", "Bringing a product together"),
        body: w(
          "Les composants qui divergent, et la direction à retenir, en maquettes.",
          "The components that drift apart, and the direction to keep, in mock-ups.",
        ),
      },
    ],
  },
};

export function bundleProductOf(key: string): BundleProduct | null {
  return BUNDLE_PRODUCTS[key] ?? null;
}
