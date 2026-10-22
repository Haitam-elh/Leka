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
