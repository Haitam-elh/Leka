"""LEKA-453: the migration matrix, generated from the code.

Each feature is written by hand (what it is, where it goes, how it is
treated); what can be read from the repository is read, never typed:
whether its page exists, its component's unit tests, the e2e specs that
open its route, the API routes it calls (with their permission, from the
app itself — api-routes.tsv) and the API tests naming them.

    python3 gen_matrix.py <repo> <api-routes.tsv> <out.md> <out.csv>
"""

from __future__ import annotations

import csv
import pathlib
import re
import sys

REPO = pathlib.Path(sys.argv[1])
ROUTES_TSV = pathlib.Path(sys.argv[2])
OUT_MD = pathlib.Path(sys.argv[3])
OUT_CSV = pathlib.Path(sys.argv[4])
WEB = REPO / "web"

# ── what the code says ───────────────────────────────────────────────────────

API = [r for r in (line.split("\t") for line in ROUTES_TSV.read_text().splitlines()) if len(r) == 5]
PAGES = {
    "/" + "/".join(p for p in f.parent.relative_to(WEB / "app").parts if not p.startswith("("))
    for f in (WEB / "app").rglob("page.tsx")
}
PAGES = {p.rstrip("/") or "/" for p in PAGES}
E2E = {f.name: f.read_text() for f in (WEB / "e2e").glob("*.spec.ts")}
API_TESTS = {f.name: f.read_text() for f in (REPO / "api" / "tests").glob("test_*.py")}


def page_exists(route: str) -> bool:
    """Whether a page answers it: its pattern ([x] any segment) matches."""
    concrete = re.sub(r"\[[^\]]+\]", "X", route.split("?")[0])
    concrete = concrete.replace("/_dev", "/%5Fdev")
    return any(re.fullmatch(re.sub(r"\[[^\]]+\]", "[^/]+", p), concrete) for p in PAGES)


def unit_tests(components: list[str]) -> list[str]:
    """Its own test file, and any test of its folder that imports it."""
    found = []
    for c in components:
        folder, name = c.rsplit("/", 1)
        for t in sorted((WEB / "components" / folder).glob("*.test.tsx")):
            text = t.read_text()
            if t.name == f"{name}.test.tsx" or (f"/{folder}/{name}" + '"') in text:
                found.append(f"{folder}/{t.name}")
    return sorted(set(found))


def e2e_for(needles: list[str]) -> list[str]:
    return sorted(n for n, s in E2E.items() if any(x in s for x in needles))


def api_for(prefixes: list[str]) -> list[list[str]]:
    return [r for r in API if any(r[1].startswith("/api/v1" + p) for p in prefixes)]


def api_tests_for(prefixes: list[str]) -> list[str]:
    stems = [p.split("{")[0].rstrip("/") for p in prefixes]
    return sorted(n for n, s in API_TESTS.items() if any(f'"/api/v1{x}' in s or f"API}}{x}" in s or f'f"{{API}}{x}' in s for x in stems))


# ── the features, by hand ───────────────────────────────────────────────────
# (id, domain, feature, route, components, api prefixes, integrations,
#  target, ticket, treatment, why/notes, e2e needles)

C, D, R, S, A = "Conservée", "Déplacée", "Remplacée", "Supprimée", "À arbitrer"
ACC, HIS, DET, ENV, CAT = (
    "① Accueil",
    "② Historique des intentions",
    "③ Détail d'une intention",
    "④ Mon environnement",
    "⑤ Agents & Bundles",
)
OUT = "Hors maquette"

F = [
    # ── Accueil ──
    ("ACC-01", "Accueil", "Salutation, date, synthèse « ce qui demande attention »", "/overview", ["overview/overview"], ["/knowledge", "/intelligence"], "—", ACC, "LEKA-456", C, "Bloc d'en-tête de la maquette Accueil (à confronter au template).", ["/overview"]),
    ("ACC-02", "Accueil", "Composer d'intention + 4 suggestions", "/overview", ["overview/overview", "intentions/compact-composer"], ["/intentions"], "Modèle de langage (compréhension)", ACC, "LEKA-456", C, "Point d'entrée principal ; garder l'envoi vers /intentions/new?q=.", ["/overview"]),
    ("ACC-03", "Accueil", "Premiers pas (LEKA-445) + entrée démo (LEKA-451)", "/overview", ["overview/first-steps"], ["/sources", "/intentions/counts"], "Sources", ACC, "LEKA-456", C, "Absent possible de la maquette : à garder tant qu'aucune source n'est lue.", ["/overview"]),
    ("ACC-04", "Accueil", "« À valider » (décisions, candidats)", "/overview", ["overview/overview"], ["/decisions", "/intelligence/enrichment/candidates"], "—", ACC, "LEKA-456", C, "Lien vers /approvals conservé.", ["/overview", "/approvals"]),
    ("ACC-05", "Accueil", "« Ce qui ne va pas » (incidents, sources en échec, conflits)", "/overview", ["overview/overview"], ["/knowledge", "/sources"], "Sources (incidents, santé)", ACC, "LEKA-456", C, "", ["/overview"]),
    ("ACC-06", "Accueil", "Intentions en cours", "/overview", ["overview/overview"], ["/intentions"], "—", ACC, "LEKA-456", C, "", ["/overview"]),
    ("ACC-07", "Accueil", "Activité récente (fil)", "/overview", ["overview/overview"], ["/intelligence/activity", "/intentions/{intention_id}/timeline"], "—", ACC, "LEKA-456", C, "", ["/overview"]),
    ("ACC-08", "Accueil", "Alertes (payantes) / limite du plan Free", "/overview", ["overview/overview"], ["/monitoring", "/billing/subscription"], "—", ACC, "LEKA-463", R, "Les règles d'alerte par plan (Starter 5, Growth 20, Business 100) n'existent pas dans le code : à construire.", ["/overview"]),
    ("ACC-09", "Accueil", "Fraîcheur, couverture, sources silencieuses", "/overview", ["overview/overview"], ["/knowledge", "/sources"], "Sources", ACC, "LEKA-456", C, "", ["/overview"]),
    ("ACC-10", "Accueil", "LEKA Insights (analyse de fond)", "/overview", ["insights/leka-insights"], ["/intelligence"], "Modèle de langage", ACC, "LEKA-456", C, "", ["insights"]),
    # ── Historique ──
    ("HIS-01", "Intentions", "Liste des intentions (statut, parcours, dernière activité)", "/intentions", ["intentions/intentions-list"], ["/intentions"], "—", HIS, "LEKA-457", C, "", ["/intentions\""]),
    ("HIS-02", "Intentions", "Recherche texte", "/intentions", ["intentions/intentions-list"], ["/intentions"], "—", HIS, "LEKA-457", C, "", ["/intentions\""]),
    ("HIS-03", "Intentions", "Filtre par phase + compteurs", "/intentions", ["intentions/intentions-list"], ["/intentions/counts"], "—", HIS, "LEKA-457", C, "", ["/intentions\""]),
    ("HIS-04", "Intentions", "Filtres agent / source / période, tri", "—", [], [], "—", HIS, "LEKA-457", "Manquante", "Demandé par LEKA-457, inexistant aujourd'hui (seulement phase + texte).", []),
    ("HIS-05", "Intentions", "Pagination (curseur, « plus »)", "/intentions", ["intentions/intentions-list"], ["/intentions"], "—", HIS, "LEKA-457", C, "", ["/intentions\""]),
    ("HIS-06", "Intentions", "Archiver / restaurer", "/intentions/[intentionId]", ["intentions/intention-screen"], ["/intentions/{intention_id}/archive", "/intentions/{intention_id}/restore"], "—", HIS, "LEKA-457", C, "Action à exposer aussi depuis la liste si le template la montre.", ["archive"]),
    ("HIS-07", "Intentions", "Nouvelle intention (formulaire, sources, périmètre, pièce jointe)", "/intentions/new", ["intentions/intention-form", "intentions/intention-composer"], ["/intentions", "/context"], "Sources, modèle de langage", DET, "LEKA-458", C, "CTA « Nouvelle intention » de la maquette Historique.", ["/intentions/new"]),
    ("HIS-08", "Intentions", "Questions de clarification (brief)", "/intentions/new", ["intentions/brief"], ["/intentions/brief", "/intentions/{intention_id}/answers"], "Modèle de langage", DET, "LEKA-458", C, "", ["/intentions/new"]),
    ("HIS-09", "Intentions", "Historique global de toutes les intentions (timeline)", "— (API)", [], ["/intention-history"], "—", HIS, "LEKA-457", D, "API existante sans écran dédié : candidate pour l'Historique.", []),
    # ── Détail ──
    ("DET-01", "Détail", "Parcours en 5 étapes + note de parcours", "/intentions/[intentionId]", ["intentions/intention-screen", "intentions/journey"], ["/intentions/{intention_id}"], "—", DET, "LEKA-458", C, "", ["intention-journey"]),
    ("DET-02", "Détail", "Compréhension (objectif, sujets, périmètre, manques)", "/intentions/[intentionId]/overview", ["intentions/intention-screen"], ["/intentions/understand", "/intentions/{intention_id}"], "Modèle de langage", DET, "LEKA-458", C, "", ["/overview`"]),
    ("DET-03", "Détail", "Faisabilité (capacités, crédits, chemin : changer de plan…)", "/intentions/[intentionId]/overview", ["intentions/feasibility"], ["/intentions/{intention_id}/feasibility", "/billing/checkout"], "Stripe (checkout)", DET, "LEKA-462", R, "Le changement de plan existe ; achat d'agent/bundle absent (add_ons.available: false) ; montants à aligner sur les règles canoniques.", []),
    ("DET-04", "Détail", "Routage (agent retenu, candidats, écartés) + lancer l'agent", "/intentions/[intentionId]/overview", ["intentions/routing"], ["/intentions/{intention_id}/routing", "/capabilities"], "Runtime agents", DET, "LEKA-458", A, "Aujourd'hui l'agent est lancé automatiquement (dispatch.py) ; le parcours voulu (proposer → valider en Décision → lancer en Action) est à arbitrer avec Haitam/Karim.", []),
    ("DET-05", "Détail", "Contexte de l'analyse (éléments, qualité, version, sources)", "/intentions/[intentionId]/overview", ["intentions/intention-screen"], ["/context"], "Sources", DET, "LEKA-458", C, "", ["context"]),
    ("DET-06", "Détail", "Analyse : étapes, capacités mobilisées, lectures, relancer/arrêter", "/intentions/[intentionId]/analysis", ["intentions/analysis-tab"], ["/intentions/{intention_id}/analysis", "/intentions/{intention_id}/analyse"], "Modèle de langage", DET, "LEKA-458", C, "", ["/analysis`"]),
    ("DET-07", "Détail", "Résultats : synthèse, constats, causes, confiance, limites, preuves", "/intentions/[intentionId]/results", ["intelligence/explained", "intelligence/findings"], ["/intentions/{intention_id}/analysis"], "—", DET, "LEKA-458", C, "Inclut LEKA-448 (source non lue pertinente).", ["/results`"]),
    ("DET-08", "Détail", "Recommandations", "/intentions/[intentionId]/results", ["intelligence/explained"], ["/intentions/{intention_id}/analysis"], "—", DET, "LEKA-458", C, "", ["/results`"]),
    ("DET-09", "Détail", "Décision : votes, approuver, rejeter, demander des changements, modifier", "/intentions/[intentionId]/decision", ["decisions/intention-decision", "intentions/decision-step"], ["/decisions", "/intentions/{intention_id}/decision"], "—", DET, "LEKA-458", C, "", ["intention-decisions"]),
    ("DET-10", "Détail", "Action : plan, étapes, planification, contrôles, exécution", "/intentions/[intentionId]/actions", ["actions/actions-tab"], ["/intentions/{intention_id}/plan"], "Endpoints d'actions (webhooks signés)", DET, "LEKA-458", C, "", ["/actions`"]),
    ("DET-11", "Détail", "Vérification du résultat (attendus, constats, conclusion)", "/intentions/[intentionId]/actions", ["actions/actions-tab"], ["/intentions/{intention_id}/verification", "/intentions/{intention_id}/plan/expectations"], "—", DET, "LEKA-458", C, "", ["intention-outcomes"]),
    ("DET-12", "Détail", "Preuves (onglet evidence)", "/intentions/[intentionId]/evidence", ["intentions/intention-screen"], ["/context"], "—", DET, "LEKA-458", C, "", ["evidence"]),
    ("DET-13", "Détail", "Historique de l'intention (timeline)", "/intentions/[intentionId]/history", ["intentions/intention-screen"], ["/intentions/{intention_id}/timeline"], "—", DET, "LEKA-458", C, "", ["/history`"]),
    ("DET-14", "Détail", "Livrables des agents (rapport, PDF, PowerPoint)", "/intentions/[intentionId]/deliverable", ["intentions/deliverable", "intentions/agent-work"], ["/agent-runs"], "Runtime agents, stockage objets", DET, "LEKA-458", C, "Ajouté le 14/10 (#275).", []),
    ("DET-15", "Détail", "Changements de code proposés (diff → pull request)", "/intentions/[intentionId]", ["capabilities/code-changes"], ["/code-changes"], "GitHub (écriture PR)", DET, "LEKA-458", C, "", []),
    ("DET-16", "Détail", "Versions, reformuler, stopper, annuler", "/intentions/[intentionId]", ["intentions/intention-screen"], ["/intentions/{intention_id}"], "—", DET, "LEKA-458", C, "", ["intentions"]),
    ("DET-17", "Détail", "Coût de l'intention (crédits mesurés)", "/intentions/[intentionId]", ["intentions/feasibility"], ["/billing/usage", "/billing/credits"], "—", DET, "LEKA-458", R, "Le template demande coût total, périodicité, renouvellement : à confronter.", []),
    # ── Environnement ──
    ("ENV-01", "Environnement", "Vue d'ensemble / jumeau (comptes, couverture, fraîcheur)", "/environment", ["environment/environment-screen"], ["/knowledge"], "Sources", ENV, "LEKA-459", C, "", ["knowledge-graph"]),
    ("ENV-02", "Environnement", "Architecture (dossier, schéma)", "/environment?view=architecture", ["environment/architecture"], ["/knowledge"], "Sources (code)", ENV, "LEKA-459", C, "", []),
    ("ENV-03", "Environnement", "Vues Applications, Infrastructure, Données", "/environment?view=…", ["environment/environment-screen"], ["/knowledge"], "Sources", ENV, "LEKA-459", C, "Onglets « Services » de la maquette.", ["tab=applications"]),
    ("ENV-04", "Environnement", "Dépendances", "/environment?view=dependencies", ["environment/environment-screen"], ["/knowledge"], "Sources", ENV, "LEKA-459", C, "", []),
    ("ENV-05", "Environnement", "Équipes (organisation)", "/environment?view=organisation", ["environment/environment-screen"], ["/knowledge"], "Sources (GitHub, M365, Google)", ENV, "LEKA-459", C, "", []),
    ("ENV-06", "Environnement", "Événements (incidents, changements, déploiements)", "/environment?view=events", ["environment/environment-screen"], ["/knowledge"], "Sources (observabilité)", ENV, "LEKA-459", C, "Onglet « Incidents » de la maquette.", ["tab=events"]),
    ("ENV-07", "Environnement", "Domaines métier", "/environment?view=domains", ["environment/environment-screen"], ["/knowledge"], "Sources", ENV, "LEKA-459", C, "", ["tab=domains"]),
    ("ENV-08", "Environnement", "Qualité de la connaissance (score, manques, retours)", "/environment?view=quality", ["environment/knowledge-quality"], ["/intelligence/quality"], "—", ENV, "LEKA-459", C, "", ["quality"]),
    ("ENV-09", "Environnement", "Fiche d'une entité (10 onglets)", "/environment/[entityType]/[entityId]", ["environment/entity-sheet"], ["/knowledge/entities"], "Sources", ENV, "LEKA-459", C, "Panneau de détail d'un service de la maquette.", ["/environment/services"]),
    ("ENV-10", "Environnement", "Explorateur du graphe (chemins)", "/environment/graph", ["environment/graph-explorer"], ["/knowledge/graph"], "—", ENV, "LEKA-459", C, "Cartographie zoom/recherche de la maquette.", []),
    ("ENV-11", "Environnement", "Contexte d'une entité (versions, conflits, éléments)", "/environment/[entityType]/[entityId]/context", ["environment/entity-context"], ["/context"], "—", ENV, "LEKA-459", C, "", []),
    ("ENV-13", "Environnement", "Configuration (synchronisation des sources, alertes, couverture)", "/environment?tab=configuration", ["environment/environment-screen"], ["/environment", "/monitoring", "/sources"], "Sources", ENV, "LEKA-459", C, "Onglet « Configuration » de la maquette (#307) ; aucune règle d'alerte simulée (LEKA-463).", []),
    ("ENV-12", "Environnement", "Recherche globale ⌘K (palette)", "toutes", ["shell/command-palette"], ["/knowledge/search"], "—", "Shell", "LEKA-455", C, "", ["keyboard"]),
    # ── Sources ──
    ("SRC-01", "Sources", "Liste des sources, santé, synchro", "/sources", ["sources/sources-page"], ["/sources"], "Tous les connecteurs", ENV, "LEKA-459", D, "Onglet « Sources » de Mon environnement ; /sources reste joignable.", ["/sources\""]),
    ("SRC-02", "Sources", "Ajouter une source (assistant, test, périmètre, activation)", "/sources", ["sources/add-source-dialog"], ["/sources", "/connectors"], "53 connecteurs", ENV, "LEKA-459", C, "CTA « Connecter une source » de la maquette.", ["custom-connector"]),
    ("SRC-03", "Sources", "Connecteur sur mesure (REST, GraphQL, webhook)", "/sources", ["sources/add-source-dialog"], ["/sources", "/connectors/catalog"], "API client", ENV, "LEKA-459", C, "", ["custom-connector"]),
    ("SRC-04", "Sources", "Détail d'une source (config, identifiants, synchro, historique, désactiver, supprimer)", "/sources/[sourceId]", ["sources/source-page"], ["/sources/{source_id}"], "Connecteur", ENV, "LEKA-459", C, "", ["custom-connector"]),
    ("SRC-05", "Sources", "Synchroniser maintenant", "/sources/[sourceId]", ["sources/source-page"], ["/ingestion/sources"], "Connecteur", ENV, "LEKA-459", C, "", []),
    ("SRC-06", "Sources", "Accueil d'un workspace : choix des outils + démo", "/welcome", ["sources/welcome-page"], ["/sources", "/connectors/catalog"], "Connecteurs", ACC, "LEKA-456", C, "Onboarding ; hors maquette mais indispensable.", ["activation"]),
    ("SRC-07", "Sources", "Réception de webhooks des sources", "— (API)", [], ["/webhooks"], "Systèmes clients", OUT, "—", C, "Aucun écran : pas d'impact UX.", []),
    # ── Capacités ──
    ("CAP-01", "Capacités", "Catalogue par domaine, recherche, filtres, favoris, usage", "/capabilities", ["capabilities/catalogue"], ["/capabilities"], "—", CAT, "LEKA-460", R, "Remplacé par la marketplace Agents & Bundles ; les capacités LEKA (règles) doivent rester visibles.", ["/capabilities\""]),
    ("CAP-02", "Capacités", "Mes capacités", "/capabilities?view=mine", ["capabilities/catalogue"], ["/capabilities"], "—", CAT, "LEKA-460", D, "« Déjà actif / inclus » de la maquette.", []),
    ("CAP-03", "Capacités", "Configuration (activer/désactiver par workspace)", "/capabilities?view=configuration", ["capabilities/catalogue"], ["/capabilities/{key}/settings"], "—", OUT, "LEKA-455", D, "Gestion admin : à garder dans Paramètres ou un onglet admin du catalogue.", ["tab=configuration"]),
    ("CAP-04", "Capacités", "Fiche capacité (entrées, versions, événements, disponibilité)", "/capabilities/[capabilityId]", ["capabilities/capability-detail"], ["/capabilities/{key}"], "—", CAT, "LEKA-460", C, "Détail agent de la maquette.", ["/capabilities/synthesis"]),
    ("CAP-05", "Capacités", "Lancer un agent + exécutions + livrables", "/capabilities/[capabilityId]", ["capabilities/agent-runs"], ["/agent-runs"], "Runtime agents", CAT, "LEKA-460", C, "", []),
    ("CAP-06", "Capacités", "Workflows (lancer, suivre)", "/capabilities/[capabilityId]", ["capabilities/workflow-runs"], ["/workflows"], "Runtime", CAT, "LEKA-460", C, "Quotas de workflows par plan (Growth 10, Business 50) inexistants.", []),
    ("CAP-07", "Capacités", "Demander une capacité", "/capabilities", ["capabilities/catalogue"], ["/capabilities"], "—", CAT, "LEKA-460", C, "", []),
    ("CAP-08", "Capacités", "Acheter un agent / un bundle", "/capabilities", ["capabilities/offers"], ["/billing/add-ons"], "Stripe", CAT, "LEKA-460 / 461 / 462", C, "Livré (#299, #302) ; achat d'agent prouvé sur Stripe en mode test (LEKA-461, #305). Aucun bundle vendable tant que des membres manquent ; pas de Price ID agents/bundles (`price_data`).", []),
    # ── Hors maquette ──
    ("ACT-01", "Activité", "Journal d'activité, tendances, filtres", "/activity", ["activity/activity"], ["/intelligence/activity", "/intention-history"], "—", OUT, "LEKA-455", C, "Hors des 5 maquettes : accès conservé par la navigation.", ["/activity"]),
    ("APP-01", "À valider", "Candidats de connaissance, conflits, décisions", "/approvals", ["approvals/approvals-page"], ["/intelligence/enrichment/candidates", "/intelligence/conflicts", "/decisions"], "—", OUT, "LEKA-455", C, "Badge du menu conservé.", ["/approvals"]),
    ("GOV-01", "Gouvernance", "Matrice d'accès, rôles personnalisés", "/governance", ["governance/governance-screen"], ["/governance/access", "/governance/roles", "/governance/assignments"], "—", OUT, "LEKA-455", C, "", ["/governance"]),
    ("GOV-02", "Gouvernance", "Politiques (+ simulation), délégations, exceptions", "/governance", ["governance/governance-screen"], ["/governance/policies", "/governance/evaluate", "/decisions/delegations", "/decisions/exceptions", "/decisions/policy"], "—", OUT, "LEKA-455", C, "", ["governance-approvals"]),
    ("GOV-03", "Gouvernance", "Restrictions d'entités", "/governance", ["governance/governance-screen"], ["/governance/restrictions"], "—", OUT, "LEKA-455", C, "", []),
    ("GOV-04", "Gouvernance", "Contrôles IA, approbations IA, audit IA, règles de risque", "/governance", ["governance/governance-screen"], ["/governance/ai"], "Modèle de langage", OUT, "LEKA-455", C, "", ["governance-approvals"]),
    ("GOV-05", "Gouvernance", "Journal d'audit + rétention", "/governance", ["governance/governance-screen"], ["/governance/audit"], "—", OUT, "LEKA-455", C, "", []),
    ("GOV-06", "Gouvernance", "Protection des données (classification, chiffrement)", "/governance", ["governance/data-protection"], ["/governance/data-protection"], "—", OUT, "LEKA-455", C, "", ["/governance"]),
    ("TEAM-01", "Équipe", "Membres, rôles, inviter (e-mail/lien), révoquer, retirer", "/team", ["team/team-page"], ["/members", "/team/members"], "E-mail", OUT, "LEKA-455", C, "Limites d'utilisateurs par plan (1/1/5/15) inexistantes.", ["/team"]),
    ("BIL-01", "Facturation", "Plan, crédits du mois, consommation, factures", "/billing", ["billing/billing-page"], ["/billing"], "Stripe", OUT, "LEKA-455 / 461", C, "", ["/billing"]),
    ("BIL-02", "Facturation", "Checkout Stripe, portail client, essai Growth 14 j", "/billing", ["billing/billing-page"], ["/billing/checkout", "/billing/portal"], "Stripe", OUT, "LEKA-461 / 462", R, "Remises à aligner (voir écarts commerciaux).", ["pricing"]),
    ("BIL-03", "Facturation", "Page tarifs publique", "/tarifs.html", [], ["/pricing"], "—", OUT, "LEKA-461", R, "Montants et remises à aligner sur les règles canoniques.", ["tarifs"]),
    ("SET-01", "Paramètres", "Général (nom), langue du workspace", "/settings", ["settings/workspace-general-form", "settings/language-settings"], ["/workspaces/current"], "—", OUT, "LEKA-455", C, "", ["/settings"]),
    ("SET-02", "Paramètres", "Modèle de langage (géré / propre clé)", "/settings", ["settings/language-model"], ["/models"], "Fournisseurs LLM", OUT, "LEKA-455", C, "", ["language-model"]),
    ("SET-03", "Paramètres", "Endpoints d'actions (systèmes autorisés)", "/settings", ["settings/action-endpoints"], ["/action-endpoints"], "Webhooks signés", OUT, "LEKA-455", C, "", []),
    ("AUTH-01", "Compte", "Inscription, confirmation e-mail, connexion, mot de passe oublié/réinitialisé", "/register, /login, /verify, /forgot-password, /reset-password", [], ["/auth"], "E-mail", OUT, "—", C, "Pages hors shell.", ["auth", "emails"]),
    ("AUTH-02", "Compte", "Invitation acceptée", "/invitations/[token]", [], ["/invitations"], "E-mail", OUT, "—", C, "", []),
    ("AUTH-03", "Compte", "Profil, langue du compte, sessions, déconnexion partout, fermeture", "menu utilisateur", ["shell/profile-dialog", "shell/user-menu"], ["/auth/me", "/auth/sessions"], "—", "Shell", "LEKA-455", C, "", ["shell"]),
    ("SHELL-01", "Shell", "Barre latérale à sections, logo, « Understand. Decide. Act. »", "toutes", ["shell/app-sidebar"], [], "—", "Shell", "LEKA-455", R, "Nouvelle navigation des maquettes ; signature à conserver mot pour mot.", ["navigation", "shell"]),
    ("SHELL-02", "Shell", "Sélecteur de workspace", "toutes", ["shell/workspace-switcher"], ["/workspaces"], "—", "Shell", "LEKA-455", "Manquante", "Affiché mais sans effet (TODO LEKA-331) : changer de workspace passe par l'écran de choix ou la bannière démo.", []),
    ("SHELL-03", "Shell", "Choix du workspace à la connexion / création du premier", "toutes", ["shell/workspace-gate"], ["/workspaces"], "—", "Shell", "LEKA-455", C, "", ["activation"]),
    ("SHELL-04", "Shell", "Cloche de notifications", "toutes", ["shell/app-shell"], [], "—", "Shell", "LEKA-455", A, "Compteur affiché, source des notifications à vérifier.", []),
    ("SHELL-05", "Shell", "Bandeaux : hors ligne, langue (démo : PR #280)", "toutes", ["shell/app-shell"], [], "—", "Shell", "LEKA-455", C, "", ["states"]),
    ("SHELL-06", "Shell", "Fil d'Ariane, titre de document, lien d'évitement, page 404", "toutes", ["shell/document-title", "shell/route-state"], [], "—", "Shell", "LEKA-455", C, "", ["accessibility", "keyboard"]),
    ("SHELL-07", "Shell", "Responsive (tiroir mobile) et clavier", "toutes", ["shell/app-shell"], [], "—", "Shell", "LEKA-455", C, "", ["responsive", "keyboard"]),
    ("SITE-01", "Site vitrine", "Pages publiques (accueil, tarifs, démo, docs, connecteurs, FAQ, légal) et langues", "/*.html", [], ["/pricing"], "—", OUT, "—", C, "Hors application ; pas dans le périmètre des 5 écrans.", ["site"]),
    ("DEV-01", "Interne", "Pages _dev (formulaires, états, UI)", "/_dev/*", [], [], "—", OUT, "—", C, "404 en production (NODE_ENV) : outil de développement.", []),
]

# ── writing ──────────────────────────────────────────────────────────────────


def row(f):
    fid, dom, feat, route, comps, prefixes, integ, target, ticket, treat, why, needles = f
    routes = [r.strip() for r in route.split(",")]
    exists = all(page_exists(r) for r in routes if r.startswith("/") and not r.endswith(".html") and "*" not in r) if route.startswith("/") else None
    apis = api_for(prefixes)
    perms = sorted({p for r in apis for p in r[3].split(",") if p and p != "-"})
    units = unit_tests(comps)
    e2e = e2e_for(needles) if needles else []
    apit = api_tests_for(prefixes) if prefixes else []
    tests = units + e2e
    if treat == "Manquante":
        proof = "—"
        status = "Manquante"
    elif exists is False:
        proof = "route introuvable"
        status = "À vérifier"
    elif tests or apit:
        listed = tests[:6] + apit[:3]
        proof = "; ".join(listed) + (f" (+{len(tests) + len(apit) - len(listed)})" if len(tests) + len(apit) > len(listed) else "")
        status = "Vérifiée (tests existants)" if tests else "Vérifiée côté API seulement"
    else:
        proof = "aucun test trouvé"
        status = "À vérifier"
    return {
        "ID": fid,
        "Domaine": dom,
        "Fonctionnalité existante": feat,
        "Route / écran actuel": route,
        "Composant": ", ".join(f"{c}.tsx" for c in comps) or "—",
        "API (n routes)": f"{len(apis)} : " + ", ".join(sorted({r[1].removeprefix('/api/v1') for r in apis})[:4]) + (" …" if len(apis) > 4 else "") if apis else "—",
        "Permissions": ", ".join(perms) or "session",
        "Intégrations": integ,
        "Destination cible": target,
        "Ticket": ticket,
        "Traitement": treat,
        "Justification / écart": why,
        "Tests de non-régression": proof,
        "État": status,
    }


rows = [row(f) for f in F]
cols = list(rows[0].keys())
with OUT_CSV.open("w", newline="") as out:
    w = csv.DictWriter(out, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)


def table(rs, keys):
    head = "| " + " | ".join(keys) + " |\n|" + "---|" * len(keys) + "\n"
    return head + "".join("| " + " | ".join(str(r[k]).replace("|", "/") for k in keys) + " |\n" for r in rs)


counts = {}
for r in rows:
    counts[r["Traitement"]] = counts.get(r["Traitement"], 0) + 1
states = {}
for r in rows:
    states[r["État"]] = states.get(r["État"], 0) + 1

covered = set()
for f in F:
    for p in f[5]:
        for r in api_for([p]):
            covered.add((r[0], r[1]))
tags = {}
for m, path, tag, perm, summary in API:
    t = tags.setdefault(tag, [0, 0, set()])
    t[0] += 1
    t[1] += (m, path) in covered
    t[2] |= {p for p in perm.split(",") if p and p != "-"}

body = OUT_MD.read_text() if OUT_MD.exists() else ""
start, end = "<!-- matrix:start -->", "<!-- matrix:end -->"
generated = (
    f"{start}\n\n_Générée par `gen_matrix.py` à partir du code (main `{sys.argv[5] if len(sys.argv) > 5 else '?'}`) : "
    f"{len(rows)} fonctionnalités, {len(API)} routes d'API, {len(PAGES)} pages._\n\n"
    "**Traitements** : " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())) + "  \n"
    "**États** : " + ", ".join(f"{k} {v}" for k, v in sorted(states.items())) + "\n\n"
)
for dom in dict.fromkeys(r["Domaine"] for r in rows):
    generated += f"### {dom}\n\n" + table([r for r in rows if r["Domaine"] == dom], [c for c in cols if c != "Domaine"]) + "\n"
generated += "### API par domaine (couverture par les lignes ci-dessus)\n\n| Tag | Routes | Rattachées à une ligne | Permissions |\n|---|---|---|---|\n"
for tag, (n, cov, perms) in sorted(tags.items(), key=lambda kv: -kv[1][0]):
    generated += f"| {tag} | {n} | {cov} | {', '.join(sorted(perms)) or 'session / publique'} |\n"
generated += f"\n{end}"
if start in body:
    body = body[: body.index(start)] + generated + body[body.index(end) + len(end) :]
else:
    body += "\n" + generated + "\n"
OUT_MD.write_text(body)
print(counts, states, len(rows))
