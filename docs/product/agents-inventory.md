# Inventaire des agents et skills externes → LEKA

Inventaire demandé pour raccorder ECC, gstack et emilkowalski/skills au catalogue
de LEKA (agents, capacités, moteur d'intentions, page Capacités, bundles, pricing).
Il complète LEKA-400 (bibliothèque d'agents) et s'aligne sur LEKA-439 (routage),
LEKA-438 (page Capacités) et LEKA-446 (pricing) sans en recopier ni en contredire les règles.

**Ce document n'importe rien.** Aucun fichier de ces dépôts n'est copié dans LEKA ici.
Chaque import retenu se fera dans sa propre PR : relu ligne par ligne
(`agents/README.md`, règle 1) et inscrit dans `THIRD_PARTY_LICENSES.md`.

## 1. Sources examinées

| Dépôt | Commit examiné | Date | Version | Licence |
| --- | --- | --- | --- | --- |
| [affaan-m/ECC](https://github.com/affaan-m/ECC) | `b92f181` | 2026-10-11 | 2.2.3 | MIT — © 2026 Affaan Mustafa ; exceptions skill par skill, ci-dessous |
| [garrytan/gstack](https://github.com/garrytan/gstack) | `945ac30` | 2026-10-13 | 1.91.97.0 | MIT — © 2026 Garry Tan ; quelques fichiers de design dérivés d'œuvres Apache-2.0 (impeccable, DESIGN.md), listés dans son NOTICE.md |
| [emilkowalski/skills](https://github.com/emilkowalski/skills) | `2d22863` | 2026-10-11 | — (pas de version publiée) | MIT — © 2026 Emil Kowalski |

Ce qui a été compté comme un élément :

- **ECC** : `skills/*/SKILL.md` (311) et `agents/*.md` (71). Le reste de ses 1 062
  `SKILL.md` sont des traductions (`docs/ja-JP`, `docs/zh-CN`…) ou des portages vers
  d'autres outils (`.kiro`, `.cursor`, `pi`, `.agents`) des mêmes skills : pas des éléments distincts.
- **gstack** : les 57 dossiers de premier niveau qui ont un `SKILL.md` (les commandes).
  `openclaw/`, `capy/`, `browser-skills/` et `test/fixtures/` sont des variantes ou des fixtures.
- **emilkowalski/skills** : les 15 `skills/*/SKILL.md`.

**Exceptions à la MIT dans ECC**, déclarées skill par skill dans leur front matter :

- `osint-investigation` : **CC BY-SA 4.0** (avec son propre `LICENSE.txt`) — toute adaptation
  resterait CC BY-SA ; à ne jamais reprendre dans LEKA.
- **Apache-2.0** : `carrier-relationship-management`, `customs-trade-compliance`,
  `energy-procurement`, `inventory-demand-planning`, `logistics-exception-management`,
  `production-scheduling`, `quality-nonconformance`, `returns-reverse-logistics`,
  `healthcare-cdss-patterns`. Une reprise imposerait la notice de modification d'Apache.
- gstack : `design-review` et quelques fichiers de design dérivés d'œuvres Apache-2.0 (son `NOTICE.md`).

Aucun de ces éléments n'est retenu (tous « non retenu »). Pour le reste :

Licences : MIT. L'usage commercial est permis, à condition de garder la
notice de copyright de toute « portion substantielle » reprise. Une méthode réécrite dans
nos mots et citée suffit ; un passage repris tel quel garde sa notice. Les fichiers
Apache-2.0 de gstack (design) ne sont pas retenus.

## 2. Ce que « skill » veut dire de chaque côté

Les deux mots se ressemblent, ce ne sont pas les mêmes objets :

- **Un skill de ces dépôts** est une méthode en markdown pour un agent de *développement*
  (Claude Code, Codex…) qui lit et écrit des fichiers, lance des commandes, pilote un navigateur.
- **Un skill LEKA** (LEKA-401, `api/leka/intelligence/library.py`, `docs/skills.md`) est une
  lecture déterministe, écrite en Python, du modèle d'entreprise : `change-review`,
  `blast-radius`, `delivery-metrics`… Il ne lit jamais un outil en direct.
- **Un agent LEKA** est un `SKILL.md` exécuté par le runtime (LEKA-395) avec des outils en
  lecture seule sur le modèle d'entreprise : `search_entities`, `read_entity`, `what_happened`,
  `dependencies` ; seul `code-change` lit des fichiers GitHub (`list_files`, `read_file`).

« Rattacher » une méthode externe à un agent LEKA veut donc dire **enrichir ses instructions**,
jamais créer un skill LEKA ni lui donner un outil qu'il n'a pas.

## 3. Décisions

| Décision | ECC | gstack | emilkowalski | Total |
| --- | --- | --- | --- | --- |
| enrichissement | 18 | 6 | 0 | 24 |
| déjà couvert | 8 | 1 | 0 | 9 |
| nouvelle capacité | 0 | 1 | 0 | 1 |
| doublon | 10 | 0 | 0 | 10 |
| bloqué | 33 | 3 | 0 | 36 |
| non retenu | 313 | 46 | 15 | 374 |
| **total** | 382 | 57 | 15 | **454** |

- **enrichissement** : une méthode qui améliore un agent LEKA existant ; elle entre dans ses instructions.
- **déjà couvert** : LEKA le fait déjà (moteur d'intentions, connecteurs).
- **nouvelle capacité** : une responsabilité distincte, absente de LEKA — à construire, donc planifiée.
- **doublon** : variante d'un agent LEKA déjà générique.
- **bloqué** : pertinent, mais il manque une dépendance (outil, connecteur) ; la dépendance est nommée.
- **non retenu** : hors du domaine de LEKA, ou outil du développeur et non capacité pour un client.

Pourquoi si peu de retenus : LEKA vend la connaissance du système d'information d'une
entreprise et les décisions qu'elle permet. L'essentiel de ces dépôts outille un développeur
dans son éditeur — langages, frameworks, hooks, mémoire de session, design d'interface. Utile
à notre équipe, pas une capacité qu'un client achète. Aucun n'est un « produit par skill ».

## 4. Matrice source → capacité LEKA (éléments retenus)

Une ligne par capacité LEKA touchée ; ses sources externes y sont rattachées. Le contrat
(entrées, sorties, outils, prérequis) est celui de l'agent LEKA tel qu'il est enregistré
aujourd'hui — l'enrichissement ne le change pas.

| Identifiant canonique | Nom public | Type | Objectif | Déclencheurs d'intention | Entrées | Sorties | Outils · permission | Dépendances | Sources rattachées (méthode) | Limites | Statut réel | Tests |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `documentation-assistant` | Assistant de documentation | agent (read_only, risque low) | Use when someone wants to know how well something is documented, or wants a first draft of its documentation built from what LEKA knows — never invented. | goals [find_knowledge] ; kinds [knowledge] | `sujet` (facultatif) | analysis ([markdown]) | [search_entities, read_entity] · skills [documentation-coverage] · permission `agent:run` | sources ["confluence\|microsoft_365\|notion\|google_workspace\|guru\|slab"] | ECC `architecture-decision-records` (skill)<br>ECC `docs-governance` (skill)<br>ECC `living-docs-governance` (skill)<br>ECC `doc-updater` (agent)<br>gstack `document-generate` (skill)<br>gstack `document-release` (skill) | Premier jet d'ADR (contexte, options, décision) à partir de ce que LEKA sait. Écart entre la documentation et la réalité, fraîcheur, responsable de chaque document. Audit de la documentation d'une release ; génération limitée à un premier jet, sans écriture dans les dépôts. | agent active v1.1.0 ; enrichissement en PR #256 (v1.2.0), à merger | routage testé (#251) ; méthode testée (#256) |
| `architecture-analysis` | Analyse d'architecture | agent (read_only, risque low) | Use when someone wants the architecture of an application or a service explained — what it is made of, what it depends on, what depends on it, where the weak po | goals [map_dependencies, assess_impact] ; kinds [dependency] | `sujet` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, dependencies] · skills [blast-radius] · permission `agent:run` | sources [] | ECC `change-impact` (skill)<br>ECC `architect` (agent)<br>ECC `code-architect` (agent)<br>ECC `code-explorer` (agent) | Déjà couvert par le skill LEKA `blast-radius` ; on garde la méthode « impact prévu puis comparé au réel ». Présentation des compromis et des alternatives, inconnues marquées « non vérifié ». | agent active v1.1.0 ; enrichissement en PR #255 (v1.2.0), à merger | routage testé (#251) ; méthode testée (#255) |
| `data-analysis` | Analyse des données | agent (read_only, risque low) | Use when someone asks about data — where it lives, which applications read or write it, who owns it, where it flows — from the databases and the company model. | goals [map_dependencies, find_owner] ; kinds [dependency, ownership] | `sujet` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, dependencies] · skills [data-landscape] · permission `agent:run` | sources ["postgresql\|mysql\|mariadb\|sqlserver\|oracle\|mongodb\|supabase"] | ECC `database-migrations` (skill)<br>ECC `database-reviewer` (agent) | Risque d'une migration (verrouillage, réversibilité), données sensibles exposées. | agent active v1.1.0 ; enrichissement en PR #261 (v1.2.0), à merger | routage testé (`test_agent_library.py`) ; méthode testée (#261) |
| `release-analysis` | Analyse de release | agent (read_only, risque low) | Use when someone wants a release or a deployment analysed — what went out, what it touched, what happened after it — or the risk of the next one assessed. | goals [find_change, assess_impact] ; kinds [change] | `release` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, what_happened, dependencies] · skills [delivery-metrics, change-review] · permission `agent:run` | sources ["github\|gitlab\|bitbucket"] | ECC `deployment-patterns` (skill)<br>ECC `production-audit` (skill) | Préparation au retour arrière, contrôles de santé, critères de prêt pour la production. | agent active v1.1.0 ; enrichissement en PR #259 (v1.2.0), à merger | routage testé (`test_agent_library.py`) ; méthode testée (#259) |
| `infrastructure-analysis` | Analyse d'infrastructure | agent (read_only, risque low) | Use when someone wants to understand the infrastructure behind a service or an environment — where it runs, on which accounts and resources, what is shared, wha | goals [map_dependencies, assess_impact] ; kinds [dependency] | `sujet` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, dependencies] · skills [infrastructure-inventory] · permission `agent:run` | sources ["aws\|azure\|gcp"] | ECC `kubernetes-patterns` (skill) | Sondes, limites de ressources, RBAC — sur les ressources que les sources cloud remontent. | agent active v1.1.0 ; enrichissement en PR #260 (v1.2.0), à merger | routage testé (#251) ; méthode testée (#260) |
| `security-review` | Revue de sécurité | agent (read_only, risque low) | Use when someone asks whether an application, a service or its infrastructure is exposed — sensitive data it holds, what reaches it, who owns it, what is undocu | goals [check_compliance, assess_impact] ; kinds [compliance] | `sujet` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, dependencies] · skills [security-posture] · permission `agent:run` | sources [] | ECC `security-reviewer` (agent)<br>gstack `cso` (skill) | Liste OWASP / secrets / authentification, appliquée à l'exposition et aux données sensibles connues du modèle, pas au code source. Méthode d'audit (constats vérifiables, faux positifs écartés) ; la partie reproduction et correctif est exclue (exécution). | agent active v1.1.0 ; enrichissement en PR #253 (v1.2.0), à merger | routage testé (`test_agent_library.py`) ; méthode testée (#253) |
| `test-analysis` | Analyse des tests | agent (read_only, risque low) | Use when someone asks what should be tested before or after a change or a release — what it touches, what depends on it, what broke recently — from the company  | goals [assess_impact, investigate] ; kinds [change] | `sujet` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, what_happened, dependencies] · skills [test-scope] · permission `agent:run` | sources ["github\|gitlab\|bitbucket"] | ECC `test-collaboration` (skill)<br>ECC `pr-test-analyzer` (agent)<br>gstack `test-audit` (skill) | Couverture jugée par comportement et par risque, pas par pourcentage. Repérer les tests de faible valeur ou en double — limité à ce que les sources CI remontent. | agent active v1.1.0 ; enrichissement en PR #257 (v1.2.0), à merger | routage testé (`test_agent_library.py`) ; méthode testée (#257) |
| `build-fixer` | Réparation de build | agent (proposes_action, risque medium) | Use when a build or a pipeline is broken and someone wants the likely reason and a proposed fix — proposed only, never applied: a person decides. | goals [investigate, explain_cause] ; kinds [diagnose] | `build` (facultatif) | proposal ([markdown]) | [search_entities, read_entity, what_happened] · skills — · permission `agent:run` | sources ["github\|gitlab\|bitbucket"] | ECC `build-error-resolver` (agent) | Règle « diff minimal, aucun changement d'architecture » pour la correction proposée. | agent active v1.0.0 ; enrichissement en PR #254 (v1.1.0), à merger | routage testé (`test_agent_library.py`) ; méthode testée (#254) |
| `code-review` | Revue de code | agent (read_only, risque low) | Use when someone asks for a review of a pull request or a recent change to a repository — what it touches, what it risks, who should look at it — from what the  | goals [investigate, assess_impact] ; kinds [change] | `changement` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, what_happened] · skills [change-review, repository-profile] · permission `agent:run` | sources ["github\|gitlab\|bitbucket"] | ECC `code-reviewer` (agent)<br>gstack `review` (skill) | Échelle de sévérité des constats et format d'un constat ; LEKA ne lit pas le diff ligne à ligne, la méthode s'applique à ce que disent les sources. Liste de contrôle avant merge (périmètre qui dérive, migrations, appels externes) appliquée aux PR connues. | agent active v1.1.0 ; enrichissement en PR #252 (v1.2.0), à merger | routage testé (#251) ; méthode testée (#252) |
| `debug-assistant` | Aide au débogage | agent (read_only, risque low) | Use when a service misbehaves now — errors, slowness, failures — and someone wants the likely causes ranked: what changed, what it depends on, what happened aro | goals [explain_cause, investigate] ; kinds [diagnose] | `symptome` (facultatif) | analysis ([markdown]) | [search_entities, read_entity, dependencies, what_happened] · skills [incident-history] · permission `agent:run` | sources [] | gstack `investigate` (skill) | « Pas de correctif sans cause racine » : hypothèses listées, éliminées une à une, preuves citées. | agent active v1.1.0 ; enrichissement en PR #258 (v1.2.0), à merger | routage testé (#251) ; méthode testée (#258) |

### Déjà couvert, doublons, nouvelle capacité

| Source | Élément | Décision | Côté LEKA | Pourquoi |
| --- | --- | --- | --- | --- |
| ECC | `blueprint` (skill) | déjà couvert | moteur d'intentions | Comprendre une demande floue et la transformer en plan vérifiable : c'est l'étape « Votre intention → Analyse » (LEKA-385, LEKA-439). |
| ECC | `github-ops` (skill) | déjà couvert | connecteurs GitHub / Jira | Lecture des issues et PR par les connecteurs ; les opérations d'écriture sont exclues. |
| ECC | `intent-driven-development` (skill) | déjà couvert | moteur d'intentions | Comprendre une demande floue et la transformer en plan vérifiable : c'est l'étape « Votre intention → Analyse » (LEKA-385, LEKA-439). |
| ECC | `jira-integration` (skill) | déjà couvert | connecteur Jira | Lecture des tickets par le connecteur ; l'écriture (statut, commentaire) serait une action, hors périmètre. |
| ECC | `product-capability` (skill) | déjà couvert | moteur d'intentions | Comprendre une demande floue et la transformer en plan vérifiable : c'est l'étape « Votre intention → Analyse » (LEKA-385, LEKA-439). |
| ECC | `project-flow-ops` (skill) | déjà couvert | connecteurs GitHub / Jira | Lecture des issues et PR par les connecteurs ; les opérations d'écriture sont exclues. |
| ECC | `security-review` (skill) | déjà couvert | agent security-review | Checklist au niveau du code (injection SQL, XSS, CSRF, validation des entrées) que LEKA ne lit pas ; les catégories OWASP au niveau du système viennent déjà de l'agent `security-reviewer`, rattaché à security-review. |
| ECC | `cpp-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `dart-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `django-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `go-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `java-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `kotlin-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `planner` (agent) | déjà couvert | moteur d'intentions | Comprendre une demande floue et la transformer en plan vérifiable : c'est l'étape « Votre intention → Analyse » (LEKA-385, LEKA-439). |
| ECC | `pytorch-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `react-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `rust-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| ECC | `swift-build-resolver` (agent) | doublon | build-fixer | Variante par langage de build-fixer, qui est déjà générique. |
| gstack | `retro` (skill) | nouvelle capacité | workflow « Rétrospective de période » (à construire) | Ce qui est parti, ce qui a cassé, les indicateurs DORA d'une équipe sur une période : un workflow sur `delivery-metrics` + `incident-history`, pas un agent. Planifié, non vendable. |
| gstack | `spec` (skill) | déjà couvert | moteur d'intentions | Même rôle que la compréhension d'intention de LEKA. |

### Bloqués, et ce qui les débloquerait

| Dépendance manquante | Éléments | Ce qui débloquerait |
| --- | --- | --- |
| Lecture ou exécution du code source : les agents en lecture seule n'ont pas d'outil de lecture de fichiers. | `benchmark`, `security-bounty-hunter`, `performance-optimizer`, `silent-failure-hunter` | Même décision (`read_file`) pour la lecture ; l'exécution reste exclue. |
| Appel HTTP en direct après déploiement : LEKA ne lit jamais un outil en direct, seulement ses sources. | `canary-watch` | Exclu par principe : LEKA lit ses sources, jamais un outil en direct. |
| Aucun connecteur d'équipements réseau (routeurs, commutateurs). | `cisco-ios-patterns`, `netmiko-ssh-automation`, `network-bgp-diagnostics`, `network-config-validation`, `network-interface-health`, `network-architect`, `network-config-reviewer`, `network-troubleshooter` | Un connecteur d'équipements réseau (hors feuille de route). |
| Écrire dans Grafana / SigNoz : LEKA lit ses sources, il n'y crée rien. | `dashboard-builder` | Exclu : ce serait une action, et LEKA n'écrit pas dans les outils du client. |
| Revue de code ligne à ligne pour un langage : les agents en lecture seule n'ont pas d'outil de lecture du code. | `cpp-reviewer`, `csharp-reviewer`, `django-reviewer`, `fastapi-reviewer`, `flutter-reviewer`, `fsharp-reviewer`, `go-reviewer`, `java-reviewer`, `kotlin-reviewer`, `mle-reviewer`, `php-reviewer`, `python-reviewer`, `rag-pipeline-reviewer`, `react-reviewer`, `ruby-reviewer`, `rust-reviewer`, `swift-reviewer`, `typescript-reviewer`, `vue-reviewer` | Donner `read_file` aux agents de revue (aujourd'hui seul `code-change` l'a) : décision de sécurité, à trancher avec Haitam. |
| Exécution (navigateur, tests, linters) : aucun outil d'exécution n'est offert aux agents. | `benchmark`, `canary`, `health` | Exclue par principe : les agents n'exécutent rien. |

### Non retenus, par motif

| Motif | Nombre |
| --- | --- |
| Outillage de l'agent de développement (Claude Code, hooks, mémoire, orchestration) : pas une capacité pour un client. | 133 |
| Hors du domaine de LEKA (connaissance du système d'information d'une entreprise). | 114 |
| Méthode d'écriture de code pour un langage ou un framework ; LEKA n'écrit du code que par `code-change`, qui n'est pas étendu ici. | 84 |
| Conception ou test d'interface dans un navigateur ou sur un appareil : outil de l'équipe, et l'exécution n'est pas offerte aux agents. | 28 |
| Méthode d'interface et d'animation pour l'équipe front : utile à LEKA comme outil de développement, pas comme capacité vendue à un client. | 15 |

La liste complète des 454 éléments, avec la décision et le motif de chacun, est en annexe :
[`agents-inventory-sources.md`](agents-inventory-sources.md).

## 5. Une seule source de vérité : ce qui est public, vendable, testé

Ce que disent aujourd'hui les trois endroits qui doivent dire la même chose :

| | `agents/registry.yaml` | `api/leka/billing/catalogue.yaml` | Page Capacités |
| --- | --- | --- | --- |
| Agents actifs | 13 `active`, 3 `draft` (`map-service-ownership`, `detect-undocumented-dependency`, `correlate-deploy-with-latency`) | 2 `core_agents`, 10 agents `add_ons` | n'affiche par défaut que les cycles `active` et `deprecated` : un brouillon n'y apparaît pas |
| Vendable | — | `add_ons.available: false` : rien n'est en vente | pas de parcours d'achat |
| Bundles | — | `bundles: []` | aucun |

Constats :

1. **Aucun bundle n'existe** et **rien n'est en vente** (`available: false`) : il n'y a pas de
   composition de bundle à corriger. C'est cohérent avec « vendus seulement s'ils sont disponibles et testés ».
2. **Les 10 agents prévus en vente sont tous `active`**, mais 5 n'avaient aucun test de routage :
   `code-review`, `architecture-analysis`, `documentation-assistant`, `debug-assistant` et
   `infrastructure-analysis`. Ils en ont un depuis #251 (à merger) ; ils ne devraient pas
   devenir vendables avant.
3. **Aucun élément externe ne devient public par cet inventaire** : les enrichissements
   modifient des agents déjà publics ; la seule nouvelle capacité est planifiée, donc masquée.

## 6. Contradictions avec les règles commerciales du ticket

Le ticket demande de ne pas contredire LEKA-446. Or le catalogue actuel contredit deux règles
du ticket. Ce n'est pas à cet inventaire de trancher : **décision à prendre par Karim, dans LEKA-446**.

| Règle du ticket | Ce que dit `catalogue.yaml` aujourd'hui |
| --- | --- |
| « Aucun agent inclus dans un abonnement. » | `core_agents` : `application-architecture` et `test-analysis` sont « inclus dans chaque plan, dans sa capacité IA ». |
| « La capacité IA est incluse dans le quota ; elle n'est pas vendue séparément. » | Une section décrit de la « capacité IA achetée en plus d'un plan », par packs (tailles et prix encore à décider). |

Les autres règles sont déjà tenues : aucun dépassement facturé automatiquement (« at the limit,
billable usage pauses »), aucun achat sans parcours explicite (`available: false`). Aucun prix
n'est proposé ici pour un skill externe : les enrichissements n'ont pas de prix propre.

## 7. Suite

1. **Décision LEKA-446** sur les deux contradictions ci-dessus.
2. **Tests de routage** — en PR #251 — pour les 5 agents qui n'en avaient pas, dans `test_agent_library.py` —
   à caler sur LEKA-439 (routage par objectif, contexte, droits, prérequis et risque).
   Un cas par agent qui doit être choisi, et un cas qui ne doit pas l'être (comme
   « une question sur un build cassé ne va jamais au réparateur »).
3. **Enrichissements** — en PR #252 à #261, une par agent, empilées : la méthode réécrite dans
   ses instructions, une ligne dans `THIRD_PARTY_LICENSES.md`, le `version` de l'agent augmenté
   (le catalogue refuse un agent modifié sans nouvelle version), et un test qui vérifie que la
   méthode est dans ses instructions. Que sa sortie la suive avec le vrai modèle reste à
   comparer, avant et après, sur des questions réelles.
4. **« Rétrospective de période »** : à valider côté produit avant d'être construite ; tant
   qu'elle n'est ni enregistrée ni testée, elle n'apparaît nulle part.
5. **Lecture du code par les agents de revue** (`read_file`) : débloquerait les 19 revues par langage ;
   décision de sécurité à prendre avec Haitam, pas dans ce ticket.
