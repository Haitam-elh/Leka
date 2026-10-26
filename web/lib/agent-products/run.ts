import { type AgentProduct, w } from "@/lib/agent-products/types";

/** Shipping, running and securing: releases, incidents, infrastructure,
 * data and documentation. */
export const RUN: Record<string, AgentProduct> = {
  "release-analysis": {
    promise: w(
      "Évaluez une release avant et après sa sortie : ce qui part, ce qu'elle touche, ce qui s'est passé ensuite et comment revenir en arrière.",
      "Assess a release before and after it ships: what goes out, what it touches, what happened next and how to roll back.",
    ),
    problem: w(
      "Après une mise en production, relier un incident à ce qui vient de partir demande de croiser déploiements, pull requests et incidents à la main.",
      "After a release, linking an incident to what just shipped means cross-checking deployments, pull requests and incidents by hand.",
    ),
    benefits: [
      {
        icon: "rocket",
        title: w("Des mises en production maîtrisées", "Releases under control"),
        body: w(
          "Un verdict en une phrase, ce qui le bloque et ce qui manque pour en être sûr.",
          "A verdict in a sentence, what blocks it and what is missing to be sure.",
        ),
      },
      {
        icon: "search",
        title: w("Le lien avec les incidents", "The link with incidents"),
        body: w(
          "Les incidents et changements survenus après la release, et leur lien possible.",
          "The incidents and changes after the release, and how they may be linked.",
        ),
      },
      {
        icon: "route",
        title: w("Le retour arrière prévu", "Rollback planned"),
        body: w(
          "Ce qu'il faudra surveiller et le retour arrière à préparer pour la suivante.",
          "What to watch and the rollback to prepare for the next one.",
        ),
      },
    ],
    does: w(
      "Il rassemble les changements et pull requests d'une release, les services qu'elle a touchés et ce qui s'est passé après, puis rend une évaluation argumentée et les points à surveiller pour la prochaine.",
      "It gathers a release's changes and pull requests, the services it touched and what happened after, then returns a reasoned assessment and the points to watch for the next one.",
    ),
    features: [
      w("Ce qui est parti : changements, PR, services", "What shipped: changes, PRs, services"),
      w("Ce qui s'est passé après, et le lien possible", "What happened after, and the possible link"),
      w("Un verdict en une phrase", "A verdict in a sentence"),
      w("Ce qui a été vérifié et ce qui manque", "What was checked and what is missing"),
      w("Ce qu'il faudra surveiller", "What to watch"),
      w("Le retour arrière à prévoir", "The rollback to plan"),
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Valider une release", "Validate a release"),
        body: w("Savoir si elle peut partir, et ce qui manque.", "Know whether it can ship, and what is missing."),
        ask: w("La release 2.8.4 de payment-api est-elle prête ?", "Is payment-api's 2.8.4 release ready?"),
      },
      {
        icon: "alert",
        title: w("Expliquer un incident après déploiement", "Explain an incident after a deployment"),
        body: w("Relier ce qui vient de partir à ce qui casse.", "Link what just shipped to what breaks."),
        ask: w(
          "Le déploiement d'hier sur checkout a-t-il causé l'incident de ce matin ?",
          "Did yesterday's checkout deployment cause this morning's incident?",
        ),
      },
      {
        icon: "search",
        title: w("Faire le bilan d'une release", "Review a release"),
        body: w("Ce qui est parti, et ce qui a suivi.", "What shipped, and what followed."),
        ask: w(
          "Qu'est-ce qui est parti dans la dernière release de payment-api ?",
          "What went out in payment-api's latest release?",
        ),
      },
      {
        icon: "route",
        title: w("Préparer le retour arrière", "Prepare the rollback"),
        body: w("Le plan B avant de livrer.", "The plan B before shipping."),
        ask: w(
          "Comment revenir en arrière si la release 2.9 de checkout pose problème ?",
          "How do we roll back if checkout's 2.9 release goes wrong?",
        ),
      },
    ],
    outline: [
      w("Ce qui est parti", "What shipped"),
      w("Après", "After"),
      w("Évaluation", "Assessment"),
      w("Pour la prochaine", "For the next one"),
    ],
    examples: [
      {
        kind: "list",
        title: w("Ce qui est parti", "What shipped"),
        items: [
          w("12 pull requests fusionnées", "12 pull requests merged"),
          w("3 services touchés", "3 services touched"),
          w("1 migration de base de données", "1 database migration"),
        ],
      },
      {
        kind: "levels",
        title: w("Après la release", "After the release"),
        items: [
          { level: "high", text: w("Latence en hausse sur checkout, 20 min après", "Latency up on checkout, 20 min after") },
          { level: "medium", text: w("Incident ouvert sur auth-service", "Incident open on auth-service") },
          { level: "low", text: w("Aucun changement de configuration", "No configuration change") },
        ],
      },
    ],
    limits: [
      w(
        "Le lien entre une release et un incident reste une hypothèse, appuyée par les faits qu'il cite.",
        "The link between a release and an incident stays a hypothesis, backed by the facts it cites.",
      ),
    ],
  },

  "change-impact-analysis": {
    promise: w(
      "Mesurez la portée d'un changement avant de le lancer : services, données, équipes et processus métier touchés, et qui prévenir.",
      "Measure a change's reach before launching it: the services, data, teams and business processes it touches, and whom to warn.",
    ),
    problem: w(
      "Un changement anodin peut toucher un processus métier critique trois dépendances plus loin ; les bonnes personnes l'apprennent trop tard.",
      "A harmless-looking change can reach a critical business process three dependencies away; the right people learn it too late.",
    ),
    benefits: [
      {
        icon: "route",
        title: w("La portée complète", "The full reach"),
        body: w(
          "Ce qui est touché directement, puis à un, deux, trois pas.",
          "What is touched directly, then one, two, three steps away.",
        ),
      },
      {
        icon: "users",
        title: w("Qui prévenir", "Whom to warn"),
        body: w("Les responsables concernés, regroupés.", "The owners concerned, grouped."),
      },
      {
        icon: "target",
        title: w("L'impact métier", "The business impact"),
        body: w("Les capacités et processus métier atteints.", "The business capabilities and processes reached."),
      },
    ],
    does: w(
      "Il part du changement (prévu ou livré), identifie ce qu'il touche directement, suit ses dépendances dans votre environnement jusqu'aux processus métier, et dit qui prévenir et ce qui se passe déjà sur la zone.",
      "It starts from the change (planned or shipped), finds what it touches directly, follows its dependencies in your environment up to the business processes, and says whom to warn and what is already happening in the area.",
    ),
    features: [
      w("Le changement en une phrase", "The change in a sentence"),
      w("La portée en tableau : directe ou à combien de pas", "The reach in a table: direct or how many steps away"),
      w("La criticité et le responsable de chaque élément atteint", "The criticality and owner of everything reached"),
      w("Les capacités et processus métier touchés", "The business capabilities and processes touched"),
      w("Les personnes à prévenir, regroupées", "The people to warn, grouped"),
      w("Ce qui se passe déjà sur la zone", "What is already happening in the area"),
    ],
    useCases: [
      {
        icon: "route",
        title: w("Avant un changement prévu", "Before a planned change"),
        body: w("Voir jusqu'où il porte avant de le lancer.", "See how far it reaches before launching it."),
        ask: w("Quel est l'impact de la migration de la base clients ?", "What is the impact of migrating the customer database?"),
      },
      {
        icon: "git",
        title: w("Évaluer une pull request", "Assess a pull request"),
        body: w("La portée réelle d'un diff.", "A diff's real reach."),
        ask: w("Jusqu'où va l'impact de la PR #482 de acme/billing ?", "How far does acme/billing's PR #482 reach?"),
      },
      {
        icon: "users",
        title: w("Organiser la communication", "Organise the communication"),
        body: w("Prévenir les bonnes équipes, au bon moment.", "Warn the right teams, at the right time."),
        ask: w(
          "Qui faut-il prévenir avant de changer l'API de paiement ?",
          "Whom should we warn before changing the payment API?",
        ),
      },
      {
        icon: "clock",
        title: w("Choisir le bon moment", "Pick the right moment"),
        body: w("Éviter de lancer pendant un incident en cours.", "Avoid launching during an ongoing incident."),
        ask: w(
          "Y a-t-il un incident en cours sur ce que touche la migration de la base clients ?",
          "Is there an ongoing incident on what the customer database migration touches?",
        ),
      },
    ],
    outline: [
      w("Le changement", "The change"),
      w("La portée", "The reach"),
      w("Le métier", "The business"),
      w("Qui prévenir", "Whom to warn"),
      w("Le moment", "The moment"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "diagram",
        title: w("Portée d'un changement", "A change's reach"),
        items: [
          w("API paiement", "Payment API"),
          w("checkout", "checkout"),
          w("facturation", "billing"),
          w("Encaissement", "Collection"),
          w("base clients", "customer DB"),
        ],
      },
      {
        kind: "list",
        title: w("Qui prévenir", "Whom to warn"),
        items: [
          w("Équipe Paiements : responsable de l'API", "Payments team: owns the API"),
          w("Équipe Finance : processus d'encaissement", "Finance team: collection process"),
          w("Astreinte checkout", "Checkout on-call"),
        ],
      },
    ],
    limits: [
      w(
        "Une dépendance que vos sources ne montrent pas n'est pas vue : ce que le modèle ne couvre pas est dit.",
        "A dependency your sources do not show is not seen: what the model does not cover is said.",
      ),
    ],
  },

  "incident-investigation": {
    promise: w(
      "Reconstituez un incident : chronologie, impact, cause probable, et le brouillon du post-mortem.",
      "Piece an incident together: timeline, impact, likely cause, and the post-mortem draft.",
    ),
    problem: w(
      "Pendant et après un incident, reconstituer qui a changé quoi et quand mobilise plusieurs équipes pendant des heures.",
      "During and after an incident, piecing together who changed what and when ties up several teams for hours.",
    ),
    benefits: [
      {
        icon: "clock",
        title: w("La chronologie datée", "A dated timeline"),
        body: w("Chaque moment cité, avant et pendant l'incident.", "Every moment cited, before and during the incident."),
      },
      {
        icon: "search",
        title: w("La cause probable", "The likely cause"),
        body: w(
          "Avec sa confiance, ce qui l'appuie et ce qui la contredit.",
          "With its confidence, what supports it and what contradicts it.",
        ),
      },
      {
        icon: "file",
        title: w("Le post-mortem prêt", "The post-mortem ready"),
        body: w(
          "Résumé, chronologie, impact, cause et actions proposées.",
          "Summary, timeline, impact, cause and proposed actions.",
        ),
      },
    ],
    does: w(
      "Il rassemble ce qui s'est passé autour de l'incident (déploiements, changements, incidents liés), suit ce qui dépend des services touchés et propose une cause probable, avec un brouillon de post-mortem dont les actions ne sont jamais exécutées.",
      "It gathers what happened around the incident (deployments, changes, related incidents), follows what depends on the services hit and proposes a likely cause, with a post-mortem draft whose actions are never carried out.",
    ),
    features: [
      w("Une chronologie datée et citée", "A dated, cited timeline"),
      w("L'impact, direct et par ricochet", "The impact, direct and in turn"),
      w("La cause probable, avec sa confiance", "The likely cause, with its confidence"),
      w("Ce qui appuie et ce qui contredit chaque hypothèse", "What supports and contradicts each hypothesis"),
      w("Un brouillon de post-mortem", "A post-mortem draft"),
      w("Des actions proposées, jamais exécutées", "Actions proposed, never carried out"),
      w("Ce qu'il manque pour conclure", "What is missing to conclude"),
    ],
    useCases: [
      {
        icon: "alert",
        title: w("Comprendre un incident en cours", "Understand an ongoing incident"),
        body: w("Les faits, dans l'ordre, pendant que ça brûle.", "The facts, in order, while it burns."),
        ask: w("Pourquoi payment-api est-il plus lent depuis hier ?", "Why has payment-api been slower since yesterday?"),
      },
      {
        icon: "clock",
        title: w("Reconstituer la chronologie", "Rebuild the timeline"),
        body: w("Qui a changé quoi, et quand.", "Who changed what, and when."),
        ask: w(
          "Reconstitue la chronologie de l'incident de ce matin sur checkout",
          "Rebuild the timeline of this morning's checkout incident",
        ),
      },
      {
        icon: "file",
        title: w("Rédiger le post-mortem", "Write the post-mortem"),
        body: w("Un premier jet, prêt à compléter.", "A first draft, ready to complete."),
        ask: w(
          "Rédige le post-mortem de l'incident de ce matin sur checkout",
          "Draft the post-mortem of this morning's checkout incident",
        ),
      },
      {
        icon: "route",
        title: w("Mesurer l'impact", "Measure the impact"),
        body: w("Ce qui a été atteint, et par ricochet.", "What was reached, and in turn."),
        ask: w(
          "Quels services ont été touchés par l'incident sur auth-service ?",
          "Which services were hit by the auth-service incident?",
        ),
      },
    ],
    outline: [
      w("Chronologie", "Timeline"),
      w("Impact", "Impact"),
      w("Cause probable", "Likely cause"),
      w("Post-mortem (brouillon)", "Post-mortem (draft)"),
      w("Ce qui manque", "What is missing"),
    ],
    examples: [
      {
        kind: "list",
        title: w("Chronologie", "Timeline"),
        items: [
          w("09:02, déploiement de payment-api v2.8.4", "09:02, payment-api v2.8.4 deployed"),
          w("09:20, latence en hausse", "09:20, latency rising"),
          w("09:41, incident ouvert", "09:41, incident opened"),
          w("10:15, retour arrière", "10:15, rolled back"),
        ],
      },
      {
        kind: "levels",
        title: w("Hypothèses de cause", "Cause hypotheses"),
        items: [
          { level: "high", text: w("Déploiement de v2.8.4 : appuyé par la chronologie", "v2.8.4 deployment: backed by the timeline") },
          { level: "medium", text: w("Base partagée avec auth-service", "Database shared with auth-service") },
          { level: "low", text: w("Panne réseau : contredite par les sources", "Network outage: contradicted by the sources") },
        ],
      },
    ],
    limits: [
      w(
        "Sans métriques ni journaux connectés, la cause reste une hypothèse : il dit ce qui manquerait pour conclure.",
        "Without connected metrics or logs, the cause stays a hypothesis: it says what would be needed to conclude.",
      ),
    ],
  },

  "debug-assistant": {
    promise: w(
      "Un service se comporte mal ? Obtenez ses causes probables, classées, et les vérifications à faire dans l'ordre.",
      "A service misbehaving? Get its likely causes, ranked, and the checks to run in order.",
    ),
    problem: w(
      "Face à des erreurs ou des lenteurs, on perd du temps à vérifier des pistes au hasard.",
      "Faced with errors or slowness, time is lost checking leads at random.",
    ),
    benefits: [
      {
        icon: "bug",
        title: w("Des causes classées", "Causes ranked"),
        body: w("Chacune avec ce qui l'appuie et ce qui l'affaiblit.", "Each with what supports it and what weakens it."),
      },
      {
        icon: "list",
        title: w("Les vérifications dans l'ordre", "Checks in order"),
        body: w("Chacune avec ce qu'elle trancherait.", "Each with what it would settle."),
      },
      {
        icon: "shield",
        title: w("Aucun remède hasardeux", "No guesswork fix"),
        body: w("Un remède seulement pour une cause appuyée.", "A fix only for a supported cause."),
      },
    ],
    does: w(
      "Il regarde ce qui a changé récemment autour du service, ce dont il dépend et l'état de ces dépendances, puis classe les causes probables et les vérifications qui les départageront.",
      "It looks at what changed recently around the service, what it depends on and how those dependencies are doing, then ranks the likely causes and the checks that will tell them apart.",
    ),
    features: [
      w("Le symptôme reformulé, avec son périmètre", "The symptom restated, with its perimeter"),
      w("Les causes probables, classées", "The likely causes, ranked"),
      w("Ce qui appuie et ce qui affaiblit chaque cause", "What supports and weakens each cause"),
      w("Les vérifications à faire, dans l'ordre", "The checks to run, in order"),
      w("Un remède seulement pour une cause appuyée", "A fix only for a supported cause"),
      w("Les signaux qui manquent pour conclure", "The signals missing to conclude"),
    ],
    useCases: [
      {
        icon: "bug",
        title: w("Diagnostiquer des erreurs", "Diagnose errors"),
        body: w("Les causes d'une vague d'erreurs, classées.", "The causes of a wave of errors, ranked."),
        ask: w(
          "Pourquoi checkout renvoie-t-il des erreurs 500 depuis ce matin ?",
          "Why has checkout been returning 500 errors since this morning?",
        ),
      },
      {
        icon: "clock",
        title: w("Comprendre une lenteur", "Understand slowness"),
        body: w("Ce qui a changé quand c'est devenu lent.", "What changed when it got slow."),
        ask: w("Pourquoi payment-api est-il plus lent depuis hier ?", "Why has payment-api been slower since yesterday?"),
      },
      {
        icon: "route",
        title: w("Vérifier les dépendances", "Check the dependencies"),
        body: w("L'état de ce dont le service dépend.", "How what the service depends on is doing."),
        ask: w("Les dépendances de auth-service vont-elles bien ?", "Are auth-service's dependencies healthy?"),
      },
      {
        icon: "list",
        title: w("Prioriser les vérifications", "Prioritise the checks"),
        body: w("Par où commencer, et pourquoi.", "Where to start, and why."),
        ask: w(
          "Par quoi commencer pour comprendre les échecs de paiement ?",
          "Where should we start to understand the payment failures?",
        ),
      },
    ],
    outline: [
      w("Le symptôme", "The symptom"),
      w("Causes probables, classées", "Likely causes, ranked"),
      w("Vérifications à faire", "Checks to run"),
      w("Ce qui manque", "What is missing"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Causes probables, classées", "Likely causes, ranked"),
        items: [
          { level: "high", text: w("Un déploiement juste avant le premier signal", "A deployment just before the first signal") },
          { level: "medium", text: w("Une dépendance en incident", "A dependency in incident") },
          { level: "low", text: w("Un pic de trafic, non confirmé", "A traffic spike, unconfirmed") },
        ],
      },
      {
        kind: "list",
        title: w("Vérifications à faire", "Checks to run"),
        items: [
          w("Comparer avant et après le déploiement", "Compare before and after the deployment"),
          w("Vérifier l'état de auth-service", "Check auth-service's state"),
          w("Lire les journaux de checkout (non connectés)", "Read checkout's logs (not connected)"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne voit que les signaux de vos sources connectées : sans métriques ni journaux, il dit ce qui manque.",
        "It only sees the signals of your connected sources: without metrics or logs, it says what is missing.",
      ),
    ],
  },

  "build-fixer": {
    promise: w(
      "Votre build est cassé ? Obtenez la cause probable et le plus petit correctif : proposé, jamais appliqué sans vous.",
      "Your build is broken? Get the likely cause and the smallest fix: proposed, never applied without you.",
    ),
    problem: w(
      "Un pipeline rouge bloque toute l'équipe ; retrouver le changement fautif parmi les derniers commits prend du temps.",
      "A red pipeline blocks the whole team; finding the faulty change among the latest commits takes time.",
    ),
    benefits: [
      {
        icon: "zap",
        title: w("Le changement en cause", "The change at fault"),
        body: w("Le changement probable, cité.", "The likely change, cited."),
      },
      {
        icon: "git",
        title: w("Le plus petit correctif", "The smallest fix"),
        body: w("Retour arrière ou correction ciblée, avec ce qu'il risque.", "A revert or a targeted fix, with what it risks."),
      },
      {
        icon: "shield",
        title: w("Vous gardez la main", "You stay in control"),
        body: w(
          "Une proposition passe par une décision humaine, nommée et datée.",
          "A proposal goes through a human decision, named and dated.",
        ),
      },
    ],
    does: w(
      "Il regarde ce qui a changé juste avant la casse (derniers commits et pull requests), désigne le changement probable et propose le plus petit correctif, soumis à votre décision.",
      "It looks at what changed just before the break (latest commits and pull requests), points to the likely change and proposes the smallest fix, put to your decision.",
    ),
    features: [
      w("Ce qui a cassé, et quand", "What broke, and when"),
      w("Le commit ou la pull request probable, cité", "The likely commit or pull request, cited"),
      w("Le plus petit correctif : retour arrière ou correction", "The smallest fix: revert or correction"),
      w("Les risques du correctif", "The fix's risks"),
      w("Une proposition soumise à décision, jamais appliquée seule", "A proposal put to a decision, never applied alone"),
    ],
    useCases: [
      {
        icon: "alert",
        title: w("Pipeline rouge sur main", "Red pipeline on main"),
        body: w("Comprendre pourquoi, et quoi faire.", "Understand why, and what to do."),
        ask: w("Le build de main est cassé depuis ce matin, pourquoi ?", "The main build has been broken since this morning: why?"),
      },
      {
        icon: "git",
        title: w("Retrouver le commit fautif", "Find the faulty commit"),
        body: w("Le changement juste avant la casse.", "The change just before the break."),
        ask: w("Quel changement a cassé le build de payment-api ?", "Which change broke payment-api's build?"),
      },
      {
        icon: "route",
        title: w("Choisir entre retour arrière et correctif", "Choose between revert and fix"),
        body: w("Ce que chaque option risque.", "What each option risks."),
        ask: w(
          "Faut-il revenir sur la dernière PR de checkout pour réparer le build ?",
          "Should checkout's latest PR be reverted to fix the build?",
        ),
      },
      {
        icon: "rocket",
        title: w("Débloquer une release", "Unblock a release"),
        body: w("Le correctif le plus sûr pour repartir.", "The safest fix to get going again."),
        ask: w("Le pipeline de release est bloqué, que proposes-tu ?", "The release pipeline is stuck: what do you suggest?"),
      },
    ],
    outline: [
      w("Ce qui a cassé", "What broke"),
      w("Le changement probable", "The likely change"),
      w("Correctif proposé", "Proposed fix"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "list",
        title: w("Ce qui a cassé", "What broke"),
        items: [
          w("Build de main en échec depuis 09:12", "Main build failing since 09:12"),
          w("Juste avant : PR #482, mise à jour d'une dépendance", "Just before: PR #482, a dependency upgrade"),
          w("Aucun autre changement entre-temps", "No other change in between"),
        ],
      },
      {
        kind: "list",
        title: w("Correctif proposé", "Proposed fix"),
        items: [
          w("Revenir sur la PR #482", "Revert PR #482"),
          w("Risque : sa fonctionnalité est retirée", "Risk: its feature is withdrawn"),
          w("À décider par un mainteneur du dépôt", "To be decided by a repository maintainer"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne lit pas les journaux de build : sans eux, la cause reste une hypothèse, dite comme telle.",
        "It does not read build logs: without them, the cause stays a hypothesis, said as such.",
      ),
    ],
  },

  "security-review": {
    promise: w(
      "Sachez ce qui expose une application : sa surface, ses données sensibles, ce qui l'atteint, et quoi vérifier en premier.",
      "Know what exposes an application: its surface, its sensitive data, what reaches it, and what to check first.",
    ),
    problem: w(
      "Savoir si un système est exposé suppose de croiser architecture, données et infrastructure : rarement documentées ensemble.",
      "Knowing whether a system is exposed means cross-checking architecture, data and infrastructure: rarely documented together.",
    ),
    benefits: [
      {
        icon: "shield",
        title: w("Votre exposition, mesurée", "Your exposure, measured"),
        body: w("Surface, frontières et données sensibles.", "Surface, boundaries and sensitive data."),
      },
      {
        icon: "alert",
        title: w("Des constats priorisés", "Prioritised findings"),
        body: w(
          "Sévérité, confiance, scénario et ce qu'il faut vérifier pour corriger.",
          "Severity, confidence, scenario and what to check to fix it.",
        ),
      },
      {
        icon: "search",
        title: w("Les signaux faibles", "Weak signals"),
        body: w(
          "Sans responsable, non documenté, ressource partagée, dépendance externe critique.",
          "No owner, undocumented, shared resource, critical external dependency.",
        ),
      },
    ],
    does: w(
      "Il examine ce qu'un système porte et ce qui l'atteint (données, infrastructure, comptes cloud, dépendances, responsables) et rend des constats priorisés, en séparant ce qui est appuyé des hypothèses.",
      "It examines what a system holds and what reaches it (data, infrastructure, cloud accounts, dependencies, owners) and returns prioritised findings, keeping what is supported apart from hypotheses.",
    ),
    features: [
      w("Un état : complet, partiel ou non évalué", "A state: complete, partial or not assessed"),
      w("La surface : ce qui l'atteint et ce qu'il atteint", "The surface: what reaches it and what it reaches"),
      w("Les données sensibles stockées ou lues", "The sensitive data stored or read"),
      w("Des constats par sévérité, avec leur scénario", "Findings by severity, with their scenario"),
      w("Les hypothèses, séparées des constats", "Hypotheses, kept apart from findings"),
      w("Les signaux : sans responsable, non documenté, partagé", "Signals: no owner, undocumented, shared"),
    ],
    useCases: [
      {
        icon: "shield",
        title: w("Évaluer une application", "Assess an application"),
        body: w("Ce qui l'expose, et par où commencer.", "What exposes it, and where to start."),
        ask: w("payment-api est-il exposé ?", "Is payment-api exposed?"),
      },
      {
        icon: "database",
        title: w("Localiser les données sensibles", "Locate sensitive data"),
        body: w("Ce qu'un service stocke ou lit.", "What a service stores or reads."),
        ask: w("Quelles données sensibles porte le service clients ?", "What sensitive data does the customer service hold?"),
      },
      {
        icon: "search",
        title: w("Préparer un audit", "Prepare an audit"),
        body: w("Les vérifications prioritaires.", "The priority checks."),
        ask: w("Que vérifier en premier sur la sécurité de checkout ?", "What should be checked first on checkout's security?"),
      },
      {
        icon: "cloud",
        title: w("Contrôler l'infrastructure", "Check the infrastructure"),
        body: w("Ressources partagées et comptes cloud.", "Shared resources and cloud accounts."),
        ask: w(
          "Quelles ressources cloud de auth-service sont partagées ?",
          "Which of auth-service's cloud resources are shared?",
        ),
      },
    ],
    outline: [
      w("État", "State"),
      w("Surface", "Surface"),
      w("Données sensibles", "Sensitive data"),
      w("Constats", "Findings"),
      w("Hypothèses", "Hypotheses"),
      w("Signaux", "Signals"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats", "Findings"),
        items: [
          { level: "critical", text: w("Base clients atteinte par un service exposé", "Customer database reached by an exposed service") },
          { level: "high", text: w("Service sans responsable connu", "Service with no known owner") },
          { level: "medium", text: w("Dépendance externe non documentée", "Undocumented external dependency") },
          { level: "low", text: w("Ressource partagée entre environnements", "Resource shared across environments") },
        ],
      },
      {
        kind: "list",
        title: w("Hypothèses à vérifier", "Hypotheses to check"),
        items: [
          w("Chiffrement de la base : non dit par les sources", "Database encryption: not said by the sources"),
          w("Accès public à l'API d'administration : à confirmer", "Public access to the admin API: to confirm"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne scanne pas de vulnérabilités et ne lit pas le code : il dit ce que le modèle de votre environnement montre.",
        "It does not scan for vulnerabilities nor read the code: it says what the model of your environment shows.",
      ),
    ],
  },

  "infrastructure-analysis": {
    promise: w(
      "Voyez où tourne chaque service, ce qui est partagé et où sont vos points uniques de défaillance.",
      "See where each service runs, what is shared and where your single points of failure are.",
    ),
    problem: w(
      "Comptes, régions, ressources partagées : la carte réelle de l'infrastructure n'est souvent que dans la tête de quelques personnes.",
      "Accounts, regions, shared resources: the real map of the infrastructure often lives only in a few people's heads.",
    ),
    benefits: [
      {
        icon: "cloud",
        title: w("La carte de votre infrastructure", "Your infrastructure's map"),
        body: w(
          "Comptes, régions, environnements et ressources, service par service.",
          "Accounts, regions, environments and resources, service by service.",
        ),
      },
      {
        icon: "alert",
        title: w("Les points uniques de défaillance", "Single points of failure"),
        body: w("Ce qui, en tombant, emporte plusieurs services.", "What takes several services down when it fails."),
      },
      {
        icon: "search",
        title: w("Les ressources orphelines", "Orphan resources"),
        body: w("Les ressources sans service ni responsable connus.", "Resources with no known service or owner."),
      },
    ],
    does: w(
      "Il lit les ressources, comptes et groupes de ressources de vos clouds connectés (AWS, Azure, GCP) et les rattache aux services qui y tournent, pour montrer ce qui est partagé et ce qui est fragile.",
      "It reads the resources, accounts and resource groups of your connected clouds (AWS, Azure, GCP) and ties them to the services running on them, to show what is shared and what is fragile.",
    ),
    features: [
      w("Où ça tourne : comptes, régions, environnements", "Where it runs: accounts, regions, environments"),
      w("Les ressources partagées entre services", "Resources shared between services"),
      w("Les points uniques de défaillance", "Single points of failure"),
      w("Les ressources sans service ni responsable", "Resources with no service or owner"),
      w("Ce qui reste à vérifier, et par qui", "What remains to check, and by whom"),
      w("Une réponse citée, ressource par ressource", "A cited answer, resource by resource"),
    ],
    useCases: [
      {
        icon: "cloud",
        title: w("Cartographier un environnement", "Map an environment"),
        body: w("Où tourne un service, et sur quoi.", "Where a service runs, and on what."),
        ask: w("Où tourne payment-api en production ?", "Where does payment-api run in production?"),
      },
      {
        icon: "alert",
        title: w("Trouver les points uniques de défaillance", "Find single points of failure"),
        body: w("Ce qui ne doit pas tomber.", "What must not fail."),
        ask: w(
          "Quels sont les points uniques de défaillance de la production ?",
          "What are production's single points of failure?",
        ),
      },
      {
        icon: "search",
        title: w("Repérer les ressources orphelines", "Spot orphan resources"),
        body: w("Ce que plus personne ne revendique.", "What nobody claims any more."),
        ask: w("Quelles ressources AWS n'ont pas de responsable connu ?", "Which AWS resources have no known owner?"),
      },
      {
        icon: "layers",
        title: w("Préparer une migration", "Prepare a migration"),
        body: w("Ce qui est partagé, avant de déplacer.", "What is shared, before moving."),
        ask: w("Qu'est-ce qui est partagé entre checkout et facturation ?", "What is shared between checkout and billing?"),
      },
    ],
    outline: [
      w("Où ça tourne", "Where it runs"),
      w("Ce qui est partagé", "What is shared"),
      w("Points uniques de défaillance", "Single points of failure"),
      w("Écarts", "Gaps"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "diagram",
        title: w("Une ressource partagée", "A shared resource"),
        items: [
          w("base RDS prod", "prod RDS DB"),
          w("payment-api", "payment-api"),
          w("auth-service", "auth-service"),
          w("facturation", "billing"),
          w("reporting", "reporting"),
        ],
      },
      {
        kind: "levels",
        title: w("Points uniques de défaillance", "Single points of failure"),
        items: [
          { level: "critical", text: w("Une base porte quatre services", "One database carries four services") },
          { level: "high", text: w("Une seule passerelle réseau en production", "A single network gateway in production") },
          { level: "medium", text: w("File de messages sans réplique", "Message queue without a replica") },
        ],
      },
    ],
    limits: [
      w(
        "Il ne lit ni les coûts, ni les métriques en direct, ni les réglages internes des ressources.",
        "It reads neither costs, nor live metrics, nor resources' internal settings.",
      ),
    ],
  },

  "data-analysis": {
    promise: w(
      "Sachez où vivent vos données, qui les lit, qui les écrit et qui en est responsable.",
      "Know where your data lives, who reads it, who writes it and who owns it.",
    ),
    problem: w(
      "Une donnée personnelle, une table critique : savoir où elle est et qui l'utilise demande souvent d'interroger plusieurs équipes.",
      "Personal data, a critical table: knowing where it is and who uses it often means asking several teams.",
    ),
    benefits: [
      {
        icon: "database",
        title: w("Une carte de vos données", "A map of your data"),
        body: w("Bases, schémas et objets, en un seul endroit.", "Databases, schemas and objects, in one place."),
      },
      {
        icon: "route",
        title: w("Le lignage", "The lineage"),
        body: w(
          "D'où vient la donnée, où elle va, quelles applications la lisent ou l'écrivent.",
          "Where data comes from, where it goes, which applications read or write it.",
        ),
      },
      {
        icon: "users",
        title: w("Les responsables", "The owners"),
        body: w("Qui répond de chaque donnée, et ce qui n'a pas de responsable.", "Who answers for each piece of data, and what has no owner."),
      },
    ],
    does: w(
      "Il lit la structure de vos bases connectées et le modèle de votre environnement pour dire où vit une donnée, son lignage, les applications qui l'utilisent et leurs responsables.",
      "It reads the structure of your connected databases and the model of your environment to say where data lives, its lineage, the applications that use it and their owners.",
    ),
    features: [
      w("Où vit la donnée : base, schéma, objets", "Where data lives: database, schema, objects"),
      w("Les applications qui la lisent ou l'écrivent", "The applications that read or write it"),
      w("Son lignage : d'où elle vient, où elle va", "Its lineage: where it comes from, where it goes"),
      w("Ses responsables, et ce qui n'en a pas", "Its owners, and what has none"),
      w("Une réponse citée, objet par objet", "A cited answer, object by object"),
      w("Ce qui reste à vérifier, et par qui", "What remains to check, and by whom"),
    ],
    useCases: [
      {
        icon: "search",
        title: w("Localiser des données personnelles", "Locate personal data"),
        body: w("Où elles sont stockées, et qui y accède.", "Where it is stored, and who accesses it."),
        ask: w(
          "Quelles bases de données contiennent des données personnelles ?",
          "Which databases hold personal data?",
        ),
      },
      {
        icon: "route",
        title: w("Suivre le lignage d'une table", "Trace a table's lineage"),
        body: w("D'où elle est alimentée, qui la consomme.", "What feeds it, who consumes it."),
        ask: w(
          "D'où viennent les données de la table orders et qui les lit ?",
          "Where does the orders table's data come from and who reads it?",
        ),
      },
      {
        icon: "users",
        title: w("Trouver un responsable", "Find an owner"),
        body: w("Qui répond d'une base.", "Who answers for a database."),
        ask: w("Qui est responsable de la base clients ?", "Who owns the customer database?"),
      },
      {
        icon: "shield",
        title: w("Préparer une revue RGPD", "Prepare a GDPR review"),
        body: w("Ce que chaque application écrit, avant un audit.", "What each application writes, before an audit."),
        ask: w("Quelles applications écrivent dans la base clients ?", "Which applications write to the customer database?"),
      },
    ],
    outline: [
      w("Où vit la donnée", "Where the data lives"),
      w("Qui l'utilise", "Who uses it"),
      w("D'où elle vient, où elle va", "Where it comes from, where it goes"),
      w("Responsables", "Owners"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "diagram",
        title: w("Le lignage d'une table", "A table's lineage"),
        items: [
          w("orders", "orders"),
          w("checkout", "checkout"),
          w("facturation", "billing"),
          w("entrepôt", "warehouse"),
          w("reporting", "reporting"),
        ],
      },
      {
        kind: "list",
        title: w("Qui utilise la base clients", "Who uses the customer database"),
        items: [
          w("checkout : lecture et écriture", "checkout: read and write"),
          w("crm-sync : lecture", "crm-sync: read"),
          w("facturation : lecture", "billing: read"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit la structure des bases, jamais le contenu des tables ; ni les index, ni les requêtes, ni les volumes.",
        "It reads the databases' structure, never the tables' content; nor indexes, queries or volumes.",
      ),
    ],
  },

  "documentation-assistant": {
    promise: w(
      "Sachez ce qui est documenté, ce qui manque ou a vieilli, et obtenez le brouillon de la page qui manque le plus.",
      "Know what is documented, what is missing or out of date, and get a draft of the page most missing.",
    ),
    problem: w(
      "La documentation se périme sans que personne ne le voie ; les trous apparaissent au pire moment.",
      "Documentation goes stale without anyone noticing; the gaps show up at the worst moment.",
    ),
    benefits: [
      {
        icon: "book",
        title: w("Une carte de votre documentation", "A map of your documentation"),
        body: w(
          "Ce qui existe, où, de quand, et le besoin que chaque document couvre.",
          "What exists, where, from when, and the need each document covers.",
        ),
      },
      {
        icon: "alert",
        title: w("Les trous critiques", "The critical gaps"),
        body: w("Ce qui manque ou a vieilli, les plus graves d'abord.", "What is missing or stale, the worst first."),
      },
      {
        icon: "file",
        title: w("Un brouillon prêt à compléter", "A draft ready to complete"),
        body: w(
          "Chaque phrase appuyée par une citation, les manques signalés « À compléter ».",
          "Every sentence backed by a citation, the gaps marked « To complete ».",
        ),
      },
    ],
    does: w(
      "Il parcourt les documents et espaces qui parlent d'un système, mesure leur fraîcheur, les compare à ce que LEKA sait de votre environnement et rédige le brouillon de la page qui manque le plus.",
      "It goes through the documents and spaces about a system, measures how fresh they are, compares them with what LEKA knows of your environment and drafts the page most missing.",
    ),
    features: [
      w("La carte de couverture documentaire", "The documentation coverage map"),
      w("Les documents périmés ou manquants", "Stale or missing documents"),
      w("Les écarts entre la documentation et votre environnement", "Gaps between the documentation and your environment"),
      w("Un brouillon de page, chaque phrase citée", "A page draft, every sentence cited"),
      w("Les manques signalés « À compléter »", "Gaps marked « To complete »"),
      w("Les experts qui peuvent compléter", "The experts who can complete it"),
    ],
    useCases: [
      {
        icon: "book",
        title: w("Faire l'état de la documentation", "Take stock of the documentation"),
        body: w("Ce qui est à jour, ce qui ne l'est plus.", "What is up to date, what no longer is."),
        ask: w("La documentation de payment-api est-elle à jour ?", "Is payment-api's documentation up to date?"),
      },
      {
        icon: "file",
        title: w("Rédiger une page manquante", "Write a missing page"),
        body: w("Un premier jet appuyé sur vos sources.", "A first draft backed by your sources."),
        ask: w(
          "Rédige un premier jet de la documentation de auth-service",
          "Draft a first version of auth-service's documentation",
        ),
      },
      {
        icon: "search",
        title: w("Trouver une procédure", "Find a procedure"),
        body: w("Où elle est écrite, et de quand elle date.", "Where it is written, and how old it is."),
        ask: w("Où est documentée la procédure de déploiement ?", "Where is the deployment procedure documented?"),
      },
      {
        icon: "users",
        title: w("Savoir qui peut compléter", "Know who can complete it"),
        body: w("Les experts connus d'un système.", "A system's known experts."),
        ask: w(
          "Qui peut compléter la documentation du service de facturation ?",
          "Who can complete the billing service's documentation?",
        ),
      },
    ],
    outline: [
      w("Ce qui existe", "What exists"),
      w("Ce qui manque ou a vieilli", "What is missing or stale"),
      w("Brouillon", "Draft"),
      w("Qui peut compléter", "Who can complete it"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Ce qui manque ou a vieilli", "What is missing or stale"),
        items: [
          { level: "critical", text: w("Aucune procédure de reprise documentée", "No recovery procedure documented") },
          { level: "high", text: w("Schéma d'architecture vieux de deux ans", "Architecture diagram two years old") },
          { level: "medium", text: w("Runbook sans responsable", "Runbook with no owner") },
          { level: "low", text: w("Glossaire incomplet", "Incomplete glossary") },
        ],
      },
      {
        kind: "list",
        title: w("Le brouillon", "The draft"),
        items: [
          w("Rôle du service : cité", "The service's role: cited"),
          w("Dépendances : citées", "Dependencies: cited"),
          w("Procédure de reprise : À compléter", "Recovery procedure: To complete"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne publie rien dans vos outils : le brouillon reste dans LEKA, à relire avant de le reprendre.",
        "It publishes nothing to your tools: the draft stays in LEKA, to review before reusing it.",
      ),
    ],
  },
};
