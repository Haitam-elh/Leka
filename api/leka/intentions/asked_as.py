"""How people ask for each agent's work, in their words (2026-10-23).

An agent's name says what it is — « Modification de code », « Aide au
débogage » — rarely what a request says: « ajoute un lien », « pourquoi
c'est bloqué », « pourquoi c'est lent ». Its description is in English, its
requests in French. So a request that asked plainly for a change of the code
went to the test generation: no word of it named the code change.

These words, said the way requests say them, count as the agent's name
(proposal.relevance). Words, never sentences: what a request asks, never
what it is about — a service, a repository, a page stay out (proposal's
_IDENTIFIER, _FILLER). A word two agents could both claim is left out, or
given to the one whose work it names first.
"""

from __future__ import annotations

from collections.abc import Mapping

ASKED_AS: Mapping[str, str] = {
    "code-change": "ajoute ajouter modifie modifier implemente implementer supprime supprimer "
    "renomme renommer remplace remplacer lien bouton champ colonne add implement remove "
    "rename",
    "test-generation": "ecris ecrire genere generer manquants unitaires write generate",
    "test-analysis": "tester faut couverture coverage",
    "debug-assistant": "bloque bloquee bloquees coince bug bugs plante crash erreur erreurs "
    "echouent echouer deboguer stuck",
    "build-fixer": "build ci pipeline echec echoue echoue reparer compile compilation",
    "architecture-analysis": "services faibles fragilites compose architecture",
    "data-analysis": "personnelles stocke stockees stockent vivent lit ecrit personal",
    "change-impact-analysis": "impact impacte impactes portee",
    "performance-analysis": "lente lent lenteur lents ralentit rapide latence trafic charge slow",
    "design-review": "meilleure meilleur maquette maquettes refaire redesign ameliore ameliorer",
    "incident-investigation": "incident postmortem post mortem panne",
    "release-analysis": "release livre livraison",
    "regression-analysis": "casser casse marchait regression",
    "qa-acceptance": "recette criteres acceptance pret",
    "reliability-analysis": "defaillance tombe tombent fiable fiabilite resilience",
    "security-review": "authentification sessions failles faille",
    "dependency-analysis": "vulnerabilites paquets bibliotheques librairies cve",
    "codebase-explorer": "organise organisation structure repere",
    "documentation-assistant": "documentation redige rediger documente",
    "migration-planning": "migrer migration",
}


__all__ = ["ASKED_AS"]
