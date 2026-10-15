# Matrice de migration UX/UI — LEKA-453

Sprint « Refonte UX UI » (LEKA-452). Ce que LEKA fait aujourd'hui, prouvé par
le code, et où chaque fonctionnalité va dans la nouvelle UX : conservée,
déplacée, remplacée, manquante ou à arbitrer.

**Statut (Karim, 15/10) : validée comme base de travail, pas encore comme
matrice finale.** Les écarts non résolus restent tracés ci-dessous ; la
matrice ne sera finale qu'une fois les fonctionnalités manquantes ou à
arbitrer traitées (parcours d'achat des agents et bundles, limites de plan,
droits).

## Comment la lire

- **Source de l'existant : le code**, pas les maquettes (consigne de Karim,
  LEKA-453). Les routes viennent de `web/app/**/page.tsx`, les API et leurs
  permissions de l'application elle-même (son schéma OpenAPI et ses
  dépendances `require_permission`), les tests des fichiers présents dans
  `web/components/**/*.test.tsx`, `web/e2e/*.spec.ts` et `api/tests/`.
- **Générée**, pas recopiée : `gen_matrix.py` lit le dépôt ; seules les
  colonnes de jugement (destination, traitement, justification) sont écrites
  à la main. « Vérifiée (tests existants) » veut dire : la route existe et au
  moins un test du dépôt l'exerce aujourd'hui — c'est le test de
  non-régression à repasser après migration. Un test listé passe par cet
  écran, ce composant ou ces routes d'API : il ne prouve pas à lui seul
  chaque sous-fonction de la ligne — la recette de chaque écran migré la
  rejoue (LEKA-455 à 460). « À vérifier » : aucun test trouvé, à prouver
  avant de déclarer la ligne conservée. La colonne API compte les routes
  sous le préfixe que l'écran appelle ; elle les nomme, sans dire qu'il les
  appelle toutes.
- **Traitements** : *Conservée* (même fonction, éventuellement re-présentée
  dans l'écran cible), *Déplacée* (vit ailleurs dans la nouvelle navigation),
  *Remplacée* (la cible la refait autrement, la fonction reste),
  *Manquante* (demandée par le sprint, absente du code), *À arbitrer*
  (décision produit nécessaire). **Aucune suppression n'est proposée.**
- **Destinations** : ① Accueil (LEKA-456), ② Historique (LEKA-457),
  ③ Détail d'une intention (LEKA-458), ④ Mon environnement (LEKA-459),
  ⑤ Agents & Bundles (LEKA-460), *Shell* (LEKA-455), *Hors maquette*
  (accès conservé par la navigation, LEKA-455).

## Blocages et éléments non vérifiés

| # | Blocage | Effet | Qui lève |
|---|---|---|---|
| B1 | ~~4 maquettes sur 5 absentes de Jira~~ — **constat périmé** : selon Karim (15/10), les cinq maquettes sont jointes aux tickets LEKA-456 à 460. Les destinations ci-dessous suivent encore les descriptions des tickets : elles restent à confronter aux maquettes jointes. | Destination visuelle fine à revoir écran par écran (LEKA-456 à 460). | Équipe : confronter chaque ligne à sa maquette |
| B2 | **Agents inclus — tranché le 15/10** : les agents fondamentaux sont inclus selon le plan CORE ; les agents spécialisés et les bundles restent payants. **Non résolu** : la liste des agents inclus par plan ; le code (#292) n'en inclut toujours aucun (Free : aucun agent ; Starter et au-dessus : à l'achat). | Matrice agents × plans proposée à Karim, construite depuis le registre et les droits configurés. | Karim : valider la matrice ; puis LEKA-454 |
| B3 | **Stripe** : en production, `stripe-sync` lancé le 15/10 (prix annuels −30 % et coupon `leka_launch_20_12m` créés). **Non résolu** : pas de clé de test en local ; agents/bundles vendus au prix du catalogue envoyé au checkout (#292, pas encore déployé en production) ; aucun test de bout en bout paiement → droits. | Price IDs de test et preuve checkout → droits : « à vérifier ». | Bilal : clés de test ; LEKA-461 |
| B4 | ~~Changements non mergés~~ — **levé** : la démo (#280) et LEKA-448 (#276) sont sur main depuis le 15/10. Les routes de la démo ne sont pas encore comptées : régénérer la matrice. | — | Régénération |

## Écarts commerciaux : règles canoniques du sprint → code actuel

Mis à jour le 15/10 après #287 (remises), #292 (agents payants, quotas au
catalogue) et les décisions de Karim. Chaque écart reste à reprendre dans
LEKA-461 (source de vérité), LEKA-454 (droits) ou LEKA-463 (quotas).

| Règle canonique (sprint) | Code / catalogue aujourd'hui (`api/leka/billing/catalogue.yaml`, `core/settings/credits.py`) | Écart | Ticket |
|---|---|---|---|
| Plans HT : Free 0, Starter 59, Growth 179, Business 599 €, Enterprise sur devis | 0 / 5 900 / 17 900 / 59 900 centimes, Enterprise `null` | ✅ conforme | — |
| Annuel : −30 % sur 12 mensualités (Starter 495,60, Growth 1 503,60, Business 5 031,60 €/an) | `annual_discount_percent: 30` (#287), prix Stripe de production créés | ✅ conforme | LEKA-461 |
| Lancement : −20 % sur le mensuel 12 mois, non cumulable avec l'annuel | `launch_offer: {percent: 20, months: 12, intervals: [month]}` (#287), coupon `leka_launch_20_12m` | ✅ conforme | LEKA-461 |
| Essai | Growth 14 jours, carte requise (LEKA-446) | ⚠️ non mentionné par les règles du sprint : à confirmer | LEKA-461 |
| Quotas : Free 10, Starter 100, Growth 500, Business 2 000 analyses standard/mois | Crédits IA : 200 / 2 000 / 10 000 / 40 000 | ⚠️ exactement ×20 : cohérent si une analyse standard = 20 crédits, **non mesuré** (banc LEKA-447 non lancé avec le vrai modèle) | LEKA-461 / 463 |
| Utilisateurs / sources : Free 1/3, Starter 1/5, Growth 5/15, Business 15/30 | Valeurs au catalogue (`quotas`, #292, provisoires) ; appliquées par le serveur dans #288, **pas encore mergée** (conflit avec #292 à résoudre entre devs) | ⚠️ en cours | LEKA-463 |
| Règles d'alerte : Starter 5, Growth 20, Business 100 ; workflows : Growth 10, Business 50 | Valeurs au catalogue (`quotas`, #292). Aucune création de règle d'alerte ni de workflow par un workspace : rien à compter | ⏸ reporté (Karim, 15/10) : appliqué avec les fonctions de création, via des tickets dédiés ; ne pas l'annoncer comme opérationnel | tickets à créer |
| Agents fondamentaux inclus selon le plan ; packs spécialisés payants | Tranché (Karim, 15/10). Code : aucun agent inclus — Free n'en lance aucun, Starter et au-dessus à l'achat (#292) | ❌ liste par plan à valider (B2) | LEKA-454 |
| Agents Standard 9, Spécialisé 15, Expert 25 €/mois HT | `add_ons.tiers` 900 / 1 500 / 2 500, 13 agents classés (#292, « à valider ») | ⚠️ prix présents, non validés | LEKA-461 |
| Bundles : Engineering 59, Ship Safe 79, Incident Response 89, Security & Reliability 69, Frontend Craft 29 € | 5 bundles au catalogue (#292) : engineering 45, architecture 49, ship-safe 52, incident-response 49, security-reliability 42 € ; Frontend Craft absent | ❌ prix et liste différents | LEKA-461 / 460 |
| Agents/bundles mensuels, renouvellement automatique, pas d'annuel | Checkout d'agent et de bundle, droits `AgentEntitlement` (#292) | ⚠️ à prouver en bout de chaîne (paiement confirmé → droit) | LEKA-461 / 462 |
| Capacité épuisée : alerte + proposition d'upgrade, pas de dépassement facturé | `automatic_overage: false` ; faisabilité `over_quota` → « Passer au forfait… » ; alertes de crédits 80 % / 100 % | ✅ conforme (bouton de paiement visible même si Stripe n'est pas configuré : à vérifier) | LEKA-462 / 463 |
| Économies de bundle affichées seulement si démontrables | Rien d'affiché | ✅ (rien à corriger tant qu'aucun bundle) | LEKA-460 |
| Price IDs, produits Stripe, droits accordés après paiement confirmé | Plans : prix de production créés le 15/10. Agents/bundles : pas de Price ID, prix du catalogue envoyé au checkout (`price_data`, #292) | 🔒 non prouvé (B3) | LEKA-461 |
| La démo garde son quota Free, isolé du workspace réel, côté serveur (Karim, 15/10) | La démo est un workspace à part, ses crédits comptés à part ; test `test_demo_credits.py` | ✅ conforme | LEKA-449 |

## Rapprochement du catalogue d'agents (maquette « Agents & Bundles(3) » → registre)

Registre réel : `agents/registry.yaml` — **13 agents actifs, 3 brouillons**.
Catalogue de Karim : **60 agents** en 12 catégories + noms cités seulement
dans les bundles (*Migration Planner*, *Reliability Analyst*). Aucun agent
fantôme n'est créé : chaque nom sans équivalent est « absent ».

| Agent de la maquette (niveau, prix) | Agent du registre | Statut runtime | Commercialisable aujourd'hui |
|---|---|---|---|
| Architect (Expert, 25 €) | `application-architecture` (livrables PDF/PPTX) | actif | non (beta, pas de prix ni de produit Stripe) |
| Codebase Explorer (9 €) | `architecture-analysis` (proche, à confirmer) | actif | non |
| Code Reviewer (9 €) | `code-review` | actif | non |
| Test Strategist (9 €) | `test-analysis` | actif | non |
| Bug Investigator (15 €) | `debug-assistant` | actif | non |
| Incident Investigator (25 €) | `incident-investigation` | actif | non |
| Build Error Resolver (15 €) | `build-fixer` | actif | non |
| Security Reviewer (25 €) | `security-review` | actif | non |
| Data Analyst (15 €) | `data-analysis` | actif | non |
| Deployment & Release Analyst (25 €) / « Deployment & Release » (bundle) | `release-analysis` | actif | non — nommage à arbitrer |
| Infrastructure Architect / Cloud Specialist (15 €) | `infrastructure-analysis` (couvre les deux en partie) | actif | non — découpage à arbitrer |
| Documentation Specialist (9 €) | `documentation-assistant` | actif | non |
| Refactoring Specialist / Code Simplifier (15 €) | `code-change` (diff → PR) — proche, à confirmer | actif | non |
| Dependency Analyst (15 €) | `detect-undocumented-dependency` (partiel) | brouillon | non |
| Performance Analyst (25 €) | `correlate-deploy-with-latency` (partiel) | brouillon | non |
| — | `map-service-ownership` | brouillon | sans équivalent dans la maquette |
| UI Quality Reviewer, Accessibility Auditor, Design Reviewer, Motion & Animation Specialist, Prototype Designer | skills Emil Kowalski + `leka-designer` dans `.claude/skills/` (LEKA-447) | **outils d'équipe Claude Code, pas des agents LEKA** | non — bundle Frontend Craft entièrement absent du runtime |
| Les 41 autres (Product Strategist, Spec Analyst, Product Reviewer, Research Specialist, Test Generator, QA Analyst, Regression Analyst, E2E Testing Specialist, Change Impact Analyst, Silent Failure Hunter, Vulnerability Scanner, Compliance Auditor, Security Advisor, Database Specialist, API Design Reviewer, Benchmark Analyst, iOS/Android/React/Flutter Specialist, Mobile App Reviewer, Canary & Monitoring Specialist, Container & Kubernetes Specialist, Network Architect, Network Config Reviewer, Network Troubleshooter, System Administrator, Monitoring Specialist, Spec Miner, Context Manager, Knowledge Organizer, Diagram Specialist, Planner, Auto Plan, Agent Evaluator, Harness Optimizer, Learning Specialist, Migration Planner, Reliability Analyst) | **absents** | — | non |

Note : des capacités LEKA « règles » couvrent une partie de certains noms
sans être des agents vendables (Changements/Impact pour *Change Impact
Analyst*, Migration pour *Migration Planner*, Conformité pour *Compliance
Auditor*) — à arbitrer : agent ou capacité incluse.

### Bundles : composition de la maquette → disponibilité

| Bundle (prix) | Agents | Présents dans le runtime | Manquants |
|---|---|---|---|
| Engineering (59 €, 7) | Architect, Codebase Explorer, Code Reviewer, Test Strategist, Test Generator, Regression Analyst, Change Impact Analyst | 4 (Architect, Codebase Explorer*, Code Reviewer, Test Strategist) | Test Generator, Regression Analyst, Change Impact Analyst |
| Ship Safe (79 €, 6) | API Design Reviewer, Migration Planner, Test Strategist, Regression Analyst, Deployment & Release, Security Reviewer | 3 (Test Strategist, Deployment & Release, Security Reviewer) | API Design Reviewer, Migration Planner, Regression Analyst |
| Incident Response (89 €, 6) | Incident Investigator, Bug Investigator, Dependency Analyst, Performance Analyst, Reliability Analyst, Change Impact Analyst | 2 (+2 brouillons partiels) | Reliability Analyst, Change Impact Analyst ; Dependency/Performance en brouillon |
| Security & Reliability (69 €, 5) | Security Reviewer, Dependency Analyst, API Design Reviewer, Database Specialist, Reliability Analyst | 1 (+1 brouillon) | API Design Reviewer, Database Specialist, Reliability Analyst |
| Frontend Craft (29 €, 4) | UI Quality Reviewer, Accessibility Auditor, Design Reviewer, Motion & Animation | 0 (outils d'équipe seulement) | les 4 |

\* correspondance à confirmer. **Aucun bundle n'est aujourd'hui composable
avec des agents tous livrés** : conformément à LEKA-460, ils doivent
s'afficher « à venir », jamais achetables.

## Matrice fonctionnelle

<!-- matrix:start -->

_Générée par `gen_matrix.py` à partir du code (main `43ebe39`) : 90 fonctionnalités, 313 routes d'API, 33 pages._

**Traitements** : Conservée 74, Déplacée 4, Manquante 3, Remplacée 7, À arbitrer 2  
**États** : Manquante 3, Vérifiée (tests existants) 83, Vérifiée côté API seulement 3, À vérifier 1

### Accueil

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ACC-01 | Salutation, date, synthèse « ce qui demande attention » | /overview | overview/overview.tsx | 90 : /intelligence/activity, /intelligence/analyzers, /intelligence/authority-rules, /intelligence/authority-rules/{rule_id} … | audit:read, intention:approve, intention:create, intention:read, source:read, workspace:read | — | ① Accueil | LEKA-456 | Conservée | Bloc d'en-tête de la maquette Accueil (à confronter au template). | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+24) | Vérifiée (tests existants) |
| ACC-02 | Composer d'intention + 4 suggestions | /overview | overview/overview.tsx, intentions/compact-composer.tsx | 35 : /intentions, /intentions/brief, /intentions/counts, /intentions/understand … | access:read, intention:approve, intention:create, intention:read | Modèle de langage (compréhension) | ① Accueil | LEKA-456 | Conservée | Point d'entrée principal ; garder l'envoi vers /intentions/new?q=. | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+18) | Vérifiée (tests existants) |
| ACC-03 | Premiers pas (LEKA-445) + entrée démo (LEKA-451) | /overview | overview/first-steps.tsx | 18 : /intentions/counts, /sources, /sources/{source_id}, /sources/{source_id}/activate … | intention:read, source:manage, source:read | Sources | ① Accueil | LEKA-456 | Conservée | Absent possible de la maquette : à garder tant qu'aucune source n'est lue. | overview/first-steps.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_audit_api.py; test_roles_policies_api.py; test_source_settings_api.py (+10) | Vérifiée (tests existants) |
| ACC-04 | « À valider » (décisions, candidats) | /overview | overview/overview.tsx | 17 : /decisions, /decisions/delegations, /decisions/delegations/{delegation_id}/revoke, /decisions/exceptions … | intention:approve, intention:read, policy:manage, workspace:read, workspace:update | — | ① Accueil | LEKA-456 | Conservée | Lien vers /approvals conservé. | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; approvals.spec.ts; auth.spec.ts; intention-decisions.spec.ts; test_governance_api.py; test_intention_decisions_api.py; test_roles_policies_api.py (+8) | Vérifiée (tests existants) |
| ACC-05 | « Ce qui ne va pas » (incidents, sources en échec, conflits) | /overview | overview/overview.tsx | 79 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, source:manage, source:read, workspace:read | Sources (incidents, santé) | ① Accueil | LEKA-456 | Conservée |  | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+24) | Vérifiée (tests existants) |
| ACC-06 | Intentions en cours | /overview | overview/overview.tsx | 35 : /intentions, /intentions/brief, /intentions/counts, /intentions/understand … | access:read, intention:approve, intention:create, intention:read | — | ① Accueil | LEKA-456 | Conservée |  | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+18) | Vérifiée (tests existants) |
| ACC-07 | Activité récente (fil) | /overview | overview/overview.tsx | 2 : /intelligence/activity, /intentions/{intention_id}/timeline | intention:read, workspace:read | — | ① Accueil | LEKA-456 | Conservée |  | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+19) | Vérifiée (tests existants) |
| ACC-08 | Alertes (payantes) / limite du plan Free | /overview | overview/overview.tsx | 2 : /billing/subscription, /monitoring | source:read, workspace:read | — | ① Accueil | LEKA-463 | Remplacée | Les règles d'alerte par plan (Starter 5, Growth 20, Business 100) n'existent pas dans le code : à construire. | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_monitoring_api.py (+6) | Vérifiée (tests existants) |
| ACC-09 | Fraîcheur, couverture, sources silencieuses | /overview | overview/overview.tsx | 79 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, source:manage, source:read, workspace:read | Sources | ① Accueil | LEKA-456 | Conservée |  | overview/overview.test.tsx; accessibility.spec.ts; activation.spec.ts; auth.spec.ts; intentions.spec.ts; keyboard.spec.ts; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+24) | Vérifiée (tests existants) |
| ACC-10 | LEKA Insights (analyse de fond) | /overview | insights/leka-insights.tsx | 28 : /intelligence/activity, /intelligence/analyzers, /intelligence/authority-rules, /intelligence/authority-rules/{rule_id} … | intention:approve, intention:create, intention:read, source:read, workspace:read | Modèle de langage | ① Accueil | LEKA-456 | Conservée |  | insights/leka-insights.test.tsx; insights.spec.ts; test_intelligence_change_impact.py; test_intelligence_conflicts_model.py; test_intelligence_engine.py (+5) | Vérifiée (tests existants) |

### Intentions

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HIS-01 | Liste des intentions (statut, parcours, dernière activité) | /intentions | intentions/intentions-list.tsx | 35 : /intentions, /intentions/brief, /intentions/counts, /intentions/understand … | access:read, intention:approve, intention:create, intention:read | — | ② Historique des intentions | LEKA-457 | Conservée |  | intentions/intentions.test.tsx; intentions/journey.test.tsx; intention-journey.spec.ts; intentions.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+13) | Vérifiée (tests existants) |
| HIS-02 | Recherche texte | /intentions | intentions/intentions-list.tsx | 35 : /intentions, /intentions/brief, /intentions/counts, /intentions/understand … | access:read, intention:approve, intention:create, intention:read | — | ② Historique des intentions | LEKA-457 | Conservée |  | intentions/intentions.test.tsx; intentions/journey.test.tsx; intention-journey.spec.ts; intentions.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+13) | Vérifiée (tests existants) |
| HIS-03 | Filtre par phase + compteurs | /intentions | intentions/intentions-list.tsx | 1 : /intentions/counts | intention:read | — | ② Historique des intentions | LEKA-457 | Conservée |  | intentions/intentions.test.tsx; intentions/journey.test.tsx; intention-journey.spec.ts; intentions.spec.ts; keyboard.spec.ts; navigation.spec.ts (+1) | Vérifiée (tests existants) |
| HIS-04 | Filtres agent / source / période, tri | — | — | — | session | — | ② Historique des intentions | LEKA-457 | Manquante | Demandé par LEKA-457, inexistant aujourd'hui (seulement phase + texte). | — | Manquante |
| HIS-05 | Pagination (curseur, « plus ») | /intentions | intentions/intentions-list.tsx | 35 : /intentions, /intentions/brief, /intentions/counts, /intentions/understand … | access:read, intention:approve, intention:create, intention:read | — | ② Historique des intentions | LEKA-457 | Conservée |  | intentions/intentions.test.tsx; intentions/journey.test.tsx; intention-journey.spec.ts; intentions.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+13) | Vérifiée (tests existants) |
| HIS-06 | Archiver / restaurer | /intentions/[intentionId] | intentions/intention-screen.tsx | 2 : /intentions/{intention_id}/archive, /intentions/{intention_id}/restore | intention:approve, intention:create | — | ② Historique des intentions | LEKA-457 | Conservée | Action à exposer aussi depuis la liste si le template la montre. | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; context.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| HIS-07 | Nouvelle intention (formulaire, sources, périmètre, pièce jointe) | /intentions/new | intentions/intention-form.tsx, intentions/intention-composer.tsx | 57 : /context, /context/contract, /context/feedback, /context/intents … | access:read, intention:approve, intention:create, intention:read, source:read | Sources, modèle de langage | ③ Détail d'une intention | LEKA-458 | Conservée | CTA « Nouvelle intention » de la maquette Historique. | intentions/intention-composer.test.tsx; intentions/intention-form.test.tsx; accessibility.spec.ts; forms.spec.ts; intentions.spec.ts; languages.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_context_api_security.py (+18) | Vérifiée (tests existants) |
| HIS-08 | Questions de clarification (brief) | /intentions/new | intentions/brief.tsx | 2 : /intentions/brief, /intentions/{intention_id}/answers | intention:create | Modèle de langage | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/brief.test.tsx; accessibility.spec.ts; forms.spec.ts; intentions.spec.ts; languages.spec.ts; navigation.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+13) | Vérifiée (tests existants) |
| HIS-09 | Historique global de toutes les intentions (timeline) | — (API) | — | 1 : /intention-history | access:read, intention:read | — | ② Historique des intentions | LEKA-457 | Déplacée | API existante sans écran dédié : candidate pour l'Historique. | test_intention_outcomes_api.py | Vérifiée côté API seulement |

### Détail

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DET-01 | Parcours en 5 étapes + note de parcours | /intentions/[intentionId] | intentions/intention-screen.tsx, intentions/journey.tsx | 30 : /intentions/{intention_id}, /intentions/{intention_id}/analyse, /intentions/{intention_id}/analyses, /intentions/{intention_id}/analysis … | access:read, intention:approve, intention:create, intention:read | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-02 | Compréhension (objectif, sujets, périmètre, manques) | /intentions/[intentionId]/overview | intentions/intention-screen.tsx | 31 : /intentions/understand, /intentions/{intention_id}, /intentions/{intention_id}/analyse, /intentions/{intention_id}/analyses … | access:read, intention:approve, intention:create, intention:read | Modèle de langage | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; intentions.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-03 | Faisabilité (capacités, crédits, chemin : changer de plan…) | /intentions/[intentionId]/overview | intentions/feasibility.tsx | 2 : /billing/checkout, /intentions/{intention_id}/feasibility | intention:create, intention:read, workspace:update | Stripe (checkout) | ③ Détail d'une intention | LEKA-462 | Remplacée | Le changement de plan existe ; achat d'agent/bundle absent (add_ons.available: false) ; montants à aligner sur les règles canoniques. | intentions/brief.test.tsx; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-04 | Routage (agent retenu, candidats, écartés) + lancer l'agent | /intentions/[intentionId]/overview | intentions/routing.tsx | 10 : /capabilities, /capabilities/discover, /capabilities/route, /capabilities/summary … | intention:create, intention:read, workspace:read, workspace:update | Runtime agents | ③ Détail d'une intention | LEKA-458 | À arbitrer | Aujourd'hui l'agent est lancé automatiquement (dispatch.py) ; le parcours voulu (proposer → valider en Décision → lancer en Action) est à arbitrer avec Haitam/Karim. | intentions/routing.test.tsx; test_agent_library_api.py; test_agent_runs_api.py; test_capabilities_api.py (+15) | Vérifiée (tests existants) |
| DET-05 | Contexte de l'analyse (éléments, qualité, version, sources) | /intentions/[intentionId]/overview | intentions/intention-screen.tsx | 22 : /context, /context/contract, /context/feedback, /context/intents … | intention:create, intention:read, source:read | Sources | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; accessibility.spec.ts; auth.spec.ts; context.spec.ts; test_context_api_security.py; test_context_engine.py; test_context_intent.py (+8) | Vérifiée (tests existants) |
| DET-06 | Analyse : étapes, capacités mobilisées, lectures, relancer/arrêter | /intentions/[intentionId]/analysis | intentions/analysis-tab.tsx | 3 : /intentions/{intention_id}/analyse, /intentions/{intention_id}/analyses, /intentions/{intention_id}/analysis | intention:create, intention:read | Modèle de langage | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intention-analysis.spec.ts; llm-runtime.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-07 | Résultats : synthèse, constats, causes, confiance, limites, preuves | /intentions/[intentionId]/results | intelligence/explained.tsx, intelligence/findings.tsx | 1 : /intentions/{intention_id}/analysis | intention:read | — | ③ Détail d'une intention | LEKA-458 | Conservée | Inclut LEKA-448 (source non lue pertinente). | intelligence/explained.test.tsx; activation.spec.ts; frame.spec.ts; intention-journey.spec.ts; llm-runtime.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-08 | Recommandations | /intentions/[intentionId]/results | intelligence/explained.tsx | 1 : /intentions/{intention_id}/analysis | intention:read | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | intelligence/explained.test.tsx; activation.spec.ts; frame.spec.ts; intention-journey.spec.ts; llm-runtime.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-09 | Décision : votes, approuver, rejeter, demander des changements, modifier | /intentions/[intentionId]/decision | decisions/intention-decision.tsx, intentions/decision-step.tsx | 14 : /decisions, /decisions/delegations, /decisions/delegations/{delegation_id}/revoke, /decisions/exceptions … | access:read, intention:approve, intention:create, intention:read, policy:manage, workspace:read, workspace:update | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | decisions/decision-governance.test.tsx; decisions/intention-decision.test.tsx; intentions/decision-step.test.tsx; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-10 | Action : plan, étapes, planification, contrôles, exécution | /intentions/[intentionId]/actions | actions/actions-tab.tsx | 6 : /intentions/{intention_id}/plan, /intentions/{intention_id}/plan/cancel, /intentions/{intention_id}/plan/expectations, /intentions/{intention_id}/plan/start … | intention:approve, intention:create, intention:read | Endpoints d'actions (webhooks signés) | ③ Détail d'une intention | LEKA-458 | Conservée |  | actions/actions-tab.test.tsx; intention-journey.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-11 | Vérification du résultat (attendus, constats, conclusion) | /intentions/[intentionId]/actions | actions/actions-tab.tsx | 5 : /intentions/{intention_id}/plan/expectations, /intentions/{intention_id}/verification/check, /intentions/{intention_id}/verification/conclude, /intentions/{intention_id}/verification/expectations/{expectation_id}/report … | intention:approve, intention:read | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | actions/actions-tab.test.tsx; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-12 | Preuves (onglet evidence) | /intentions/[intentionId]/evidence | intentions/intention-screen.tsx | 22 : /context, /context/contract, /context/feedback, /context/intents … | intention:create, intention:read, source:read | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; accessibility.spec.ts; approvals.spec.ts; context.spec.ts; test_context_api_security.py; test_context_engine.py; test_context_intent.py (+6) | Vérifiée (tests existants) |
| DET-13 | Historique de l'intention (timeline) | /intentions/[intentionId]/history | intentions/intention-screen.tsx | 1 : /intentions/{intention_id}/timeline | intention:read | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; intention-journey.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+12) | Vérifiée (tests existants) |
| DET-14 | Livrables des agents (rapport, PDF, PowerPoint) | /intentions/[intentionId]/deliverable | intentions/deliverable.tsx, intentions/agent-work.tsx | 7 : /agent-runs, /agent-runs/{run_id}, /agent-runs/{run_id}/approve, /agent-runs/{run_id}/cancel … | intention:approve, intention:create, intention:read, workspace:read | Runtime agents, stockage objets | ③ Détail d'une intention | LEKA-458 | Conservée | Ajouté le 14/10 (#275). | intentions/agent-work.test.tsx; intentions/deliverable.test.tsx; test_access_control_api.py; test_agent_library_api.py; test_agent_runs_api.py (+8) | Vérifiée (tests existants) |
| DET-15 | Changements de code proposés (diff → pull request) | /intentions/[intentionId] | capabilities/code-changes.tsx | 4 : /code-changes, /code-changes/{change_id}, /code-changes/{change_id}/accept, /code-changes/{change_id}/reject | intention:approve, intention:read | GitHub (écriture PR) | ③ Détail d'une intention | LEKA-458 | Conservée |  | capabilities/code-changes.test.tsx; test_code_changes_api.py | Vérifiée (tests existants) |
| DET-16 | Versions, reformuler, stopper, annuler | /intentions/[intentionId] | intentions/intention-screen.tsx | 30 : /intentions/{intention_id}, /intentions/{intention_id}/analyse, /intentions/{intention_id}/analyses, /intentions/{intention_id}/analysis … | access:read, intention:approve, intention:create, intention:read | — | ③ Détail d'une intention | LEKA-458 | Conservée |  | intentions/analysis-tab.test.tsx; intentions/intentions.test.tsx; intentions/journey.test.tsx; accessibility.spec.ts; activation.spec.ts; forms.spec.ts; test_capabilities_api.py; test_capability_routing_api.py; test_data_protection_intentions.py (+24) | Vérifiée (tests existants) |
| DET-17 | Coût de l'intention (crédits mesurés) | /intentions/[intentionId] | intentions/feasibility.tsx | 2 : /billing/credits, /billing/usage | workspace:read | — | ③ Détail d'une intention | LEKA-458 | Remplacée | Le template demande coût total, périodicité, renouvellement : à confronter. | intentions/brief.test.tsx; test_ai_credits.py; test_billing_api.py | Vérifiée (tests existants) |

### Environnement

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ENV-01 | Vue d'ensemble / jumeau (comptes, couverture, fraîcheur) | /environment | environment/environment-screen.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources | ④ Mon environnement | LEKA-459 | Conservée |  | environment/environment.test.tsx; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-02 | Architecture (dossier, schéma) | /environment?view=architecture | environment/architecture.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources (code) | ④ Mon environnement | LEKA-459 | Conservée |  | environment/architecture.test.tsx; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-03 | Vues Applications, Infrastructure, Données | /environment?view=… | environment/environment-screen.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources | ④ Mon environnement | LEKA-459 | Conservée | Onglets « Services » de la maquette. | environment/environment.test.tsx; accessibility.spec.ts; insights.spec.ts; navigation.spec.ts; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-04 | Dépendances | /environment?view=dependencies | environment/environment-screen.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources | ④ Mon environnement | LEKA-459 | Conservée |  | environment/environment.test.tsx; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-05 | Équipes (organisation) | /environment?view=organisation | environment/environment-screen.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources (GitHub, M365, Google) | ④ Mon environnement | LEKA-459 | Conservée |  | environment/environment.test.tsx; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-06 | Événements (incidents, changements, déploiements) | /environment?view=events | environment/environment-screen.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources (observabilité) | ④ Mon environnement | LEKA-459 | Conservée | Onglet « Incidents » de la maquette. | environment/environment.test.tsx; navigation.spec.ts; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-07 | Domaines métier | /environment?view=domains | environment/environment-screen.tsx | 62 : /knowledge/applications, /knowledge/applications/{entity_id}, /knowledge/architecture, /knowledge/business-capabilities … | audit:read, intention:approve, intention:create, workspace:read | Sources | ④ Mon environnement | LEKA-459 | Conservée |  | environment/environment.test.tsx; navigation.spec.ts; test_access_control_api.py; test_application_landscape.py; test_architecture_model.py (+12) | Vérifiée (tests existants) |
| ENV-08 | Qualité de la connaissance (score, manques, retours) | /environment?view=quality | environment/knowledge-quality.tsx | 3 : /intelligence/quality, /intelligence/quality/scores, /intelligence/quality/scores/{key} | source:read, workspace:read | — | ④ Mon environnement | LEKA-459 | Conservée |  | environment/knowledge-quality.test.tsx; accessibility.spec.ts; context.spec.ts; quality.spec.ts | Vérifiée (tests existants) |
| ENV-09 | Fiche d'une entité (10 onglets) | /environment/[entityType]/[entityId] | environment/entity-sheet.tsx | 10 : /knowledge/entities, /knowledge/entities/{entity_id}, /knowledge/entities/{entity_id}/at, /knowledge/entities/{entity_id}/business … | intention:approve, intention:create, workspace:read | Sources | ④ Mon environnement | LEKA-459 | Conservée | Panneau de détail d'un service de la maquette. | environment/environment.test.tsx; navigation.spec.ts; test_access_control_api.py; test_audit_api.py | Vérifiée (tests existants) |
| ENV-10 | Explorateur du graphe (chemins) | /environment/graph | environment/graph-explorer.tsx | 2 : /knowledge/graph, /knowledge/graph/paths | workspace:read | — | ④ Mon environnement | LEKA-459 | Conservée | Cartographie zoom/recherche de la maquette. | environment/graph-explorer.test.tsx | Vérifiée (tests existants) |
| ENV-11 | Contexte d'une entité (versions, conflits, éléments) | /environment/[entityType]/[entityId]/context | environment/entity-context.tsx | 22 : /context, /context/contract, /context/feedback, /context/intents … | intention:create, intention:read, source:read | — | ④ Mon environnement | LEKA-459 | Conservée |  | environment/entity-context.test.tsx; test_context_api_security.py; test_context_engine.py; test_context_intent.py (+2) | Vérifiée (tests existants) |
| ENV-12 | Recherche globale ⌘K (palette) | toutes | shell/command-palette.tsx | 1 : /knowledge/search | audit:read, workspace:read | — | Shell | LEKA-455 | Conservée |  | shell/command-palette.test.tsx; accessibility.spec.ts; forms.spec.ts; keyboard.spec.ts; knowledge-graph.spec.ts; navigation.spec.ts; test_access_control_api.py (+2) | Vérifiée (tests existants) |

### Sources

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SRC-01 | Liste des sources, santé, synchro | /sources | sources/sources-page.tsx | 17 : /sources, /sources/{source_id}, /sources/{source_id}/activate, /sources/{source_id}/credentials … | source:manage, source:read | Tous les connecteurs | ④ Mon environnement | LEKA-459 | Déplacée | Onglet « Sources » de Mon environnement ; /sources reste joignable. | sources/sources-page.test.tsx; accessibility.spec.ts; custom-connector.spec.ts; keyboard.spec.ts; languages.spec.ts; navigation.spec.ts; test_audit_api.py; test_roles_policies_api.py; test_source_settings_api.py (+6) | Vérifiée (tests existants) |
| SRC-02 | Ajouter une source (assistant, test, périmètre, activation) | /sources | sources/add-source-dialog.tsx | 18 : /connectors/catalog, /sources, /sources/{source_id}, /sources/{source_id}/activate … | source:manage, source:read | 53 connecteurs | ④ Mon environnement | LEKA-459 | Conservée | CTA « Connecter une source » de la maquette. | sources/add-source-dialog.test.tsx; sources/custom-connector.test.tsx; test_audit_api.py; test_roles_policies_api.py; test_source_settings_api.py (+4) | Vérifiée (tests existants) |
| SRC-03 | Connecteur sur mesure (REST, GraphQL, webhook) | /sources | sources/add-source-dialog.tsx | 18 : /connectors/catalog, /sources, /sources/{source_id}, /sources/{source_id}/activate … | source:manage, source:read | API client | ④ Mon environnement | LEKA-459 | Conservée |  | sources/add-source-dialog.test.tsx; sources/custom-connector.test.tsx; test_audit_api.py; test_roles_policies_api.py; test_source_settings_api.py (+4) | Vérifiée (tests existants) |
| SRC-04 | Détail d'une source (config, identifiants, synchro, historique, désactiver, supprimer) | /sources/[sourceId] | sources/source-page.tsx | 15 : /sources/{source_id}, /sources/{source_id}/activate, /sources/{source_id}/credentials, /sources/{source_id}/disable … | source:manage, source:read | Connecteur | ④ Mon environnement | LEKA-459 | Conservée |  | sources/source-page.test.tsx; test_audit_api.py; test_roles_policies_api.py; test_source_settings_api.py (+4) | Vérifiée (tests existants) |
| SRC-05 | Synchroniser maintenant | /sources/[sourceId] | sources/source-page.tsx | 12 : /ingestion/sources/{source_id}/deliveries, /ingestion/sources/{source_id}/extraction, /ingestion/sources/{source_id}/normalisation, /ingestion/sources/{source_id}/parsing … | source:manage, source:read | Connecteur | ④ Mon environnement | LEKA-459 | Conservée |  | sources/source-page.test.tsx; test_sync_schedule.py; test_webhook_deliveries.py | Vérifiée (tests existants) |
| SRC-06 | Accueil d'un workspace : choix des outils + démo | /welcome | sources/welcome-page.tsx | 18 : /connectors/catalog, /sources, /sources/{source_id}, /sources/{source_id}/activate … | source:manage, source:read | Connecteurs | ① Accueil | LEKA-456 | Conservée | Onboarding ; hors maquette mais indispensable. | sources/welcome-page.test.tsx; activation.spec.ts; test_audit_api.py; test_roles_policies_api.py; test_source_settings_api.py (+4) | Vérifiée (tests existants) |
| SRC-07 | Réception de webhooks des sources | — (API) | — | 1 : /webhooks/sources/{source_id} | session | Systèmes clients | Hors maquette | — | Conservée | Aucun écran : pas d'impact UX. | test_route_protection.py; test_webhook_deliveries.py | Vérifiée côté API seulement |

### Capacités

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CAP-01 | Catalogue par domaine, recherche, filtres, favoris, usage | /capabilities | capabilities/catalogue.tsx | 8 : /capabilities, /capabilities/discover, /capabilities/route, /capabilities/summary … | intention:read, workspace:read, workspace:update | — | ⑤ Agents & Bundles | LEKA-460 | Remplacée | Remplacé par la marketplace Agents & Bundles ; les capacités LEKA (règles) doivent rester visibles. | capabilities/catalogue.test.tsx; capabilities.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_agent_library_api.py; test_agent_runs_api.py; test_capabilities_api.py (+3) | Vérifiée (tests existants) |
| CAP-02 | Mes capacités | /capabilities?view=mine | capabilities/catalogue.tsx | 8 : /capabilities, /capabilities/discover, /capabilities/route, /capabilities/summary … | intention:read, workspace:read, workspace:update | — | ⑤ Agents & Bundles | LEKA-460 | Déplacée | « Déjà actif / inclus » de la maquette. | capabilities/catalogue.test.tsx; test_agent_library_api.py; test_agent_runs_api.py; test_capabilities_api.py (+3) | Vérifiée (tests existants) |
| CAP-03 | Configuration (activer/désactiver par workspace) | /capabilities?view=configuration | capabilities/catalogue.tsx | 1 : /capabilities/{key}/settings | workspace:update | — | Hors maquette | LEKA-455 | Déplacée | Gestion admin : à garder dans Paramètres ou un onglet admin du catalogue. | capabilities/catalogue.test.tsx; capabilities.spec.ts; test_agent_library_api.py; test_agent_runs_api.py; test_capabilities_api.py (+3) | Vérifiée (tests existants) |
| CAP-04 | Fiche capacité (entrées, versions, événements, disponibilité) | /capabilities/[capabilityId] | capabilities/capability-detail.tsx | 4 : /capabilities/{key}, /capabilities/{key}/favourite, /capabilities/{key}/settings | workspace:read, workspace:update | — | ⑤ Agents & Bundles | LEKA-460 | Conservée | Détail agent de la maquette. | capabilities/catalogue.test.tsx; llm-runtime.spec.ts; test_agent_library_api.py; test_agent_runs_api.py; test_capabilities_api.py (+3) | Vérifiée (tests existants) |
| CAP-05 | Lancer un agent + exécutions + livrables | /capabilities/[capabilityId] | capabilities/agent-runs.tsx | 7 : /agent-runs, /agent-runs/{run_id}, /agent-runs/{run_id}/approve, /agent-runs/{run_id}/cancel … | intention:approve, intention:create, intention:read, workspace:read | Runtime agents | ⑤ Agents & Bundles | LEKA-460 | Conservée |  | capabilities/agent-runs.test.tsx; test_access_control_api.py; test_agent_library_api.py; test_agent_runs_api.py (+8) | Vérifiée (tests existants) |
| CAP-06 | Workflows (lancer, suivre) | /capabilities/[capabilityId] | capabilities/workflow-runs.tsx | 2 : /workflows, /workflows/{key} | intention:read | Runtime | ⑤ Agents & Bundles | LEKA-460 | Conservée | Quotas de workflows par plan (Growth 10, Business 50) inexistants. | capabilities/workflow-runs.test.tsx; test_workflow_runs_api.py | Vérifiée (tests existants) |
| CAP-07 | Demander une capacité | /capabilities | capabilities/catalogue.tsx | 8 : /capabilities, /capabilities/discover, /capabilities/route, /capabilities/summary … | intention:read, workspace:read, workspace:update | — | ⑤ Agents & Bundles | LEKA-460 | Conservée |  | capabilities/catalogue.test.tsx; test_agent_library_api.py; test_agent_runs_api.py; test_capabilities_api.py (+3) | Vérifiée (tests existants) |
| CAP-08 | Acheter un agent / un bundle | — | — | — | session | Stripe | ⑤ Agents & Bundles | LEKA-460 / 461 / 462 | Manquante | add_ons.available: false, bundles: [], aucune route de checkout agent, aucun Price ID. | — | Manquante |

### Activité

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ACT-01 | Journal d'activité, tendances, filtres | /activity | activity/activity.tsx | 2 : /intelligence/activity, /intention-history | access:read, intention:read, workspace:read | — | Hors maquette | LEKA-455 | Conservée | Hors des 5 maquettes : accès conservé par la navigation. | activity/activity.test.tsx; activity.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_intelligence_evolution_model.py; test_intention_outcomes_api.py | Vérifiée (tests existants) |

### À valider

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| APP-01 | Candidats de connaissance, conflits, décisions | /approvals | approvals/approvals-page.tsx | 23 : /decisions, /decisions/delegations, /decisions/delegations/{delegation_id}/revoke, /decisions/exceptions … | intention:approve, intention:read, policy:manage, workspace:read, workspace:update | — | Hors maquette | LEKA-455 | Conservée | Badge du menu conservé. | approvals/approvals-page.test.tsx; approvals.spec.ts; intention-decisions.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_governance_api.py; test_intention_decisions_api.py; test_roles_policies_api.py | Vérifiée (tests existants) |

### Gouvernance

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| GOV-01 | Matrice d'accès, rôles personnalisés | /governance | governance/governance-screen.tsx | 6 : /governance/access, /governance/assignments, /governance/assignments/{user_id}, /governance/roles … | policy:manage, workspace:read | — | Hors maquette | LEKA-455 | Conservée |  | governance/approval-governance.test.tsx; governance/governance-screen.test.tsx; accessibility.spec.ts; data-protection.spec.ts; governance-approvals.spec.ts; keyboard.spec.ts; test_ai_governance_api.py (+1) | Vérifiée (tests existants) |
| GOV-02 | Politiques (+ simulation), délégations, exceptions | /governance | governance/governance-screen.tsx | 14 : /decisions/delegations, /decisions/delegations/{delegation_id}/revoke, /decisions/exceptions, /decisions/exceptions/{exception_id}/revoke … | access:read, intention:approve, intention:read, policy:manage, workspace:read, workspace:update | — | Hors maquette | LEKA-455 | Conservée |  | governance/approval-governance.test.tsx; governance/governance-screen.test.tsx; test_audit_api.py; test_governance_api.py; test_intention_decisions_api.py | Vérifiée (tests existants) |
| GOV-03 | Restrictions d'entités | /governance | governance/governance-screen.tsx | 3 : /governance/restrictions, /governance/restrictions/{entity_id} | access:read, entity:restrict | — | Hors maquette | LEKA-455 | Conservée |  | governance/approval-governance.test.tsx; governance/governance-screen.test.tsx; test_access_control_api.py; test_audit_api.py | Vérifiée (tests existants) |
| GOV-04 | Contrôles IA, approbations IA, audit IA, règles de risque | /governance | governance/governance-screen.tsx | 6 : /governance/ai/calls, /governance/ai/controls, /governance/ai/controls/{control_id}, /governance/ai/events … | access:read, policy:manage, workspace:read | Modèle de langage | Hors maquette | LEKA-455 | Conservée |  | governance/approval-governance.test.tsx; governance/governance-screen.test.tsx; test_ai_governance_api.py | Vérifiée (tests existants) |
| GOV-05 | Journal d'audit + rétention | /governance | governance/governance-screen.tsx | 5 : /governance/audit, /governance/audit/export, /governance/audit/settings, /governance/audit/{event_id} … | audit:manage, audit:read, workspace:read | — | Hors maquette | LEKA-455 | Conservée |  | governance/approval-governance.test.tsx; governance/governance-screen.test.tsx; test_audit_api.py; test_audit_sign_in.py; test_languages.py | Vérifiée (tests existants) |
| GOV-06 | Protection des données (classification, chiffrement) | /governance | governance/data-protection.tsx | 2 : /governance/data-protection, /governance/data-protection/policy | access:read, policy:manage, workspace:update | — | Hors maquette | LEKA-455 | Conservée |  | governance/data-protection.test.tsx; accessibility.spec.ts; data-protection.spec.ts; governance-approvals.spec.ts; keyboard.spec.ts; navigation.spec.ts; test_data_protection.py | Vérifiée (tests existants) |

### Équipe

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TEAM-01 | Membres, rôles, inviter (e-mail/lien), révoquer, retirer | /team | team/team-page.tsx | 5 : /members, /members/invite, /members/{membership_id}, /team/members … | member:invite, member:remove, member:update_role, workspace:read | E-mail | Hors maquette | LEKA-455 | Conservée | Limites d'utilisateurs par plan (1/1/5/15) inexistantes. | team/team-page.test.tsx; keyboard.spec.ts; navigation.spec.ts; platform-pages.spec.ts; shell.spec.ts; states.spec.ts; test_audit_api.py; test_auth_hardening.py; test_route_protection.py (+1) | Vérifiée (tests existants) |

### Facturation

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BIL-01 | Plan, crédits du mois, consommation, factures | /billing | billing/billing-page.tsx | 6 : /billing/checkout, /billing/credits, /billing/portal, /billing/stripe/webhook … | workspace:read, workspace:update | Stripe | Hors maquette | LEKA-455 / 461 | Conservée |  | billing/billing-page.test.tsx; activation.spec.ts; keyboard.spec.ts; languages.spec.ts; navigation.spec.ts; platform-pages.spec.ts; test_ai_credits.py; test_billing_api.py; test_billing_stripe.py (+2) | Vérifiée (tests existants) |
| BIL-02 | Checkout Stripe, portail client, essai Growth 14 j | /billing | billing/billing-page.tsx | 2 : /billing/checkout, /billing/portal | workspace:update | Stripe | Hors maquette | LEKA-461 / 462 | Remplacée | Remises à aligner (voir écarts commerciaux). | billing/billing-page.test.tsx; pricing.spec.ts | Vérifiée (tests existants) |
| BIL-03 | Page tarifs publique | /tarifs.html | — | 2 : /pricing, /pricing/events | session | — | Hors maquette | LEKA-461 | Remplacée | Montants et remises à aligner sur les règles canoniques. | pricing.spec.ts; test_pricing.py; test_route_protection.py | Vérifiée (tests existants) |

### Paramètres

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SET-01 | Général (nom), langue du workspace | /settings | settings/workspace-general-form.tsx, settings/language-settings.tsx | 3 : /workspaces/current | workspace:delete, workspace:update | — | Hors maquette | LEKA-455 | Conservée |  | accessibility.spec.ts; forms.spec.ts; keyboard.spec.ts; language-model.spec.ts; languages.spec.ts; llm-runtime.spec.ts; test_auth_hardening.py; test_languages.py; test_workspace_api.py (+2) | Vérifiée (tests existants) |
| SET-02 | Modèle de langage (géré / propre clé) | /settings | settings/language-model.tsx | 5 : /models, /models/settings, /models/settings/test, /models/usage … | workspace:read, workspace:update | Fournisseurs LLM | Hors maquette | LEKA-455 | Conservée |  | settings/language-model.test.tsx; language-model.spec.ts; test_model_api.py | Vérifiée (tests existants) |
| SET-03 | Endpoints d'actions (systèmes autorisés) | /settings | settings/action-endpoints.tsx | 4 : /action-endpoints, /action-endpoints/{endpoint_id} | intention:read, workspace:update | Webhooks signés | Hors maquette | LEKA-455 | Conservée |  | settings/action-endpoints.test.tsx; test_intention_actions_api.py | Vérifiée (tests existants) |

### Compte

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AUTH-01 | Inscription, confirmation e-mail, connexion, mot de passe oublié/réinitialisé | /register, /login, /verify, /forgot-password, /reset-password | — | 14 : /auth/login, /auth/logout, /auth/logout-all, /auth/me … | session | E-mail | Hors maquette | — | Conservée | Pages hors shell. | accessibility.spec.ts; activation.spec.ts; activity.spec.ts; auth.spec.ts; context.spec.ts; emails.spec.ts; test_api_contract.py; test_auth_api.py; test_intelligence_conflicts_model.py (+12) | Vérifiée (tests existants) |
| AUTH-02 | Invitation acceptée | /invitations/[token] | — | 3 : /invitations, /invitations/{invitation_id}, /invitations/{token}/accept | member:invite | E-mail | Hors maquette | — | Conservée |  | test_workspace_api.py | Vérifiée côté API seulement |
| AUTH-03 | Profil, langue du compte, sessions, déconnexion partout, fermeture | menu utilisateur | shell/profile-dialog.tsx, shell/user-menu.tsx | 5 : /auth/me, /auth/sessions, /auth/sessions/{session_id} … | session | — | Shell | LEKA-455 | Conservée |  | shell/menus.test.tsx; shell/profile-dialog.test.tsx; shell/user-menu-name.test.tsx; auth.spec.ts; navigation.spec.ts; responsive.spec.ts (+2) | Vérifiée (tests existants) |

### Shell

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SHELL-01 | Barre latérale à sections, logo, « Understand. Decide. Act. » | toutes | shell/app-sidebar.tsx | — | session | — | Shell | LEKA-455 | Remplacée | Nouvelle navigation des maquettes ; signature à conserver mot pour mot. | shell/app-sidebar.test.tsx; accessibility.spec.ts; auth.spec.ts; navigation.spec.ts; responsive.spec.ts; shell.spec.ts (+1) | Vérifiée (tests existants) |
| SHELL-02 | Sélecteur de workspace | toutes | shell/workspace-switcher.tsx | 6 : /workspaces, /workspaces/current, /workspaces/{workspace_id}/switch … | workspace:delete, workspace:update | — | Shell | LEKA-455 | Manquante | Affiché mais sans effet (TODO LEKA-331) : changer de workspace passe par l'écran de choix ou la bannière démo. | — | Manquante |
| SHELL-03 | Choix du workspace à la connexion / création du premier | toutes | shell/workspace-gate.tsx | 6 : /workspaces, /workspaces/current, /workspaces/{workspace_id}/switch … | workspace:delete, workspace:update | — | Shell | LEKA-455 | Conservée |  | shell/workspace-gate.test.tsx; activation.spec.ts; test_api_contract.py; test_audit_sign_in.py; test_auth_api.py (+4) | Vérifiée (tests existants) |
| SHELL-04 | Cloche de notifications | toutes | shell/app-shell.tsx | — | session | — | Shell | LEKA-455 | À arbitrer | Compteur affiché, source des notifications à vérifier. | shell/app-shell.test.tsx | Vérifiée (tests existants) |
| SHELL-05 | Bandeaux : hors ligne, langue (démo : PR #280) | toutes | shell/app-shell.tsx | — | session | — | Shell | LEKA-455 | Conservée |  | shell/app-shell.test.tsx; accessibility.spec.ts; navigation.spec.ts; states.spec.ts | Vérifiée (tests existants) |
| SHELL-06 | Fil d'Ariane, titre de document, lien d'évitement, page 404 | toutes | shell/document-title.tsx, shell/route-state.tsx | — | session | — | Shell | LEKA-455 | Conservée |  | shell/document-title.test.tsx; shell/route-views.test.tsx; accessibility.spec.ts; forms.spec.ts; keyboard.spec.ts; knowledge-graph.spec.ts (+3) | Vérifiée (tests existants) |
| SHELL-07 | Responsive (tiroir mobile) et clavier | toutes | shell/app-shell.tsx | — | session | — | Shell | LEKA-455 | Conservée |  | shell/app-shell.test.tsx; accessibility.spec.ts; forms.spec.ts; keyboard.spec.ts; knowledge-graph.spec.ts; navigation.spec.ts (+2) | Vérifiée (tests existants) |

### Site vitrine

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SITE-01 | Pages publiques (accueil, tarifs, démo, docs, connecteurs, FAQ, légal) et langues | /*.html | — | 2 : /pricing, /pricing/events | session | — | Hors maquette | — | Conservée | Hors application ; pas dans le périmètre des 5 écrans. | auth.spec.ts; emails.spec.ts; languages.spec.ts; pricing.spec.ts; site.spec.ts; test_pricing.py; test_route_protection.py | Vérifiée (tests existants) |

### Interne

| ID | Fonctionnalité existante | Route / écran actuel | Composant | API (n routes) | Permissions | Intégrations | Destination cible | Ticket | Traitement | Justification / écart | Tests de non-régression | État |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| DEV-01 | Pages _dev (formulaires, états, UI) | /_dev/* | — | — | session | — | Hors maquette | — | Conservée | 404 en production (NODE_ENV) : outil de développement. | aucun test trouvé | À vérifier |

### API par domaine (couverture par les lignes ci-dessus)

| Tag | Routes | Rattachées à une ligne | Permissions |
|---|---|---|---|
| knowledge | 62 | 62 | audit:read, intention:approve, intention:create, workspace:read |
| governance | 29 | 27 | access:read, audit:manage, audit:read, entity:restrict, intention:read, policy:manage, workspace:read, workspace:update |
| intelligence | 28 | 28 | intention:approve, intention:create, intention:read, source:read, workspace:read |
| ingestion | 24 | 12 | source:manage, source:read, workspace:read |
| capabilities | 23 | 19 | intention:approve, intention:create, intention:read, workspace:read, workspace:update |
| context | 22 | 22 | intention:create, intention:read, source:read |
| intentions | 22 | 22 | access:read, intention:approve, intention:create, intention:read |
| connectors | 18 | 18 | source:manage, source:read |
| auth | 14 | 14 | session / publique |
| decisions | 14 | 14 | access:read, intention:approve, intention:create, intention:read, policy:manage, workspace:read, workspace:update |
| actions | 9 | 9 | intention:approve, intention:create, intention:read, workspace:update |
| members | 8 | 8 | member:invite, member:remove, member:update_role, workspace:read |
| workflows | 7 | 2 | intention:create, intention:read, workspace:read |
| outcomes | 7 | 7 | access:read, intention:approve, intention:read |
| workspaces | 6 | 6 | workspace:delete, workspace:update |
| billing | 6 | 6 | workspace:read, workspace:update |
| models | 5 | 5 | workspace:read, workspace:update |
| jobs | 2 | 0 | job:read |
| operations | 2 | 0 | session / publique |
| pricing | 2 | 2 | session / publique |
| health | 1 | 0 | session / publique |
| monitoring | 1 | 1 | source:read |
| webhooks | 1 | 1 | session / publique |

<!-- matrix:end -->

## Régénérer

```
python3 docs/product/gen_matrix.py . docs/product/ux-migration-api-routes.tsv docs/product/ux-migration-matrix.md docs/product/ux-migration-matrix.csv <commit>
```

`ux-migration-api-routes.tsv` est exporté de l'application par
`docs/product/export_api_routes.py` (les chemins de `app.openapi()`, les
permissions des dépendances `require_permission` de chaque route). Le CSV
est le même tableau que ci-dessus, à joindre au ticket.
