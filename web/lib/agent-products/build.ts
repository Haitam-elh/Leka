import { type AgentProduct, w } from "@/lib/agent-products/types";

/** Architecture, code and tests: what is built, and how it is checked. */
export const BUILD: Record<string, AgentProduct> = {
  "application-architecture": {
    promise: w(
      "Le dossier d'architecture d'un parcours métier, prêt à présenter : couche métier, couche applicative, règles de gestion et RACI — construit uniquement depuis votre documentation.",
      "The architecture deck of a business journey, ready to present: business layer, application layer, business rules and RACI — built only from your documentation.",
    ),
    problem: w(
      "Documenter l'architecture d'un parcours demande des semaines d'entretiens et de recherches dans la documentation, les tickets et le code — et le résultat vieillit vite.",
      "Documenting a journey's architecture takes weeks of interviews and digging through documentation, tickets and code — and the result ages fast.",
    ),
    benefits: [
      {
        icon: "zap",
        title: w("Le dossier construit pour vous", "The deck built for you"),
        body: w(
          "Le deck se construit depuis vos espaces documentaires, vos tickets, votre code et vos bases déjà connectés.",
          "The deck is built from your documentation spaces, tickets, code and databases already connected.",
        ),
      },
      {
        icon: "shield",
        title: w("Rien d'inventé", "Nothing made up"),
        body: w(
          "Ce que la documentation ne dit pas apparaît en orange, à confirmer, et la dernière page liste les sources consultées.",
          "What the documentation does not say shows in orange, to be confirmed, and the last page lists the sources read.",
        ),
      },
      {
        icon: "users",
        title: w("Un support pour décider", "Material to decide on"),
        body: w(
          "Processus, applications, règles de gestion et responsabilités réunis : de quoi aligner le métier et la DSI.",
          "Processes, applications, business rules and responsibilities together: enough to align business and IT.",
        ),
      },
    ],
    does: w(
      "Vous nommez un parcours et son périmètre ; l'Architecte applicatif cherche ce que vos sources en disent et produit un deck PowerPoint et sa version PDF : le parcours en clair, ses règles, une page par sous-processus avec la couche métier et la couche applicative, le RACI et les points à confirmer.",
      "You name a journey and its perimeter; the Application architect looks for what your sources say about it and produces a PowerPoint deck and its PDF: the journey in plain words, its rules, a page per sub-process with the business and application layers, the RACI and the points to confirm.",
    ),
    features: [
      w("Le parcours expliqué en clair, sur une page", "The journey in plain words, on one page"),
      w("Les règles de gestion du parcours, citées", "The journey's business rules, cited"),
      w("Une page par sous-processus, couche métier en ArchiMate 3.0.1", "A page per sub-process, business layer in ArchiMate 3.0.1"),
      w("La couche applicative en diagrammes de séquence", "The application layer as sequence diagrams"),
      w("La matrice RACI des acteurs", "The actors' RACI matrix"),
      w("Les points à confirmer signalés en orange", "Points to confirm shown in orange"),
      w("Les sources consultées et les limites, en dernière page", "Sources read and limits, on the last page"),
      w("En option, la vue applicative et le catalogue des flux", "Optionally, the application view and the flow catalogue"),
    ],
    useCases: [
      {
        icon: "map",
        title: w("Documenter un parcours existant", "Document an existing journey"),
        body: w(
          "Paiement, souscription, facturation : le dossier d'un parcours que personne n'a jamais formalisé.",
          "Payment, subscription, billing: the deck of a journey nobody ever wrote down.",
        ),
        ask: w(
          "Construis l'architecture du parcours Paiement CB sur le périmètre Digital",
          "Build the architecture of the card payment journey on the Digital perimeter",
        ),
      },
      {
        icon: "users",
        title: w("Préparer un comité d'architecture", "Prepare an architecture board"),
        body: w(
          "Arriver avec un support clair : processus, applications, règles et responsabilités.",
          "Come with clear material: processes, applications, rules and responsibilities.",
        ),
        ask: w(
          "Architecture applicative du parcours de facturation",
          "Application architecture of the billing journey",
        ),
      },
      {
        icon: "rocket",
        title: w("Cadrer une évolution", "Frame a change"),
        body: w(
          "Avant de transformer un parcours, voir ce qu'il traverse et ce qui reste à confirmer.",
          "Before reshaping a journey, see what it goes through and what remains to confirm.",
        ),
        ask: w(
          "Architecture du parcours de souscription en ligne, avec la vue applicative",
          "Architecture of the online subscription journey, with the application view",
        ),
      },
      {
        icon: "search",
        title: w("Repérer ce qui n'est pas documenté", "Spot what is undocumented"),
        body: w(
          "Les éléments en orange montrent ce que vos sources ne disent pas : votre liste de points à confirmer.",
          "The orange items show what your sources do not say: your list of points to confirm.",
        ),
        ask: w(
          "Construis l'architecture du parcours de résiliation sur le périmètre Espace client",
          "Build the architecture of the cancellation journey on the Customer area perimeter",
        ),
      },
    ],
    outline: [
      w("Page de titre et sommaire", "Title page and contents"),
      w("Le parcours en clair", "The journey in plain words"),
      w("Règles de gestion", "Business rules"),
      w("Une page par sous-processus", "A page per sub-process"),
      w("RACI", "RACI"),
      w("Points de contrôle à confirmer", "Checkpoints to confirm"),
      w("Sources consultées et limites", "Sources read and limits"),
    ],
    examples: [
      {
        kind: "diagram",
        title: w("Cartographie d'un sous-processus", "A sub-process mapped"),
        items: [
          w("Autorisation", "Authorisation"),
          w("Client", "Customer"),
          w("Saisie carte", "Card entry"),
          w("Banque", "Bank"),
          w("Confirmation", "Confirmation"),
        ],
      },
      {
        kind: "list",
        title: w("Points à confirmer", "Points to confirm"),
        items: [
          w("Plafond de paiement : règle non documentée", "Payment ceiling: rule not documented"),
          w("Flux de remboursement : responsable inconnu", "Refund flow: owner unknown"),
          w("Version de l'API d'autorisation à confirmer", "Authorisation API version to confirm"),
          w("Canal mobile : absent des sources", "Mobile channel: missing from the sources"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne décrit que ce que vos sources documentent : un parcours peu documenté donne un deck avec beaucoup de points à confirmer.",
        "It only describes what your sources document: a poorly documented journey gives a deck with many points to confirm.",
      ),
    ],
  },

  "architecture-analysis": {
    promise: w(
      "Comprenez de quoi est fait un service, ce dont il dépend et où il est fragile — sans monter de dossier.",
      "Understand what a service is made of, what it depends on and where it is fragile — without building a deck.",
    ),
    problem: w(
      "Avant de toucher à un système, il faut savoir ce qu'il contient et qui en dépend ; cette connaissance est éparpillée entre les équipes.",
      "Before touching a system you need to know what it holds and what depends on it; that knowledge is scattered across teams.",
    ),
    benefits: [
      {
        icon: "map",
        title: w("Une vue d'ensemble sur une page", "An overview on one page"),
        body: w(
          "Composants, responsables et dépendances, résumés sur une page.",
          "Components, owners and dependencies, summed up on one page.",
        ),
      },
      {
        icon: "alert",
        title: w("Les fragilités mises au jour", "Weak points brought to light"),
        body: w(
          "Les points de fragilité et le rayon d'impact du plus grave, avec les liens qui les montrent.",
          "The weak points and the blast radius of the worst, with the links that show them.",
        ),
      },
      {
        icon: "target",
        title: w("Des pistes concrètes", "Concrete options"),
        body: w("Au plus trois pistes, chacune avec son compromis.", "At most three options, each with its trade-off."),
      },
    ],
    does: w(
      "Il part de l'application ou du service que vous nommez, suit ses dépendances amont et aval dans le modèle de votre environnement que LEKA construit, et rend une analyse structurée dont chaque affirmation cite sa source.",
      "It starts from the application or service you name, follows its upstream and downstream dependencies in the model of your environment LEKA builds, and returns a structured analysis in which every statement cites its source.",
    ),
    features: [
      w("Le système résumé en trois phrases", "The system summed up in three sentences"),
      w("Chaque composant, son rôle et son responsable connu", "Each component, its role and its known owner"),
      w("Les dépendances amont et aval, les plus critiques d'abord", "Upstream and downstream dependencies, most critical first"),
      w("Les points de fragilité et leur rayon d'impact", "Weak points and their blast radius"),
      w("Au plus trois pistes, avec leur compromis", "At most three options, with their trade-offs"),
      w("Ce que le modèle ne dit pas encore", "What the model does not say yet"),
    ],
    useCases: [
      {
        icon: "search",
        title: w("Comprendre un service hérité", "Understand an inherited service"),
        body: w(
          "Savoir ce qu'est un système que personne n'a documenté.",
          "Learn what a system nobody documented is.",
        ),
        ask: w("Explique-moi l'architecture de payment-api", "Explain the architecture of payment-api to me"),
      },
      {
        icon: "alert",
        title: w("Trouver les points de fragilité", "Find the weak points"),
        body: w(
          "Repérer ce qui, en tombant, en emporte d'autres.",
          "Spot what takes others down when it fails.",
        ),
        ask: w("Où sont les points de fragilité de checkout-service ?", "Where are checkout-service's weak points?"),
      },
      {
        icon: "users",
        title: w("Transmettre un système", "Hand a system over"),
        body: w(
          "Donner à une nouvelle équipe la carte d'un système et ses responsables.",
          "Give a new team a system's map and its owners.",
        ),
        ask: w(
          "De quoi est fait le service de facturation et qui en est responsable ?",
          "What is the billing service made of and who owns it?",
        ),
      },
      {
        icon: "route",
        title: w("Anticiper une évolution", "Anticipate a change"),
        body: w(
          "Savoir ce qui dépend d'un service avant de le modifier.",
          "Know what depends on a service before changing it.",
        ),
        ask: w("Qu'est-ce qui dépend de auth-service ?", "What depends on auth-service?"),
      },
    ],
    outline: [
      w("En bref", "In short"),
      w("Composants", "Components"),
      w("Dépendances", "Dependencies"),
      w("Points de fragilité", "Weak points"),
      w("Pistes", "Options"),
      w("Ce qui manque", "What is missing"),
    ],
    examples: [
      {
        kind: "diagram",
        title: w("Dépendances d'un service", "A service's dependencies"),
        items: [
          w("payment-api", "payment-api"),
          w("auth-service", "auth-service"),
          w("base clients", "customer DB"),
          w("checkout", "checkout"),
          w("facturation", "billing"),
        ],
      },
      {
        kind: "levels",
        title: w("Points de fragilité", "Weak points"),
        items: [
          { level: "critical", text: w("Une base partagée par trois services", "One database shared by three services") },
          { level: "high", text: w("Un composant sans responsable connu", "A component with no known owner") },
          { level: "medium", text: w("Une dépendance externe non documentée", "An undocumented external dependency") },
          { level: "low", text: w("Un lien non vérifié vers le cache", "An unverified link to the cache") },
        ],
      },
    ],
    limits: [
      w(
        "Il ne voit que les liens que vos sources montrent : un lien absent du modèle est signalé comme manquant.",
        "It only sees the links your sources show: a link missing from the model is reported as missing.",
      ),
    ],
  },

  "codebase-explorer": {
    promise: w(
      "Trouvez votre chemin dans n'importe quel dépôt : son organisation, ses points d'entrée, où vit une fonctionnalité et comment le lancer.",
      "Find your way in any repository: how it is organised, its entry points, where a feature lives and how to run it.",
    ),
    problem: w(
      "Arriver sur un dépôt inconnu, c'est des heures à parcourir des dossiers avant de savoir où modifier sans casser.",
      "Landing on an unknown repository means hours of browsing folders before knowing where to change things without breaking them.",
    ),
    benefits: [
      {
        icon: "zap",
        title: w("Une prise en main guidée", "A guided start"),
        body: w(
          "La carte du dépôt et ses commandes, lues dans ses propres fichiers.",
          "The repository's map and commands, read from its own files.",
        ),
      },
      {
        icon: "target",
        title: w("La réponse exacte", "The exact answer"),
        body: w(
          "Une question précise mène au fichier, à la fonction, à la ligne.",
          "A precise question leads to the file, the function, the line.",
        ),
      },
      {
        icon: "book",
        title: w("Toujours cité", "Always cited"),
        body: w(
          "Chaque affirmation renvoie au fichier qui la montre.",
          "Every statement points to the file that shows it.",
        ),
      },
    ],
    does: w(
      "Il lit l'arborescence de votre dépôt GitHub et ses fichiers déclaratifs — README, manifestes, build, intégration continue —, repère ses points d'entrée et suit votre question jusqu'à l'endroit exact du code.",
      "It reads your GitHub repository's tree and declarative files — README, manifests, build, continuous integration —, finds its entry points and follows your question to the exact place in the code.",
    ),
    features: [
      w("Ce que fait le dépôt, en une phrase", "What the repository does, in a sentence"),
      w("La carte des dossiers qui comptent", "The map of the folders that matter"),
      w("Langages, frameworks et dépendances déclarés", "Declared languages, frameworks and dependencies"),
      w("Les points d'entrée et le chemin d'une requête", "Entry points and the path of a request"),
      w("Les commandes pour construire, lancer et tester", "The commands to build, run and test"),
      w("L'endroit exact d'une fonctionnalité : fichier, fonction, ligne", "Where a feature lives: file, function, line"),
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Accueillir un nouveau développeur", "Onboard a new developer"),
        body: w("Lui donner la carte du dépôt dès le premier jour.", "Give them the repository's map on day one."),
        ask: w("Comment est organisé le dépôt acme/billing ?", "How is the acme/billing repository organised?"),
      },
      {
        icon: "search",
        title: w("Trouver où vit une fonctionnalité", "Find where a feature lives"),
        body: w("Aller droit au fichier et à la fonction.", "Go straight to the file and the function."),
        ask: w("Où est calculée la TVA dans acme/billing ?", "Where is VAT computed in acme/billing?"),
      },
      {
        icon: "code",
        title: w("Suivre le chemin d'une requête", "Follow a request's path"),
        body: w("De l'entrée jusqu'aux données, étape par étape.", "From the entry point to the data, step by step."),
        ask: w(
          "Quel chemin suit une requête de paiement dans acme/checkout ?",
          "What path does a payment request take in acme/checkout?",
        ),
      },
      {
        icon: "flask",
        title: w("Savoir lancer et tester un projet", "Learn to run and test a project"),
        body: w("Les commandes du dépôt, telles qu'il les écrit.", "The repository's commands, as it writes them."),
        ask: w("Comment lancer les tests de acme/api ?", "How do I run acme/api's tests?"),
      },
    ],
    outline: [
      w("En une phrase", "In a sentence"),
      w("La carte", "The map"),
      w("Points d'entrée et chemin d'une requête", "Entry points and a request's path"),
      w("Construire, lancer, tester", "Build, run, test"),
      w("La réponse à la question", "The answer to the question"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "list",
        title: w("La carte d'un dépôt", "A repository's map"),
        items: [
          w("api/ — le serveur et ses routes", "api/ — the server and its routes"),
          w("web/ — l'application et ses écrans", "web/ — the application and its screens"),
          w("tests/ — les tests automatisés", "tests/ — the automated tests"),
          w("infra/ — le déploiement", "infra/ — the deployment"),
        ],
      },
      {
        kind: "list",
        title: w("Construire, lancer, tester", "Build, run, test"),
        items: [
          w("Installer : npm ci", "Install: npm ci"),
          w("Lancer : npm run dev", "Run: npm run dev"),
          w("Tester : npm test", "Test: npm test"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit les dépôts GitHub connectés ; un fichier trop long n'est lu qu'en partie, et ce qui n'a pas été lu n'est pas décrit.",
        "It reads connected GitHub repositories; a file too long is read in part, and what was not read is not described.",
      ),
    ],
  },

  "code-review": {
    promise: w(
      "Une revue de chaque pull request : ce qu'elle touche, ce qu'elle risque et qui devrait la relire — commentée ligne par ligne.",
      "A review of every pull request: what it touches, what it risks and who should review it — commented line by line.",
    ),
    problem: w(
      "Les relecteurs manquent de temps et de contexte : une pull request qui touche un service critique peut passer sans que les bonnes personnes la voient.",
      "Reviewers lack time and context: a pull request touching a critical service can go through without the right people seeing it.",
    ),
    benefits: [
      {
        icon: "shield",
        title: w("Les risques repérés", "Risks spotted"),
        body: w(
          "Des constats classés par sévérité et confiance, chacun appuyé par ce qu'il cite.",
          "Findings ranked by severity and confidence, each backed by what it cites.",
        ),
      },
      {
        icon: "users",
        title: w("Les bons relecteurs", "The right reviewers"),
        body: w(
          "Proposés d'après les responsables et contributeurs connus.",
          "Suggested from the known owners and contributors.",
        ),
      },
      {
        icon: "git",
        title: w("Commenté sur le diff", "Commented on the diff"),
        body: w(
          "Sur GitHub, chaque commentaire s'affiche sur sa ligne, avec le code proposé.",
          "On GitHub, every comment shows on its line, with the suggested code.",
        ),
      },
    ],
    does: w(
      "Il lit la pull request, sa description et son diff, regarde les services qu'elle porte et leurs responsables, et rend un avis argumenté — un avis, jamais une décision : la pull request reste à ses relecteurs.",
      "It reads the pull request, its description and its diff, looks at the services it carries and their owners, and gives a reasoned opinion — an opinion, never a decision: the pull request stays with its reviewers.",
    ),
    features: [
      w("Ce que fait le changement, en une phrase", "What the change does, in a sentence"),
      w("Ce qu'il touche : services, dépôts, équipes", "What it touches: services, repositories, teams"),
      w("Des constats par sévérité et confiance", "Findings by severity and confidence"),
      w("Un avis : favorable, prudence ou à revoir", "An opinion: favourable, caution or to rework"),
      w("Qui devrait relire", "Who should review"),
      w("Des commentaires sur les lignes du diff (GitHub)", "Comments on the diff's lines (GitHub)"),
      w("Ce qui est bien fait, à garder", "What is done well, to keep"),
    ],
    useCases: [
      {
        icon: "git",
        title: w("Relire la dernière pull request", "Review the latest pull request"),
        body: w("Un premier avis avant la relecture humaine.", "A first opinion before the human review."),
        ask: w("Fais la revue de la dernière PR de payment-api", "Review payment-api's latest PR"),
      },
      {
        icon: "alert",
        title: w("Mesurer le risque d'un changement", "Weigh a change's risk"),
        body: w("Savoir ce qu'un changement met en jeu.", "Know what a change puts at stake."),
        ask: w("Qu'est-ce que ce changement sur checkout risque ?", "What does this change to checkout risk?"),
      },
      {
        icon: "users",
        title: w("Trouver les bons relecteurs", "Find the right reviewers"),
        body: w("Les personnes qui connaissent ce que la PR touche.", "The people who know what the PR touches."),
        ask: w("Qui devrait relire la PR #412 de payment-api ?", "Who should review payment-api's PR #412?"),
      },
      {
        icon: "check",
        title: w("Vérifier avant de fusionner", "Check before merging"),
        body: w("Un dernier regard sur ce qui part.", "A last look at what ships."),
        ask: w("La PR #273 de acme/api peut-elle être fusionnée ?", "Can acme/api's PR #273 be merged?"),
      },
    ],
    outline: [
      w("Ce que fait le changement", "What the change does"),
      w("Ce qu'il touche", "What it touches"),
      w("Constats", "Findings"),
      w("Avis", "Opinion"),
      w("Qui devrait relire", "Who should review"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats d'une revue", "A review's findings"),
        items: [
          { level: "critical", text: w("Requête SQL construite par concaténation", "SQL query built by concatenation") },
          { level: "high", text: w("Erreur avalée sans journalisation", "Error swallowed without logging") },
          { level: "medium", text: w("Pas de test pour le cas limite", "No test for the edge case") },
          { level: "low", text: w("Nom de variable ambigu", "Ambiguous variable name") },
        ],
      },
      {
        kind: "list",
        title: w("Avis et relecteurs", "Opinion and reviewers"),
        items: [
          w("Avis : prudence — un constat élevé", "Opinion: caution — one high finding"),
          w("Relecteurs proposés : l'équipe Paiements", "Suggested reviewers: the Payments team"),
          w("À garder : la validation des entrées", "To keep: the input validation"),
        ],
      },
    ],
    limits: [
      w(
        "Sur GitLab ou Bitbucket, il juge ce que les sources disent du changement : le diff n'y est pas lu ligne à ligne.",
        "On GitLab or Bitbucket, it judges what the sources say of the change: the diff is not read line by line there.",
      ),
    ],
  },

  "code-change": {
    promise: w(
      "Décrivez la modification : LEKA lit le code, propose le diff et n'ouvre la pull request qu'une fois que vous l'acceptez.",
      "Describe the change: LEKA reads the code, proposes the diff and opens the pull request only once you accept it.",
    ),
    problem: w(
      "Les petites corrections s'accumulent faute de temps pour lire le code, écrire le changement et l'expliquer.",
      "Small fixes pile up for lack of time to read the code, write the change and explain it.",
    ),
    benefits: [
      {
        icon: "zap",
        title: w("Du besoin au diff", "From need to diff"),
        body: w(
          "La plus petite modification qui répond à la demande, dans le style du code existant.",
          "The smallest change that answers the request, in the existing code's style.",
        ),
      },
      {
        icon: "eye",
        title: w("Relu par vous", "Reviewed by you"),
        body: w(
          "Le diff est présenté à une personne qui décide : rien n'est poussé sans son accord.",
          "The diff is shown to a person who decides: nothing is pushed without their consent.",
        ),
      },
      {
        icon: "check",
        title: w("Testée et expliquée", "Tested and explained"),
        body: w(
          "Un test ajouté ou adapté quand le dépôt en a, et les étapes pour vérifier.",
          "A test added or adapted when the repository has some, and the steps to check.",
        ),
      },
    ],
    does: w(
      "Il lit en entier les fichiers à modifier et ce dont ils dépendent, propose la modification fichier par fichier ; LEKA en calcule le diff et le présente à une personne : la pull request ne s'ouvre que si elle l'accepte.",
      "It reads in full the files to change and what they depend on, proposes the change file by file; LEKA computes the diff and shows it to a person: the pull request opens only if they accept it.",
    ),
    features: [
      w("Le problème situé dans le code, cité", "The problem located in the code, cited"),
      w("La modification, fichier par fichier, expliquée", "The change, file by file, explained"),
      w("La plus petite modification qui répond à la demande", "The smallest change that answers the request"),
      w("Le style du code existant respecté", "The existing code's style respected"),
      w("Un test ajouté ou adapté quand le dépôt en a", "A test added or adapted when the repository has some"),
      w("Les risques et comment tester", "The risks and how to test"),
      w("Une pull request ouverte seulement après acceptation", "A pull request opened only once accepted"),
    ],
    useCases: [
      {
        icon: "bug",
        title: w("Corriger un bug identifié", "Fix a known bug"),
        body: w("Le correctif, son test et ses risques.", "The fix, its test and its risks."),
        ask: w("Corrige l'arrondi des montants dans acme/billing", "Fix the rounding of amounts in acme/billing"),
      },
      {
        icon: "code",
        title: w("Faire une petite évolution", "Make a small improvement"),
        body: w("Une évolution ciblée, prête à relire.", "A targeted change, ready to review."),
        ask: w(
          "Ajoute la pagination à la liste des factures de acme/billing",
          "Add pagination to the invoice list in acme/billing",
        ),
      },
      {
        icon: "sparkles",
        title: w("Améliorer un message", "Improve a message"),
        body: w("Des textes plus clairs pour vos utilisateurs.", "Clearer words for your users."),
        ask: w(
          "Rends le message d'erreur de connexion plus clair dans acme/web",
          "Make the sign-in error message clearer in acme/web",
        ),
      },
      {
        icon: "shield",
        title: w("Ajouter une validation", "Add a validation"),
        body: w("Refuser ce qui ne devrait jamais passer.", "Refuse what should never get through."),
        ask: w(
          "Refuse les montants négatifs dans l'API de paiement de acme/api",
          "Refuse negative amounts in acme/api's payment API",
        ),
      },
    ],
    outline: [
      w("Le problème", "The problem"),
      w("La modification, fichier par fichier", "The change, file by file"),
      w("Les risques", "The risks"),
      w("Comment tester", "How to test"),
      w("Le diff, à accepter ou refuser", "The diff, to accept or refuse"),
    ],
    examples: [
      {
        kind: "list",
        title: w("Une modification proposée", "A proposed change"),
        items: [
          w("billing/rounding.py — arrondi au centime supérieur", "billing/rounding.py — round up to the cent"),
          w("tests/test_rounding.py — un cas ajouté", "tests/test_rounding.py — one case added"),
          w("Risque : les factures déjà émises ne changent pas", "Risk: invoices already issued do not change"),
        ],
      },
      {
        kind: "list",
        title: w("Ce que vous décidez", "What you decide"),
        items: [
          w("Le diff complet, affiché avant toute action", "The full diff, shown before anything happens"),
          w("Accepter : la pull request s'ouvre", "Accept: the pull request opens"),
          w("Refuser : rien n'est poussé", "Refuse: nothing is pushed"),
        ],
      },
    ],
    limits: [
      w(
        "Il travaille sur les dépôts GitHub connectés et ne lance ni le build ni les tests lui-même.",
        "It works on connected GitHub repositories and runs neither the build nor the tests itself.",
      ),
    ],
  },

  "test-generation": {
    promise: w(
      "Les tests qui manquent, écrits dans le style de votre dépôt et proposés en diff — la pull request ne s'ouvre qu'avec votre accord.",
      "The missing tests, written in your repository's style and proposed as a diff — the pull request opens only with your consent.",
    ),
    problem: w(
      "Le code sans tests s'accumule ; écrire les bons tests demande de comprendre le code et les conventions du projet.",
      "Untested code piles up; writing the right tests takes understanding the code and the project's conventions.",
    ),
    benefits: [
      {
        icon: "flask",
        title: w("Vos conventions suivies", "Your conventions followed"),
        body: w(
          "Le cadre, les utilitaires et le style des tests existants, lus avant d'écrire une ligne.",
          "The framework, helpers and style of the existing tests, read before writing a line.",
        ),
      },
      {
        icon: "check",
        title: w("Chaque test expliqué", "Every test explained"),
        body: w(
          "Fichier par fichier, le comportement que chaque test vérifie.",
          "File by file, the behaviour each test checks.",
        ),
      },
      {
        icon: "eye",
        title: w("Vous décidez", "You decide"),
        body: w(
          "Le diff est présenté à une personne : rien n'est poussé sans son accord.",
          "The diff is shown to a person: nothing is pushed without their consent.",
        ),
      },
    ],
    does: w(
      "Il lit le code à tester et les tests qui existent, reconnaît le cadre utilisé — pytest, Jest, Vitest, JUnit, Go test… — et propose les nouveaux tests ; LEKA en calcule le diff et le présente à une personne qui décide.",
      "It reads the code to test and the existing tests, recognises the framework used — pytest, Jest, Vitest, JUnit, Go test… — and proposes the new tests; LEKA computes the diff and shows it to a person who decides.",
    ),
    features: [
      w("Les tests existants du périmètre, cités", "The perimeter's existing tests, cited"),
      w("Les tests proposés, fichier par fichier", "The proposed tests, file by file"),
      w("Le comportement vérifié par chaque test", "The behaviour each test checks"),
      w("Le cadre de test du dépôt respecté", "The repository's test framework respected"),
      w("Ce qui n'a pas été testé, et pourquoi", "What was not tested, and why"),
      w("La commande pour lancer les tests", "The command to run the tests"),
      w("Une pull request ouverte seulement après acceptation", "A pull request opened only once accepted"),
    ],
    useCases: [
      {
        icon: "flask",
        title: w("Couvrir un module sans tests", "Cover an untested module"),
        body: w("Les premiers tests d'un code qui n'en a pas.", "The first tests of code that has none."),
        ask: w(
          "Écris les tests manquants pour billing/rounding.py dans acme/billing",
          "Write the missing tests for billing/rounding.py in acme/billing",
        ),
      },
      {
        icon: "bug",
        title: w("Verrouiller un bug corrigé", "Lock a fixed bug"),
        body: w("Un test qui empêche le retour du bug.", "A test that stops the bug coming back."),
        ask: w(
          "Ajoute un test qui empêche le retour du bug d'arrondi dans acme/billing",
          "Add a test that stops the rounding bug coming back in acme/billing",
        ),
      },
      {
        icon: "shield",
        title: w("Sécuriser un refactoring", "Secure a refactoring"),
        body: w("Figer le comportement avant de le réécrire.", "Pin the behaviour before rewriting it."),
        ask: w(
          "Ajoute des tests sur le calcul des remises de acme/billing avant de le refactorer",
          "Add tests on acme/billing's discount computation before refactoring it",
        ),
      },
      {
        icon: "git",
        title: w("Compléter une pull request", "Complete a pull request"),
        body: w("Les tests qu'une PR aurait dû apporter.", "The tests a PR should have brought."),
        ask: w(
          "Écris les tests qui manquent à la PR #482 de acme/billing",
          "Write the tests missing from acme/billing's PR #482",
        ),
      },
    ],
    outline: [
      w("Ce qui était couvert", "What was covered"),
      w("Les tests proposés", "The proposed tests"),
      w("Ce qui n'a pas été testé, et pourquoi", "What was not tested, and why"),
      w("Comment les lancer", "How to run them"),
      w("Le diff, à accepter ou refuser", "The diff, to accept or refuse"),
    ],
    examples: [
      {
        kind: "list",
        title: w("Tests proposés", "Proposed tests"),
        items: [
          w("L'arrondi au centime supérieur", "Rounding up to the cent"),
          w("Un montant négatif refusé", "A negative amount refused"),
          w("La devise conservée", "The currency kept"),
          w("Le total d'une facture vide", "The total of an empty invoice"),
        ],
      },
      {
        kind: "list",
        title: w("Ce qui n'a pas été testé", "What was not tested"),
        items: [
          w("La règle des remises cumulées : à confirmer", "The stacked-discount rule: to confirm"),
          w("L'appel au service de change : dépendance externe", "The exchange-rate call: external dependency"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne lance pas les tests : la commande du dépôt est donnée pour les exécuter.",
        "It does not run the tests: the repository's command is given to run them.",
      ),
    ],
  },

  "api-design-review": {
    promise: w(
      "Sachez si un changement d'API casse ceux qui l'appellent, et si votre API tient ses propres règles — erreurs, pagination, ce qu'elle expose.",
      "Know whether an API change breaks those who call it, and whether your API keeps its own rules — errors, pagination, what it exposes.",
    ),
    problem: w(
      "Un champ renommé, un paramètre devenu obligatoire, une erreur qui change de forme : la rupture se découvre chez les clients, après la livraison.",
      "A renamed field, a parameter made required, an error changing shape: the break is found by the clients, after the release.",
    ),
    benefits: [
      {
        icon: "shield",
        title: w("Les ruptures avant la livraison", "Breaks before the release"),
        body: w(
          "Ce qu'une pull request casse, pour qui, et comment la livrer sans casser.",
          "What a pull request breaks, for whom, and how to ship it without breaking.",
        ),
      },
      {
        icon: "check",
        title: w("Une API cohérente", "A consistent API"),
        body: w(
          "Les écarts à ses propres conventions : noms, dates, erreurs, pagination.",
          "Departures from its own conventions: names, dates, errors, pagination.",
        ),
      },
      {
        icon: "eye",
        title: w("Ce que le contrat expose", "What the contract exposes"),
        body: w(
          "Un champ interne renvoyé, une écriture sans contrôle d'accès, une erreur trop bavarde.",
          "An internal field returned, a write without access control, an error that says too much.",
        ),
      },
    ],
    does: w(
      "Il lit le contrat de l'API — sa spécification, sinon ses routes et ses modèles dans le code — et, pour une pull request, ce qu'elle change. Il sépare ce qui est sans risque de ce qui rompt, dit qui serait cassé et comment livrer, puis relève les écarts à ses propres conventions avec la correction exacte.",
      "It reads the API's contract — its specification, else its routes and models in the code — and, for a pull request, what it changes. It separates what is safe from what breaks, says who would be broken and how to ship, then lists the departures from its own conventions with the exact fix.",
    ),
    features: [
      w("Le contrat lu, et d'où il vient", "The contract read, and where from"),
      w("Ce qui est sans risque, ce qui rompt", "What is safe, what breaks"),
      w("Pour chaque rupture : qui elle casse, comment la livrer", "For each break: who it breaks, how to ship it"),
      w("Les erreurs, les statuts et la pagination, cohérents", "Errors, statuses and pagination, consistent"),
      w("Les champs internes et les écritures exposés", "Internal fields and writes exposed"),
      w("L'écart entre la documentation et le code", "The gap between documentation and code"),
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Avant de livrer", "Before shipping"),
        body: w("Savoir si une pull request casse les clients.", "Know whether a pull request breaks the clients."),
        ask: w(
          "La PR #42 de acme/api casse-t-elle les clients de l'API ?",
          "Does PR #42 of acme/api break the API's clients?",
        ),
      },
      {
        icon: "check",
        title: w("Revue complète", "Full review"),
        body: w("La cohérence de toute l'API.", "The consistency of the whole API."),
        ask: w("Fais une revue de l'API de acme/api", "Review acme/api's API"),
      },
      {
        icon: "users",
        title: w("Pour vos partenaires", "For your partners"),
        body: w(
          "Ce qu'un changement ferait aux applications qui l'appellent.",
          "What a change would do to the applications calling it.",
        ),
        ask: w(
          "Peut-on livrer ce changement d'API sans casser l'application mobile ?",
          "Can we ship this API change without breaking the mobile app?",
        ),
      },
      {
        icon: "shield",
        title: w("Ce qui est exposé", "What is exposed"),
        body: w("Les champs et les routes qui en disent trop.", "Fields and routes that say too much."),
        ask: w(
          "Notre API expose-t-elle des champs internes ?",
          "Does our API expose internal fields?",
        ),
      },
    ],
    outline: [
      w("Verdict", "Verdict"),
      w("Le contrat lu", "The contract read"),
      w("Ruptures", "Breaks"),
      w("Constats", "Findings"),
      w("Questions", "Questions"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats", "Findings"),
        items: [
          { level: "critical", text: w("Champ « status » retiré de /v1/orders", "« status » field removed from /v1/orders") },
          { level: "high", text: w("Erreur de validation renvoyée en 500", "Validation error returned as a 500") },
          { level: "medium", text: w("Liste /v1/invoices sans pagination", "/v1/invoices list without pagination") },
          { level: "low", text: w("« createdAt » parmi des champs en snake_case", "« createdAt » among snake_case fields") },
        ],
      },
      {
        kind: "list",
        title: w("Livrer sans casser", "Ship without breaking"),
        items: [
          w("Garder l'ancien champ pendant la migration", "Keep the old field during the migration"),
          w("Annoncer la dépréciation, avec une date de fin", "Announce the deprecation, with an end date"),
          w("Le nouveau comportement sous /v2", "The new behaviour under /v2"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit le code et la spécification sans appeler l'API : une limite de débit ou une règle de passerelle que le dépôt ne montre pas est posée en question.",
        "It reads the code and the specification without calling the API: a rate limit or a gateway rule the repository does not show is asked as a question.",
      ),
    ],
  },

  "reliability-analysis": {
    promise: w(
      "Sachez ce qui ferait tomber un service, ce qui se passe quand une dépendance lâche, et quoi corriger d'abord.",
      "Know what would bring a service down, what happens when a dependency gives way, and what to fix first.",
    ),
    problem: w(
      "Les incidents reviennent, une base sans relève porte tout un parcours, une erreur avalée perd des données sans bruit : on l'apprend pendant la panne.",
      "Incidents recur, a database with no standby carries a whole journey, a swallowed error loses data silently: you learn it during the outage.",
    ),
    benefits: [
      {
        icon: "target",
        title: w("Les points de défaillance", "The points of failure"),
        body: w(
          "Ce par quoi tout passe sans remplaçant, et ce qu'une panne atteindrait.",
          "What everything goes through with no replacement, and what an outage would reach.",
        ),
      },
      {
        icon: "eye",
        title: w("Les pannes qui se cachent", "The failures that hide"),
        body: w(
          "Les erreurs avalées, les tâches qui échouent sans alerte, les appels sans délai d'attente.",
          "Swallowed errors, jobs failing without an alert, calls without a timeout.",
        ),
      },
      {
        icon: "clock",
        title: w("Ce que dit l'histoire", "What the history says"),
        body: w(
          "Les incidents, leur temps de résolution, ceux qui reviennent, ceux qui suivent une livraison.",
          "The incidents, how long they took to resolve, those that recur, those that follow a release.",
        ),
      },
    ],
    does: w(
      "Il lit ce dont le service dépend et ce qui dépend de lui, son historique d'incidents et de livraisons, ses alertes et ses documents d'exploitation, et son code quand un dépôt est connecté. Il dit ce que « fiable » veut dire ici, où sont les points de défaillance, ce que fait le code quand une dépendance tombe, puis les actions, par risque.",
      "It reads what the service depends on and what depends on it, its incident and delivery history, its alerts and runbooks, and its code when a repository is connected. It says what « reliable » means here, where the points of failure are, what the code does when a dependency falls, then the actions, by risk.",
    ),
    features: [
      w("L'objectif de service lu, ou proposé à valider", "The service objective read, or proposed to validate"),
      w("Les incidents par gravité, leur résolution, ceux qui reviennent", "Incidents by severity, their resolution, those that recur"),
      w("Les points de défaillance, et ce qu'ils atteignent", "The points of failure, and what they reach"),
      w("Pour chaque dépendance : délai, reprises, repli", "For each dependency: timeout, retries, fallback"),
      w("Les erreurs avalées et les tâches qui échouent en silence", "Swallowed errors and jobs failing silently"),
      w("Les alertes qui suivent ce que vivent les utilisateurs", "Alerts that follow what users experience"),
      w("Les actions, la plus utile d'abord", "The actions, the most useful first"),
    ],
    useCases: [
      {
        icon: "alert",
        title: w("Des incidents qui reviennent", "Incidents that recur"),
        body: w("Comprendre ce qui se répète, et pourquoi.", "Understand what repeats, and why."),
        ask: w(
          "Pourquoi les incidents reviennent-ils sur checkout ?",
          "Why do incidents keep coming back on checkout?",
        ),
      },
      {
        icon: "route",
        title: w("Un parcours critique", "A critical journey"),
        body: w("Ce par quoi tout passe sans relève.", "What everything goes through with no standby."),
        ask: w(
          "Quels sont les points de défaillance uniques du parcours de paiement ?",
          "What are the single points of failure of the payment journey?",
        ),
      },
      {
        icon: "rocket",
        title: w("Avant un pic", "Before a peak"),
        body: w("Ce qui tiendra, ce qui lâchera d'abord.", "What will hold, what will give way first."),
        ask: w(
          "Sommes-nous prêts pour le pic des soldes sur la boutique ?",
          "Are we ready for the sales peak on the shop?",
        ),
      },
      {
        icon: "database",
        title: w("Une dépendance qui tombe", "A dependency that falls"),
        body: w("Ce que verraient les utilisateurs.", "What users would see."),
        ask: w(
          "Que se passe-t-il pour orders-api si la base de données tombe ?",
          "What happens to orders-api if the database goes down?",
        ),
      },
    ],
    outline: [
      w("Verdict", "Verdict"),
      w("Ce que « fiable » veut dire ici", "What « reliable » means here"),
      w("Ce que dit l'histoire", "What the history says"),
      w("Points de défaillance", "Points of failure"),
      w("Quand une dépendance tombe", "When a dependency falls"),
      w("Les pannes qui se cachent", "The failures that hide"),
      w("Actions", "Actions"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats", "Findings"),
        items: [
          { level: "critical", text: w("Base « orders » sans réplique, sous tout le paiement", "« orders » database with no replica, under the whole payment") },
          { level: "high", text: w("Appel au prestataire de paiement sans délai d'attente", "Call to the payment provider without a timeout") },
          { level: "medium", text: w("Erreur d'envoi de facture avalée, sans alerte", "Invoice sending error swallowed, without an alert") },
          { level: "low", text: w("Alerte sur le processeur, aucune sur les erreurs", "Alert on CPU, none on errors") },
        ],
      },
      {
        kind: "list",
        title: w("Actions", "Actions"),
        items: [
          w("Un délai et deux reprises espacées sur l'appel de paiement", "A timeout and two spaced retries on the payment call"),
          w("Une alerte sur la part de paiements en erreur", "An alert on the share of payments failing"),
          w("Une réplique de la base, essayée en bascule", "A database replica, tried in a failover"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit le modèle, l'historique et le code sans rien provoquer : aucun test de charge, aucune panne simulée — une relève que les sources ne montrent pas est posée en question.",
        "It reads the model, the history and the code without causing anything: no load test, no simulated outage — a standby the sources do not show is asked as a question.",
      ),
    ],
  },

  "dependency-analysis": {
    promise: w(
      "Sachez quels paquets tiers exposent votre code, lesquels traiter d'abord, et la version qui corrige.",
      "Know which third-party packages expose your code, which to deal with first, and the version that fixes them.",
    ),
    problem: w(
      "Des centaines de paquets tirés par quelques-uns : une faille annoncée, et personne ne sait si elle vous touche, ni par où elle arrive.",
      "Hundreds of packages pulled in by a few: a flaw is announced, and no one knows whether it touches you, nor how it gets in.",
    ),
    benefits: [
      {
        icon: "shield",
        title: w("Les vulnérabilités connues", "Known vulnerabilities"),
        body: w(
          "Chaque paquet de vos fichiers de verrouillage, cherché dans une base publique de vulnérabilités.",
          "Every package of your lock files, looked up in a public vulnerability database.",
        ),
      },
      {
        icon: "target",
        title: w("Ce qui compte vraiment", "What really matters"),
        body: w(
          "Directe ou transitive, production ou développement, appelée ou non : la priorité, pas seulement la note.",
          "Direct or transitive, production or development, called or not: the priority, not only the score.",
        ),
      },
      {
        icon: "check",
        title: w("La correction exacte", "The exact fix"),
        body: w(
          "La version qui corrige, le paquet à monter, ce qu'il faut tester après.",
          "The version that fixes it, the package to upgrade, what to test afterwards.",
        ),
      },
    ],
    does: w(
      "Il trouve les fichiers de dépendances du dépôt, les fait lire par LEKA sans rien installer et cherche chaque paquet public dans une base publique de vulnérabilités. Il trie chaque faille selon ce qu'elle expose ici, donne la version qui corrige, relève ce qui s'exécute à l'installation, et relie un changement de versions à un incident qu'il précède.",
      "It finds the repository's dependency files, has LEKA read them without installing anything and looks each public package up in a public vulnerability database. It ranks each flaw by what it exposes here, gives the version that fixes it, points out what runs at install time, and ties a change of versions to an incident it preceded.",
    ),
    features: [
      w("Chaque fichier de verrouillage lu en entier", "Every lock file read whole"),
      w("Les vulnérabilités connues, avec leurs identifiants", "Known vulnerabilities, with their identifiers"),
      w("Directes ou transitives, production ou développement", "Direct or transitive, production or development"),
      w("La version qui corrige, et le paquet à monter", "The fixing version, and the package to upgrade"),
      w("Les scripts d'installation et les sources hors registre", "Install scripts and sources outside the registry"),
      w("Les versions avant et après d'une montée", "Versions before and after an upgrade"),
      w("Le changement de dépendance avant un incident", "The dependency change before an incident"),
    ],
    useCases: [
      {
        icon: "shield",
        title: w("Un état des lieux", "A review"),
        body: w("Les vulnérabilités connues de tout un dépôt.", "The known vulnerabilities of a whole repository."),
        ask: w(
          "Nos dépendances ont-elles des vulnérabilités connues dans acme/web ?",
          "Do our dependencies have known vulnerabilities in acme/web?",
        ),
      },
      {
        icon: "alert",
        title: w("Une faille annoncée", "A flaw announced"),
        body: w("Savoir si elle vous touche, et où.", "Know whether it touches you, and where."),
        ask: w("Sommes-nous touchés par la faille de log4j ?", "Are we affected by the log4j flaw?"),
      },
      {
        icon: "git",
        title: w("Une montée de versions", "An upgrade"),
        body: w("Ce qu'elle corrige, ce qu'elle apporte.", "What it fixes, what it brings."),
        ask: w(
          "La montée de versions de la PR #42 de acme/web est-elle sûre ?",
          "Is the upgrade in PR #42 of acme/web safe?",
        ),
      },
      {
        icon: "clock",
        title: w("Après un incident", "After an incident"),
        body: w("Une dépendance a-t-elle changé juste avant ?", "Did a dependency change just before?"),
        ask: w(
          "Une dépendance a-t-elle changé avant la panne de checkout ?",
          "Did a dependency change before the checkout outage?",
        ),
      },
    ],
    outline: [
      w("Verdict", "Verdict"),
      w("Ce qui a été lu", "What was read"),
      w("Vulnérabilités", "Vulnerabilities"),
      w("Ce qui s'exécute à l'installation", "What runs at install time"),
      w("Actions", "Actions"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Vulnérabilités", "Vulnerabilities"),
        items: [
          { level: "critical", text: w("log4j-core 2.14.1, en production — corrigé en 2.17.1", "log4j-core 2.14.1, in production — fixed in 2.17.1") },
          { level: "high", text: w("qs 6.5.0, transitive par express — monter express", "qs 6.5.0, transitive through express — upgrade express") },
          { level: "medium", text: w("Script postinstall d'un paquet tiré d'un dépôt git", "Postinstall script of a package pulled from a git repository") },
          { level: "low", text: w("lodash en trois versions", "lodash in three versions") },
        ],
      },
      {
        kind: "list",
        title: w("Actions", "Actions"),
        items: [
          w("Monter log4j-core en 2.17.1, puis rejouer les tests d'intégration", "Upgrade log4j-core to 2.17.1, then rerun the integration tests"),
          w("Monter express pour corriger qs", "Upgrade express to fix qs"),
          w("Installer avec le fichier de verrouillage dans la CI", "Install from the lock file in the CI"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit les fichiers sans rien installer ni exécuter ; seuls les noms et versions des paquets publics sont envoyés à la base de vulnérabilités — une faille que la base ne connaît pas encore n'est pas vue.",
        "It reads the files without installing or running anything; only public packages' names and versions are sent to the vulnerability database — a flaw the database does not know yet is not seen.",
      ),
    ],
  },

  "database-review": {
    promise: w(
      "Sachez si votre base tiendra : son schéma, les index que ses requêtes demandent, et les migrations à livrer sans rien bloquer.",
      "Know whether your database will hold: its schema, the indexes its queries need, and the migrations to ship without blocking anything.",
    ),
    problem: w(
      "Une clé étrangère sans index sur une table qui grossit, une migration qui verrouille la table des commandes, une colonne retirée que le code lit encore : on le découvre en production.",
      "A foreign key without an index on a growing table, a migration that locks the orders table, a column dropped that the code still reads: you find out in production.",
    ),
    benefits: [
      {
        icon: "database",
        title: w("Le schéma tel qu'il est", "The schema as it is"),
        body: w(
          "Lu dans le catalogue de la base : clés, index, types, volumes — jamais une ligne de données.",
          "Read from the database's catalogue: keys, indexes, types, volumes — never a row of data.",
        ),
      },
      {
        icon: "search",
        title: w("Des index pour de vraies requêtes", "Indexes for real queries"),
        body: w(
          "Chaque index proposé part d'une requête du code, avec ce qu'il coûte.",
          "Each index proposed starts from a query in the code, with what it costs.",
        ),
      },
      {
        icon: "shield",
        title: w("Des migrations sans casse", "Migrations without breakage"),
        body: w(
          "Le verrou qu'elles prennent, les données qu'elles risquent, et l'ordre sûr pour livrer.",
          "The lock they take, the data they risk, and the safe order to ship.",
        ),
      },
    ],
    does: w(
      "Il lit la structure de la base dans son catalogue — chaque table, ses clés, ses index, son volume — et calcule ce qui manque : clé primaire, index de clé étrangère, types exacts. Il relit dans le code les requêtes et les migrations, dit lesquelles ne tiendront pas quand la base grossira et comment les corriger, puis ce qu'il faut mesurer sur la base.",
      "It reads the database's structure from its catalogue — each table, its keys, its indexes, its volume — and works out what is missing: primary keys, foreign key indexes, exact types. It reviews the queries and migrations in the code, says which will not hold as the database grows and how to fix them, then what to measure on the database.",
    ),
    features: [
      w("Les tables sans clé primaire", "Tables without a primary key"),
      w("Les clés étrangères qu'aucun index ne sert", "Foreign keys no index serves"),
      w("Les index en double", "Duplicate indexes"),
      w("Les requêtes N+1, sans limite, par décalage", "N+1, unbounded and offset queries"),
      w("Les migrations qui verrouillent ou perdent des données", "Migrations that lock or lose data"),
      w("L'argent en type flottant, les dates sans fuseau", "Money in a floating type, dates without a time zone"),
      w("Les droits et les données sensibles", "Access rights and sensitive data"),
    ],
    useCases: [
      {
        icon: "database",
        title: w("Une revue complète", "A full review"),
        body: w("Le schéma, ses index, ses risques.", "The schema, its indexes, its risks."),
        ask: w("Fais une revue de la base de données ledger", "Review the ledger database"),
      },
      {
        icon: "git",
        title: w("Avant une migration", "Before a migration"),
        body: w("Le verrou qu'elle prend, l'ordre pour livrer.", "The lock it takes, the order to ship."),
        ask: w(
          "La migration de la PR #42 de acme/api est-elle sûre en production ?",
          "Is the migration in PR #42 of acme/api safe in production?",
        ),
      },
      {
        icon: "clock",
        title: w("Une page lente", "A slow page"),
        body: w("La requête en cause, et l'index qui lui manque.", "The query at fault, and the index it lacks."),
        ask: w("Pourquoi la liste des factures est-elle lente ?", "Why is the invoice list slow?"),
      },
      {
        icon: "shield",
        title: w("Les données protégées", "Data protected"),
        body: w("Qui peut lire quoi, ce qui est sensible.", "Who may read what, what is sensitive."),
        ask: w(
          "Notre schéma de facturation protège-t-il ses données ?",
          "Does our billing schema protect its data?",
        ),
      },
    ],
    outline: [
      w("Verdict", "Verdict"),
      w("Ce qui a été lu", "What was read"),
      w("Intégrité du schéma", "Schema integrity"),
      w("Index et requêtes", "Indexes and queries"),
      w("Migrations", "Migrations"),
      w("Actions", "Actions"),
      w("À mesurer", "To measure"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats", "Findings"),
        items: [
          { level: "critical", text: w("invoices.customer_id sans index — 12 millions de lignes", "invoices.customer_id without an index — 12 million rows") },
          { level: "high", text: w("Index créé sans CONCURRENTLY sur orders", "Index created without CONCURRENTLY on orders") },
          { level: "medium", text: w("Montant en double precision", "Amount in double precision") },
          { level: "low", text: w("Deux index sur lines (sku)", "Two indexes on lines (sku)") },
        ],
      },
      {
        kind: "list",
        title: w("Actions", "Actions"),
        items: [
          w("CREATE INDEX CONCURRENTLY sur invoices (customer_id)", "CREATE INDEX CONCURRENTLY on invoices (customer_id)"),
          w("Ajouter la colonne, remplir par lots, puis NOT NULL", "Add the column, fill it in batches, then NOT NULL"),
          w("Mesurer la requête des factures avec EXPLAIN ANALYZE", "Measure the invoice query with EXPLAIN ANALYZE"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit le catalogue et le code sans lancer aucune requête : la durée réelle d'une requête et l'usage réel d'un index se mesurent sur la base, il dit comment.",
        "It reads the catalogue and the code without running any query: a query's real duration and an index's real use are measured on the database, it says how.",
      ),
    ],
  },

  "performance-analysis": {
    promise: w(
      "Sachez où passe le temps d'une page lente, ce qui ne tiendra pas quand les données grandiront, et quoi corriger d'abord.",
      "Know where a slow page's time goes, what will not hold as the data grows, and what to fix first.",
    ),
    problem: w(
      "Une page ralentit, on ajoute des serveurs ou un cache au hasard : la vraie cause — une requête par ligne, des appels en série — reste là et grandit avec les données.",
      "A page slows down, servers or a cache get added at random: the real cause — one query per row, calls in sequence — stays and grows with the data.",
    ),
    benefits: [
      {
        icon: "route",
        title: w("Le chemin de la lenteur", "The path of the slowness"),
        body: w(
          "De la page à la base, étape par étape, où le temps peut passer.",
          "From the page to the database, step by step, where the time can go.",
        ),
      },
      {
        icon: "layers",
        title: w("Ce qui grandit avec les données", "What grows with the data"),
        body: w(
          "Les requêtes par ligne, les listes sans limite, les boucles dans des boucles.",
          "Queries per row, lists without a limit, loops within loops.",
        ),
      },
      {
        icon: "target",
        title: w("Des corrections à prouver", "Fixes to prove"),
        body: w(
          "Chaque correction avec la mesure avant et après qui la prouvera.",
          "Each fix with the before-and-after measure that will prove it.",
        ),
      },
    ],
    does: w(
      "Il part de ce qui est mesuré — une durée, un incident, une alerte — et suit la requête lente de la page jusqu'à la base, dans le code et dans ce dont le service dépend. Il dit où le temps peut passer, ce qui ne tiendra pas quand les données grandiront, ce qu'une pull request ajoute sur le chemin, puis les corrections et le plan de mesure qui les prouvera.",
      "It starts from what is measured — a duration, an incident, an alert — and follows the slow request from the page to the database, in the code and in what the service depends on. It says where the time can go, what will not hold as the data grows, what a pull request adds on the path, then the fixes and the measurement plan that will prove them.",
    ),
    features: [
      w("Le chemin d'une requête lente, étape par étape", "A slow request's path, step by step"),
      w("Les requêtes N+1 et les appels en série", "N+1 queries and calls in sequence"),
      w("Le travail qui grandit avec les données", "Work that grows with the data"),
      w("Ce qui bloque : entrées-sorties, verrous, pools", "What blocks: I/O, locks, pools"),
      w("Le poids du front : dépendances, découpage, images", "The front end's weight: dependencies, splitting, images"),
      w("Ce qu'une pull request ajoute sur le chemin", "What a pull request adds on the path"),
      w("Le plan de mesure qui prouvera chaque gain", "The measurement plan that will prove each gain"),
    ],
    useCases: [
      {
        icon: "clock",
        title: w("Une page lente", "A slow page"),
        body: w("Où passe son temps, et pourquoi.", "Where its time goes, and why."),
        ask: w("Pourquoi la page des commandes est-elle lente ?", "Why is the orders page slow?"),
      },
      {
        icon: "rocket",
        title: w("Avant la croissance", "Before growth"),
        body: w("Ce qui lâchera quand le trafic doublera.", "What will give way when traffic doubles."),
        ask: w("orders-api tiendra-t-il si le trafic double ?", "Will orders-api hold if traffic doubles?"),
      },
      {
        icon: "git",
        title: w("Avant de fusionner", "Before merging"),
        body: w("Ce qu'une pull request coûte en temps.", "What a pull request costs in time."),
        ask: w(
          "La PR #42 de acme/shop ralentit-elle l'application ?",
          "Does PR #42 of acme/shop slow the application down?",
        ),
      },
      {
        icon: "zap",
        title: w("Un front lourd", "A heavy front end"),
        body: w("Ce que l'utilisateur attend, et pourquoi.", "What the user waits for, and why."),
        ask: w("Qu'est-ce qui rend le front de acme/web lourd ?", "What makes acme/web's front end heavy?"),
      },
    ],
    outline: [
      w("Verdict", "Verdict"),
      w("Ce qui est mesuré", "What is measured"),
      w("Le chemin", "The path"),
      w("Constats", "Findings"),
      w("Actions", "Actions"),
      w("À mesurer", "To measure"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Constats", "Findings"),
        items: [
          { level: "critical", text: w("Une requête par commande dans la liste (N+1)", "One query per order in the list (N+1)") },
          { level: "high", text: w("Trois appels en série au service de stock", "Three calls in sequence to the stock service") },
          { level: "medium", text: w("Bibliothèque de dates importée entière", "Date library imported whole") },
          { level: "low", text: w("Animation sur la hauteur du panneau", "Animation on the panel's height") },
        ],
      },
      {
        kind: "list",
        title: w("À mesurer", "To measure"),
        items: [
          w("Le profil de la route /orders, avant et après", "The /orders route's profile, before and after"),
          w("EXPLAIN ANALYZE de la requête des commandes", "EXPLAIN ANALYZE of the orders query"),
          w("Un test de charge sur le tunnel de commande", "A load test on the checkout journey"),
        ],
      },
    ],
    limits: [
      w(
        "Il lit le code et l'histoire sans rien exécuter : aucun profil, aucun test de charge — chaque gain est un ordre de grandeur, à confirmer par la mesure qu'il indique.",
        "It reads the code and the history without running anything: no profile, no load test — each gain is an order of magnitude, to confirm with the measure it gives.",
      ),
    ],
  },

  "qa-acceptance": {
    promise: w(
      "Sachez si une pull request est prête : chaque critère attendu, vérifié avec sa preuve — le code, le test, la CI.",
      "Know whether a pull request is ready: each expected criterion, checked with its proof — the code, the test, the CI.",
    ),
    problem: w(
      "« C'est testé, c'est prêt » se dit souvent sans preuve : ce qui manque se découvre en production.",
      "« It's tested, it's ready » is often said without proof: what is missing shows up in production.",
    ),
    benefits: [
      {
        icon: "check",
        title: w("Critère par critère", "Criterion by criterion"),
        body: w(
          "Les critères du ticket, chacun avec son statut et sa preuve.",
          "The ticket's criteria, each with its status and its proof.",
        ),
      },
      {
        icon: "eye",
        title: w("Ce qui n'est pas prouvé, dit", "What is not proven, said"),
        body: w(
          "Le code sans test, le test qui n'affirme rien, la CI absente ou rouge.",
          "Code without a test, a test that asserts nothing, a CI missing or red.",
        ),
      },
      {
        icon: "flask",
        title: w("La recette à la main, guidée", "Manual testing, guided"),
        body: w(
          "Ce qu'une personne doit vérifier dans l'application, et quoi observer.",
          "What a person must check in the application, and what to observe.",
        ),
      },
    ],
    does: w(
      "Il lit le ticket et ses critères d'acceptation, puis la pull request : le code changé, ses tests et sa CI. Il rend un verdict — Prêt, À reprendre ou Bloqué — avec la preuve de chaque critère et les problèmes reproductibles.",
      "It reads the ticket and its acceptance criteria, then the pull request: the changed code, its tests and its CI. It gives a verdict — Ready, Needs work or Blocked — with the proof of each criterion and the reproducible issues.",
    ),
    features: [
      w("Les critères cités, d'où ils viennent", "The criteria quoted, and where they come from"),
      w("Un statut et une preuve pour chaque critère", "A status and a proof for each criterion"),
      w("Les tests qui ne prouvent rien, signalés", "Tests that prove nothing, flagged"),
      w("Les problèmes reproductibles, par gravité", "Reproducible issues, by severity"),
      w("La liste à cocher de la recette à la main", "The checklist for manual testing"),
      w("Ce qui n'a pas pu être vérifié, et pourquoi", "What could not be checked, and why"),
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Avant de fusionner", "Before merging"),
        body: w("Savoir si la pull request fait ce qui était demandé.", "Know whether the pull request does what was asked."),
        ask: w("Peut-on fusionner la PR #42 de acme/web ?", "Can we merge PR #42 of acme/web?"),
      },
      {
        icon: "check",
        title: w("Contre le ticket", "Against the ticket"),
        body: w("Chaque critère d'acceptation, vérifié.", "Each acceptance criterion, checked."),
        ask: w(
          "La PR #42 de acme/web respecte-t-elle les critères du ticket PAY-142 ?",
          "Does PR #42 of acme/web meet the criteria of ticket PAY-142?",
        ),
      },
      {
        icon: "eye",
        title: w("Ce qui n'est pas testé", "What is not tested"),
        body: w("Le code changé qu'aucun test n'exerce.", "Changed code that no test exercises."),
        ask: w(
          "Qu'est-ce qui n'est pas testé dans la dernière PR de acme/web ?",
          "What is not tested in acme/web's latest PR?",
        ),
      },
      {
        icon: "flask",
        title: w("Préparer la recette", "Prepare acceptance testing"),
        body: w("Ce qu'il faut vérifier à la main, et comment.", "What to check by hand, and how."),
        ask: w("Fais la recette de la PR #42 de acme/web", "Run the acceptance check of PR #42 of acme/web"),
      },
    ],
    outline: [
      w("Verdict", "Verdict"),
      w("Ce qui était attendu", "What was expected"),
      w("Critère par critère", "Criterion by criterion"),
      w("Problèmes trouvés", "Issues found"),
      w("À vérifier à la main", "To check by hand"),
      w("Avant de dire « Prêt »", "Before saying « Ready »"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Critère par critère", "Criterion by criterion"),
        items: [
          { level: "low", text: w("Export CSV avec la date — vérifié", "CSV export with the date — checked") },
          { level: "medium", text: w("Tri par montant — fait, sans test", "Sort by amount — done, no test") },
          { level: "high", text: w("Filtre par client — absent", "Filter by customer — missing") },
          { level: "critical", text: w("Total recalculé — test en échec", "Recomputed total — test failing") },
        ],
      },
      {
        kind: "list",
        title: w("À vérifier à la main", "To check by hand"),
        items: [
          w("L'export s'ouvre dans un tableur", "The export opens in a spreadsheet"),
          w("Les accents restent lisibles", "Accents stay readable"),
          w("Un client sans facture : fichier vide, pas d'erreur", "A customer with no invoice: empty file, no error"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne lance ni l'application ni les tests : il lit le code, les tests et le résultat de la CI, et dit ce qu'une personne doit vérifier à la main.",
        "It runs neither the application nor the tests: it reads the code, the tests and the CI's result, and says what a person must check by hand.",
      ),
    ],
  },

  "test-analysis": {
    promise: w(
      "Sachez quoi tester avant ou après un changement : ce qu'il touche, ce qui en dépend et ce qui a cassé récemment.",
      "Know what to test before or after a change: what it touches, what depends on it and what broke recently.",
    ),
    problem: w(
      "Tout tester coûte cher, tester au hasard laisse passer des régressions : il faut savoir où porter l'effort.",
      "Testing everything is costly, testing at random lets regressions through: you need to know where to focus.",
    ),
    benefits: [
      {
        icon: "target",
        title: w("Tester au bon endroit", "Test in the right place"),
        body: w("Un plan de test priorisé, les points critiques d'abord.", "A prioritised test plan, critical points first."),
      },
      {
        icon: "route",
        title: w("Les effets de bord", "Side effects"),
        body: w(
          "Ce qui dépend du changement et doit être revérifié.",
          "What depends on the change and must be checked again.",
        ),
      },
      {
        icon: "alert",
        title: w("Les zones à risque", "Risky areas"),
        body: w("Ce qui a cassé récemment autour du changement.", "What broke recently around the change."),
      },
    ],
    does: w(
      "Il part du changement ou de la release, suit ce qui en dépend dans votre environnement et les incidents récents autour, puis propose un plan de test priorisé dont chaque point est justifié.",
      "It starts from the change or the release, follows what depends on it in your environment and the recent incidents around it, then proposes a prioritised test plan where every point is justified.",
    ),
    features: [
      w("Le périmètre touché directement", "The perimeter touched directly"),
      w("Ce qui doit être revérifié par ricochet", "What must be checked again in turn"),
      w("Les zones qui ont cassé récemment", "The areas that broke recently"),
      w("Un plan de test priorisé, critiques d'abord", "A prioritised test plan, critical first"),
      w("Pour chaque point : quoi observer et pourquoi", "For each point: what to observe and why"),
      w("Ce qu'un test vert ne prouverait pas", "What a green test would not prove"),
    ],
    useCases: [
      {
        icon: "rocket",
        title: w("Préparer une recette", "Prepare acceptance testing"),
        body: w("Savoir quoi tester avant de livrer.", "Know what to test before shipping."),
        ask: w("Que faut-il tester avant la release de payment-api ?", "What should be tested before payment-api's release?"),
      },
      {
        icon: "route",
        title: w("Mesurer les effets de bord", "Measure side effects"),
        body: w("Ce qui dépend d'un changement et doit être retesté.", "What depends on a change and must be retested."),
        ask: w(
          "Qu'est-ce qui dépend du changement sur auth-service et doit être retesté ?",
          "What depends on the auth-service change and must be retested?",
        ),
      },
      {
        icon: "check",
        title: w("Vérifier après une mise en production", "Check after a release"),
        body: w("Les vérifications utiles après un déploiement.", "The checks that matter after a deployment."),
        ask: w("Que tester après le déploiement de checkout ?", "What to test after checkout's deployment?"),
      },
      {
        icon: "alert",
        title: w("Cibler les zones fragiles", "Target fragile areas"),
        body: w("Ce qui casse souvent, à surveiller de près.", "What often breaks, to watch closely."),
        ask: w("Quelles zones de checkout ont cassé récemment ?", "Which areas of checkout broke recently?"),
      },
    ],
    outline: [
      w("Périmètre", "Perimeter"),
      w("Par ricochet", "In turn"),
      w("Zones à risque", "Risky areas"),
      w("Plan de test proposé", "Proposed test plan"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Plan de test proposé", "Proposed test plan"),
        items: [
          { level: "critical", text: w("Paiement par carte, parcours complet", "Card payment, full journey") },
          { level: "high", text: w("Remboursement partiel", "Partial refund") },
          { level: "medium", text: w("Export comptable", "Accounting export") },
          { level: "low", text: w("Libellés des e-mails", "E-mail wording") },
        ],
      },
      {
        kind: "list",
        title: w("Par ricochet", "In turn"),
        items: [
          w("checkout — appelle l'API modifiée", "checkout — calls the changed API"),
          w("facturation — lit la même table", "billing — reads the same table"),
          w("notifications — dépend de l'événement", "notifications — depends on the event"),
        ],
      },
    ],
    limits: [
      w(
        "Il ne lit pas la couverture de tests : il le dit quand c'est elle qui manque.",
        "It does not read test coverage: it says so when that is what is missing.",
      ),
    ],
  },

  "regression-analysis": {
    promise: w(
      "Avant de livrer, sachez ce que votre changement pourrait casser qui fonctionnait — et si un test le protège.",
      "Before shipping, know what your change could break that used to work — and whether a test guards it.",
    ),
    problem: w(
      "Une régression se découvre souvent en production, parce que personne n'a vu qui dépendait du comportement modifié.",
      "A regression is often found in production, because nobody saw what depended on the changed behaviour.",
    ),
    benefits: [
      {
        icon: "shield",
        title: w("Les régressions anticipées", "Regressions anticipated"),
        body: w(
          "Chaque comportement modifié, qui en dépend et le test qui le garde.",
          "Each changed behaviour, what depends on it and the test that guards it.",
        ),
      },
      {
        icon: "route",
        title: w("Les dépendances suivies", "Dependencies followed"),
        body: w(
          "Les appelants dans le code et les services qui dépendent de ce qui change.",
          "Callers in the code and services that depend on what changes.",
        ),
      },
      {
        icon: "clock",
        title: w("L'historique pris en compte", "History taken into account"),
        body: w(
          "Ce qui a déjà cassé dans cette zone après un changement semblable.",
          "What already broke in this area after a similar change.",
        ),
      },
    ],
    does: w(
      "Il lit le diff, suit ce qui dépend du code modifié — dans le code et dans votre environnement —, cherche les tests qui le gardent et regarde ce qui a cassé dans la zone, pour dresser la liste des risques de régression.",
      "It reads the diff, follows what depends on the changed code — in the code and in your environment —, looks for the tests that guard it and at what broke in the area, to list the regression risks.",
    ),
    features: [
      w("Ce qui change vraiment, d'après le diff", "What really changes, from the diff"),
      w("Les risques de régression, en tableau", "Regression risks, in a table"),
      w("Qui dépend de chaque comportement modifié", "What depends on each changed behaviour"),
      w("Le test qui le garde — ou son absence", "The test that guards it — or none"),
      w("Les cassures passées de la zone", "The area's past breakages"),
      w("Les tests à ajouter et les personnes à prévenir", "Tests to add and people to warn"),
    ],
    useCases: [
      {
        icon: "shield",
        title: w("Sécuriser une pull request", "Secure a pull request"),
        body: w("Savoir ce qu'elle peut casser avant de fusionner.", "Know what it can break before merging."),
        ask: w("Que pourrait casser la PR #482 de acme/billing ?", "What could acme/billing's PR #482 break?"),
      },
      {
        icon: "rocket",
        title: w("Préparer une release", "Prepare a release"),
        body: w("Les risques de régression de ce qui part.", "The regression risks of what ships."),
        ask: w(
          "Quels risques de régression dans la release 2.8 de payment-api ?",
          "What regression risks in payment-api's 2.8 release?",
        ),
      },
      {
        icon: "flask",
        title: w("Repérer les zones non testées", "Spot untested areas"),
        body: w("Ce qui change sans aucun test pour le garder.", "What changes with no test to guard it."),
        ask: w(
          "Quels comportements modifiés par la PR #482 ne sont couverts par aucun test ?",
          "Which behaviours changed by PR #482 are covered by no test?",
        ),
      },
      {
        icon: "users",
        title: w("Savoir qui prévenir", "Know whom to warn"),
        body: w("Les équipes qui dépendent de ce qui change.", "The teams that depend on what changes."),
        ask: w(
          "Qui faut-il prévenir avant de fusionner la PR #482 de acme/billing ?",
          "Whom should we warn before merging acme/billing's PR #482?",
        ),
      },
    ],
    outline: [
      w("Ce qui change", "What changes"),
      w("Risques de régression", "Regression risks"),
      w("À vérifier avant de livrer", "To check before shipping"),
      w("Limites", "Limits"),
    ],
    examples: [
      {
        kind: "levels",
        title: w("Risques de régression", "Regression risks"),
        items: [
          { level: "high", text: w("Calcul des remises modifié — aucun test", "Discount computation changed — no test") },
          { level: "medium", text: w("Format de date de l'export changé — 2 consommateurs", "Export date format changed — 2 consumers") },
          { level: "low", text: w("Libellé d'erreur modifié — test existant", "Error wording changed — test exists") },
        ],
      },
      {
        kind: "list",
        title: w("À vérifier avant de livrer", "To check before shipping"),
        items: [
          w("Ajouter un test sur le calcul des remises", "Add a test on the discount computation"),
          w("Prévenir l'équipe Export", "Warn the Export team"),
          w("Relancer les tests de checkout", "Run checkout's tests again"),
        ],
      },
    ],
    limits: [
      w(
        "Le diff est lu sur GitHub ; ailleurs, il s'appuie sur ce que les sources disent du changement. Un diff tronqué est signalé.",
        "The diff is read on GitHub; elsewhere, it relies on what the sources say of the change. A truncated diff is reported.",
      ),
    ],
  },
};
