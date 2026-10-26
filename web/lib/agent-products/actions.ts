import type { Words } from "@/lib/agent-products/types";

/**
 * What each agent's deliverable leads to (Karim, 2026-10-23): an analysis
 * any model can write; what LEKA delivers is the action that settles it,
 * one click away at the end of every deliverable — never only a report.
 *
 *     fix      the code-change agent writes the correction from the
 *              deliverable — shown before / after, a pull request only once
 *              a person accepts it
 *     tests    the test-generation agent writes the missing tests, the same
 *              way
 *     issues   tickets LEKA drafts for a Jira project, created once a
 *              person chose them
 *     pages    pages for a Confluence space, the same way
 *     change   for the agents whose deliverable is itself a change: see it,
 *              then send it to GitHub
 *
 * The first step is the agent's own: what settles what it found. Every
 * agent on sale has at least one (actions.test.ts).
 */

export type NextStepKind = "fix" | "tests" | "issues" | "pages" | "change";

export type NextStep = {
  readonly kind: NextStepKind;
  readonly title: Words;
  readonly body: Words;
  /** What the writing agent is asked, before the deliverable itself. */
  readonly focus?: Words;
};

const w = (fr: string, en: string): Words => ({ fr, en });

function fix(title: Words, body: Words, focus: Words): NextStep {
  return { kind: "fix", title, body, focus };
}

function tests(focus: Words): NextStep {
  return {
    kind: "tests",
    title: w("Écrire les tests manquants", "Write the missing tests"),
    body: w(
      "LEKA écrit les tests que ce livrable demande ; vous les relisez avant la pull request.",
      "LEKA writes the tests this deliverable calls for; you review them before the pull request.",
    ),
    focus,
  };
}

function issues(title: Words, body: Words): NextStep {
  return { kind: "issues", title, body };
}

function pages(title: Words, body: Words): NextStep {
  return { kind: "pages", title, body };
}

const TICKETS = issues(
  w("Créer les tickets", "Create the tickets"),
  w(
    "Une action par ticket dans Jira, avec sa priorité : créés quand vous les avez choisis.",
    "One action per ticket in Jira, with its priority: created once you chose them.",
  ),
);

const PAGE = pages(
  w("Publier sur Confluence", "Publish to Confluence"),
  w(
    "Le livrable mis en page pour votre espace, publié quand vous l'avez relu.",
    "The deliverable laid out for your space, published once you read it.",
  ),
);

const CODE_FIX = (focus: Words, title = w("Corriger dans le code", "Fix it in the code")): NextStep =>
  fix(
    title,
    w(
      "LEKA écrit la correction de chaque constat ; vous la voyez avant / après, puis la pull request.",
      "LEKA writes the fix of each finding; you see it before / after, then the pull request.",
    ),
    focus,
  );

const CHANGE: NextStep = {
  kind: "change",
  title: w("Envoyer la modification sur GitHub", "Send the change to GitHub"),
  body: w(
    "La modification avant / après : acceptée, elle devient une pull request.",
    "The change before / after: accepted, it becomes a pull request.",
  ),
};

export const NEXT_STEPS: Readonly<Record<string, readonly NextStep[]>> = {
  // ── Architecture & code ──────────────────────────────────────────────────
  "application-architecture": [
    pages(
      w("Publier l'architecture sur Confluence", "Publish the architecture to Confluence"),
      w(
        "Le dossier d'architecture en pages, pour l'équipe et les décideurs.",
        "The architecture file as pages, for the team and the decision makers.",
      ),
    ),
    issues(
      w("Créer les tickets des risques", "Create the risks' tickets"),
      w("Chaque risque et chaque décision à prendre, en ticket.", "Each risk and each decision to make, as a ticket."),
    ),
  ],
  "architecture-analysis": [
    issues(
      w("Créer les tickets des risques", "Create the risks' tickets"),
      w(
        "Chaque point de fragilité de l'architecture, en ticket pour l'équipe qui en répond.",
        "Each weak point of the architecture, as a ticket for the team answering for it.",
      ),
    ),
    PAGE,
  ],
  "codebase-explorer": [
    pages(
      w("Publier le guide du code", "Publish the code guide"),
      w(
        "Le guide pour se repérer dans le dépôt, en page pour les nouveaux arrivants.",
        "The guide to find one's way in the repository, as a page for newcomers.",
      ),
    ),
  ],
  "code-change": [CHANGE],
  "code-review": [
    CODE_FIX(
      w(
        "Corrige les constats bloquants et importants de cette revue, un par un, par le plus petit changement.",
        "Fix the blocking and important findings of this review, one by one, with the smallest change.",
      ),
    ),
    TICKETS,
  ],
  // ── Tests & quality ──────────────────────────────────────────────────────
  "test-analysis": [
    tests(
      w(
        "Écris les tests que cette analyse dit manquer, les plus critiques d'abord.",
        "Write the tests this analysis says are missing, the most critical first.",
      ),
    ),
    TICKETS,
  ],
  "test-generation": [CHANGE],
  "qa-acceptance": [
    CODE_FIX(
      w(
        "Corrige les problèmes trouvés par cette recette (les bloquants d'abord) pour que chaque critère soit tenu.",
        "Fix the issues this acceptance found (the blocking first) so that each criterion is met.",
      ),
      w("Corriger ce qui bloque", "Fix what blocks"),
    ),
    tests(
      w(
        "Écris les tests qui prouvent chaque critère « Fait, sans preuve » de cette recette.",
        "Write the tests proving each criterion this acceptance found « Done, without proof ».",
      ),
    ),
    TICKETS,
  ],
  "regression-analysis": [
    tests(
      w(
        "Écris les tests qui gardent les comportements que ce changement peut casser.",
        "Write the tests guarding the behaviours this change could break.",
      ),
    ),
    TICKETS,
  ],
  // ── Debug & incidents ────────────────────────────────────────────────────
  "debug-assistant": [
    CODE_FIX(
      w(
        "Corrige la cause la plus probable que ce diagnostic établit, par le plus petit changement, et ajoute le test qui la reproduit.",
        "Fix the most likely cause this diagnosis establishes, with the smallest change, and add the test reproducing it.",
      ),
      w("Corriger la cause", "Fix the cause"),
    ),
    TICKETS,
  ],
  "change-impact-analysis": [
    issues(
      w("Créer les vérifications", "Create the checks"),
      w(
        "Une vérification par équipe ou système touché, en ticket, avant de livrer.",
        "One check per team or system reached, as a ticket, before shipping.",
      ),
    ),
    tests(
      w(
        "Écris les tests des comportements que ce changement atteint, les plus critiques d'abord.",
        "Write the tests of the behaviours this change reaches, the most critical first.",
      ),
    ),
  ],
  "reliability-analysis": [
    CODE_FIX(
      w(
        "Corrige dans le code les actions de cette analyse : délais d'attente, reprises bornées, erreurs avalées, vérifications de santé, la plus utile d'abord.",
        "Fix in the code this analysis's actions: timeouts, bounded retries, swallowed errors, health checks, the most useful first.",
      ),
      w("Renforcer le code", "Harden the code"),
    ),
    issues(
      w("Créer les tickets des actions", "Create the actions' tickets"),
      w(
        "Les actions d'infrastructure et de détection, en tickets pour leurs équipes.",
        "The infrastructure and detection actions, as tickets for their teams.",
      ),
    ),
    PAGE,
  ],
  "incident-investigation": [
    pages(
      w("Publier le post-mortem", "Publish the post-mortem"),
      w(
        "Le post-mortem sur Confluence : chronologie, cause, ce qui change.",
        "The post-mortem on Confluence: timeline, cause, what changes.",
      ),
    ),
    issues(
      w("Créer les actions correctives", "Create the corrective actions"),
      w("Chaque action du post-mortem, en ticket avec son responsable.", "Each action of the post-mortem, as a ticket with its owner."),
    ),
    CODE_FIX(
      w(
        "Corrige la cause de cet incident dans le code, par le plus petit changement, et ajoute le test qui l'aurait vue.",
        "Fix this incident's cause in the code, with the smallest change, and add the test that would have caught it.",
      ),
      w("Corriger la cause", "Fix the cause"),
    ),
  ],
  "build-fixer": [
    CODE_FIX(
      w(
        "Applique la correction qui remet le build au vert, rien d'autre.",
        "Apply the fix that turns the build green, nothing else.",
      ),
      w("Réparer le build", "Repair the build"),
    ),
  ],
  // ── Security ─────────────────────────────────────────────────────────────
  "security-review": [
    CODE_FIX(
      w(
        "Corrige dans le code les failles de cette revue, les bloquantes d'abord, sans affaiblir aucune protection.",
        "Fix in the code this review's flaws, the blocking first, without weakening any protection.",
      ),
      w("Corriger les failles", "Fix the flaws"),
    ),
    TICKETS,
  ],
  "dependency-analysis": [
    fix(
      w("Mettre à jour les dépendances", "Upgrade the dependencies"),
      w(
        "LEKA monte chaque dépendance vulnérable à la version qui corrige ; vous relisez avant la pull request.",
        "LEKA upgrades each vulnerable dependency to the fixing version; you review before the pull request.",
      ),
      w(
        "Monte dans les manifestes chaque dépendance vulnérable de cette analyse à la version qui corrige : les plus urgentes d'abord, une version majeure dite comme telle. Ne modifie pas un fichier de verrouillage à la main : dis la commande qui le régénère.",
        "Upgrade in the manifests each vulnerable dependency of this analysis to the fixing version: the most urgent first, a major version said as such. Never edit a lock file by hand: say the command that regenerates it.",
      ),
    ),
    TICKETS,
  ],
  // ── Performance & data ───────────────────────────────────────────────────
  "performance-analysis": [
    CODE_FIX(
      w(
        "Applique les corrections de cette analyse sur le chemin lent (requêtes N+1, appels en série, listes sans limite), la plus utile d'abord, sans changer le comportement.",
        "Apply this analysis's fixes on the slow path (N+1 queries, calls in sequence, unbounded lists), the most useful first, without changing the behaviour.",
      ),
      w("Optimiser le code", "Optimise the code"),
    ),
    TICKETS,
  ],
  "data-analysis": [TICKETS, PAGE],
  "api-design-review": [
    CODE_FIX(
      w(
        "Corrige les constats de cette revue d'API sans rupture pour les clients : ce qui romprait passe par une nouvelle version ou une dépréciation.",
        "Fix this API review's findings without breaking the clients: what would break goes through a new version or a deprecation.",
      ),
    ),
    TICKETS,
  ],
  "database-review": [
    fix(
      w("Écrire la migration", "Write the migration"),
      w(
        "LEKA écrit la migration qui corrige le schéma : réversible, sans verrouiller ; vous relisez avant la pull request.",
        "LEKA writes the migration fixing the schema: reversible, without locking; you review before the pull request.",
      ),
      w(
        "Écris, dans l'outil de migration du dépôt, la migration qui corrige les constats bloquants et importants de cette revue : index créés sans verrouiller, contraintes, types, réversible, et les requêtes du code à corriger.",
        "Write, in the repository's migration tool, the migration fixing this review's blocking and important findings: indexes created without locking, constraints, types, reversible, and the code's queries to fix.",
      ),
    ),
    TICKETS,
  ],
  // ── Frontend & design ────────────────────────────────────────────────────
  "accessibility-audit": [
    CODE_FIX(
      w(
        "Corrige dans le code les manquements de cet audit, les bloquants d'abord, critère par critère.",
        "Fix in the code this audit's failures, the blocking first, criterion by criterion.",
      ),
    ),
    TICKETS,
  ],
  "design-review": [
    CODE_FIX(
      w(
        "Implémente dans le code la direction retenue de cette revue de design, écran par écran.",
        "Implement in the code this design review's chosen direction, screen by screen.",
      ),
      w("Implémenter le design", "Implement the design"),
    ),
    TICKETS,
  ],
  "ui-quality-review": [
    CODE_FIX(
      w(
        "Corrige les défauts d'interface de cette revue, les plus visibles d'abord.",
        "Fix this review's interface defects, the most visible first.",
      ),
    ),
    TICKETS,
  ],
  "motion-review": [
    CODE_FIX(
      w(
        "Corrige les animations relevées par cette revue : durées, courbes, propriétés animées, mouvement réduit.",
        "Fix the animations this review found: durations, curves, animated properties, reduced motion.",
      ),
    ),
    TICKETS,
  ],
  // ── DevOps & release ─────────────────────────────────────────────────────
  "infrastructure-analysis": [
    issues(
      w("Créer les tickets d'infrastructure", "Create the infrastructure tickets"),
      w(
        "Chaque ressource à corriger, en ticket pour l'équipe qui la possède.",
        "Each resource to fix, as a ticket for the team owning it.",
      ),
    ),
    PAGE,
  ],
  "release-analysis": [
    issues(
      w("Créer les vérifications avant livraison", "Create the pre-release checks"),
      w(
        "Chaque condition du « on y va » de la release, en ticket.",
        "Each condition of the release's go, as a ticket.",
      ),
    ),
    pages(
      w("Publier les notes de version", "Publish the release notes"),
      w("Les notes de version et l'analyse, sur Confluence.", "The release notes and the analysis, on Confluence."),
    ),
  ],
  "migration-planning": [
    issues(
      w("Créer un ticket par étape", "Create one ticket per step"),
      w(
        "Chaque étape du plan en ticket, dans l'ordre, avec sa vérification et son retour arrière.",
        "Each step of the plan as a ticket, in order, with its check and its way back.",
      ),
    ),
    pages(
      w("Publier le plan de migration", "Publish the migration plan"),
      w("Le plan complet sur Confluence, pour ceux qui en dépendent.", "The whole plan on Confluence, for those depending on it."),
    ),
  ],
  // ── Documentation ────────────────────────────────────────────────────────
  "documentation-assistant": [
    pages(
      w("Publier la documentation", "Publish the documentation"),
      w("Les pages écrites, publiées dans votre espace Confluence.", "The pages written, published to your Confluence space."),
    ),
    TICKETS,
  ],
};

/** Any other agent — a draft, one built after this list — still ends on an
 * action: its findings as tickets, its deliverable as a page. */
const ANY: readonly NextStep[] = [TICKETS, PAGE];

export function nextStepsOf(key: string): readonly NextStep[] {
  return NEXT_STEPS[key] ?? ANY;
}

/** The agent that writes a step's change: the code's, or the tests'. */
export const WRITER: Readonly<Record<"fix" | "tests", string>> = {
  fix: "code-change",
  tests: "test-generation",
};
