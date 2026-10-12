# Audit UX/UI — LEKA-438

Première étape de la refonte : chaque écran, son objectif, son action
principale, ce qu'on garde, ce qu'on retire, les états qui manquent. **À
valider avant de toucher au design** — le ticket demande de clarifier le rôle
des écrans avant de les polir.

- **Références** : les 16 maquettes de Karim, [`mockups/`](mockups/). Consigne
  du fondateur (2026-10-13) : *un mix des templates et de ce qu'on propose* —
  elles donnent la direction, pas un pixel à reproduire.
- **Hors périmètre** : le menu et la navigation (`web/config/navigation.ts`),
  strictement inchangés. La barre latérale des maquettes n'est pas reprise.
- **Base de l'audit** : l'application réelle en local, espace de démo Acme
  (`scripts/seed.py`, compte Nora), 1440 px, le 2026-10-13. Les chiffres des
  maquettes sont illustratifs ; aucun ne doit apparaître comme réel.

## Constat d'ensemble

La structure des maquettes est **déjà en place** (LEKA-428 et suivants) :
mêmes titres, mêmes sous-titres, parcours en cinq étapes, cartes, onglets. La
refonte n'est donc pas une reconstruction : c'est **épurer, rendre honnête et
finir les états**. Cinq défauts reviennent sur presque toutes les pages :

| # | Défaut transverse | Où | Correction proposée |
| --- | --- | --- | --- |
| T1 | **Rangée de KPI sur chaque page**, souvent à 0 ou « — » (Facturation, Équipe, À valider, Sources, Capacités, Activité, Environnement). La maquette elle-même le fait, mais le ticket demande de *ne pas appliquer le même dashboard partout* et de *retirer les KPI qui ne mènent à aucune décision*. | 8 pages | Garder une rangée de KPI seulement là où un chiffre déclenche une action (Activité, Sources en erreur). Ailleurs : un résumé d'une ligne dans l'en-tête, ou rien. Un KPI à 0 qui n'appelle rien disparaît. |
| T2 | **Bandeau de réassurance en bas de page** (« Collaborez en toute sécurité », « LEKA suit 11 source(s) », « Une question sur votre offre ? », « Des insights en continu »). Directive : *réduire les encarts de réassurance répétitifs*. | 6 pages | Un seul endroit où LEKA dit « vous gardez le contrôle » : le parcours d'intention (étapes Décision et Action). Ailleurs, le bandeau ne reste que s'il porte une vraie action. |
| T3 | **Pluriels en « (s) »** : « 1 source(s) demandent », « 4 élément(s) », « 3 service(s) », « 1 base(s) ». Fait brouillon : **316 chaînes** dans `web/lib/i18n`. | toutes | Vrais pluriels : le mécanisme existe déjà (`lib/i18n/format.ts`), à généraliser. |
| T4 | **Colonnes et valeurs vides présentées comme des données** : Sources → colonnes *Éléments* et *Propriétaire* à « — » sur toutes les lignes ; KPI « — Éléments synchronisés » ; « ? Services opérationnels ». | Sources, Vue d'ensemble, Capacités | Une colonne vide partout est masquée ; une valeur inconnue se dit en mots (« pas encore mesuré ») et une seule fois. |
| T5 | **Le panneau de détail existe mais reste caché** : À valider, Sources et Mes intentions ouvrent le détail à droite au clic sur une ligne — rien n'est ouvert à l'arrivée, et l'élément ouvert n'est pas dans l'URL (un lien ou une notification ne peut pas y mener). | 3 listes | Garder les panneaux existants ; l'élément ouvert dans l'URL ; sur grand écran, ouvrir à l'arrivée le premier élément qui attend quelque chose (À valider : le premier en attente ; Sources : la première en erreur). |

## Matrice écran par écran

Verdict : **conserver**, **simplifier**, **fusionner**, **repenser**,
**supprimer**.

| Écran | Objectif utilisateur | Action primaire | Verdict | À garder | À simplifier / retirer | États à finir |
| --- | --- | --- | --- | --- | --- | --- |
| **Vue d'ensemble** `/overview` — maquette 01 | Savoir en 10 secondes si quelque chose demande mon attention, et agir | Poser une intention (le champ en haut) | **Simplifier** | Salutation + phrase d'état, champ d'intention et ses 4 suggestions, *À valider*, *Insights LEKA* | Les 4 cartes KPI sont étirées sur ~250 px de vide ; « ? Services opérationnels » ; *Activité récente* dit « Aucune activité » alors qu'Activité en compte 36 (**incohérence à vérifier**) ; bandeau bas qui répète *Sources connectées* | Environnement vide (aucune source), sources en erreur, modèle jamais construit |
| **Nouvelle intention — 1. Votre intention** `/intentions/new` — 02 | Dire ce que je veux, en sachant sur quoi LEKA va s'appuyer | Lancer l'analyse | **Conserver** (proche de la maquette) | Stepper 5 étapes, contexte analysé à droite, périmètre | « Dictée — Bientôt » (fonction absente montrée) : retirer jusqu'à ce qu'elle existe ; « Tout désélectionner » en tête de la liste | Aucune source connectée, quota de crédits atteint |
| **2. Analyse / 3. Résultats / 4. Décision / 5. Action** — 03 à 06 | Suivre l'analyse, comprendre le résultat, décider, suivre l'exécution | Selon l'étape : *Arrêter*, *Voir les preuves*, *Valider et passer à l'action*, *Suivre* | **À auditer en conditions réelles** | — | — | Analyse partielle (LEKA-436 : *partial*), action bloquée faute de preuve (`blocked`/`validation`), action échouée, résultat à vérifier |
| **Mes intentions** `/intentions` — 07 | Retrouver une demande et voir où elle en est | Nouvelle intention | **Simplifier** | Onglets de statut, recherche, bouton | État vide d'une ligne perdu dans une carte de 70 px : le remplacer par un vrai état vide (ce que LEKA sait faire + 2 suggestions + bouton) ; ouvrir le panneau (T5) | Vide, chargement, erreur, intention en échec |
| **À valider** `/approvals` — 09 | Décider vite, en voyant pourquoi | Valider / Refuser l'élément ouvert | **Repenser** | Tableau, filtres par type, recherche, confiance | 4 KPI dont 3 à 0 (T1) ; **deux rangées de filtres concurrentes** (statut + type) : une seule rangée de types, le statut dans un menu ; le panneau de décision existe : l'ouvrir sur le premier en attente (T5), *Valider* / *Refuser* / *Demander des modifications* en évidence | File vide (« rien n'attend votre décision »), permission insuffisante (membre sans `approve`), décision déjà prise par un autre |
| **Mon environnement** `/environment` — 10, 11 | Comprendre mon système et ce qui y bouge | Ouvrir un élément (fiche) | **Simplifier** | Cartographie, onglets de vue, panneau de l'élément, légende, date de mise à jour | 10 onglets + bouton sur une ligne : garder l'ordre, mais réduire le poids visuel ; bas de page (*Services par statut*, *Types de ressources*, *Top dépendances*) : décoratif, à remplacer par *Points d'attention* et *Événements récents* de la maquette 10 | Modèle jamais construit (« Pas encore cartographié » est déjà là), source partielle, élément restreint |
| **Fiche d'un élément** `/environment/:type/:id` — 11 | Tout savoir d'un service et agir dessus | *Demander à LEKA* (intention pré-remplie) | **À auditer** (pas capturé, l'aperçu latéral seulement) | — | — | Métriques non mesurées : dire « non mesuré », jamais une courbe vide |
| **Activité** `/activity` — 08 | Voir ce qui s'est passé et ce que LEKA a fait | Filtrer / ouvrir un événement | **Conserver** | Le plus fidèle à la maquette : graphique, répartition, derniers événements, filtres, export | KPI « 0 Utilisateurs actifs » ; bandeau bas (T2) | Période sans événement |
| **Capacités** `/capabilities` — 13 | Trouver la capacité qui répond à mon besoin | Demander une capacité / ouvrir une capacité | **Repenser** | Onglets *Disponibles / Mes capacités / Configuration*, recherche, catégories | Directive explicite : *aider à choisir selon le besoin plutôt que le volume*. Aujourd'hui 27 cartes sur ~2 000 px, chacune avec « Pas encore exécutée » et souvent « Aucun modèle de langage ne peut l'exécuter ici » répété. Proposer : regroupement par besoin (*Comprendre un incident*, *Préparer une release*…), carte compacte, l'indisponibilité dite une fois en tête, pas sur chaque carte | Aucune capacité exécutable (pas de modèle), capacité verrouillée par l'offre |
| **Sources** `/sources` — 12 | Savoir si mes outils sont bien connectés, réparer ce qui casse | Ajouter une source | **Simplifier** | Tableau, filtres, statut, dernière synchro | Colonnes vides (T4) ; KPI « — » ; « Connecteur sur mesure » au même niveau que l'action primaire → menu secondaire ; panneau ouvert sur la source en erreur (T5) ; source en erreur mise en avant (aujourd'hui une ligne parmi 12) | Erreur d'une source avec la raison et l'action pour réparer, source à configurer |
| **Sécurité & gouvernance** `/governance` — 14 | Contrôler qui peut faire quoi et ce qui s'est passé | Selon l'onglet | **Repenser** | Toutes les fonctions (journal d'audit, matrice des droits, entités restreintes, rôles, politiques, conservation) — elles sont réelles | **L'écran le plus éloigné de la maquette et le plus dense** : formulaires de création de rôle et de politique ouverts en permanence, matrice de 22 lignes, 7 blocs empilés. Proposer : une page de synthèse (état réel : nombre de rôles, politiques, refus récents, alertes) puis chaque outil dans son onglet, les formulaires dans un dialogue. **Pas de score « 92/100 » inventé** comme dans la maquette : aucun calcul ne le produit | Membre sans droit (lecture seule), aucune politique |
| **Équipe & accès** `/team` — 15 | Inviter et gérer les membres | Inviter un utilisateur | **Simplifier** | Tableau, onglets utilisateurs / invitations, paramètres de sécurité | 4 KPI dont 2 à 0 ; bandeau bas (T2) ; carte *Répartition par rôle* utile seulement au-delà de quelques membres | Seul membre (inviter), invitation expirée |
| **Facturation** `/billing` — 16 | Savoir ce que j'ai, ce que je consomme | Voir les tarifs / contacter (pas de paiement en ligne, LEKA-446) | **Conserver** | Honnête : offre réelle, crédits, consommation, pas de fausse facture | Bandeau bas (T2) | Crédits épuisés, offre à changer (LEKA-446) |
| **Paramètres** `/settings` | Régler l'espace et mon profil | Enregistrer | **À auditer** | — | — | — |
| **Bienvenue** `/welcome` | Première connexion : arriver à une première intention utile | Connecter une source | **Hors 438** → LEKA-445 (onboarding) | — | — | — |

## Principes UX/UI révisés

Les règles que chaque page refondue suit — elles complètent
[`../frontend/design-system.md`](../frontend/design-system.md), elles ne la
remplacent pas.

1. **Une page, une action primaire.** Un seul bouton plein (bleu marine) par
   page, en haut à droite ou dans le contenu principal ; les autres sont
   secondaires (contour) ou dans un menu « … ».
2. **En-tête identique partout** : fil d'Ariane (si sous-page), titre,
   sous-titre d'une phrase, action primaire. Pas de rangée de KPI par défaut.
3. **Un chiffre doit mener quelque part.** Un KPI est cliquable et filtre la
   liste ; sinon il n'est pas affiché. Un 0 qui n'appelle aucune action est
   retiré.
4. **Jamais de donnée inventée.** Inconnu → dit en mots, une fois. Pas de
   courbe, de score ou de tendance sans calcul derrière. Les données de démo
   restent identifiées comme telles.
5. **Liste → détail à droite.** Le panneau existant, l'élément dans l'URL, au clavier.
6. **Chaque écran a ses états** : vide (ce qu'on peut faire), chargement
   (squelette à la forme du contenu), erreur (ce qui s'est passé + réessayer),
   partiel/obsolète (bandeau discret avec la fraîcheur), permission
   (lecture seule expliquée), succès/échec d'action (toast). Les composants
   existent déjà (`components/states`) : les utiliser partout.
7. **La réassurance a une place** : le parcours d'intention. Pas un bandeau
   par page.
8. **Rien d'annoncé qui n'existe pas** (« Dictée — Bientôt »).

## Composants à modifier

| Composant | Changement |
| --- | --- |
| `components/shell/page-container.tsx` | `PageHeader` existe déjà et sert partout (fil d'Ariane, titre, sous-titre, actions) : rien à refaire, seulement y faire passer une seule action primaire |
| Cartes KPI (dupliquées dans `overview`, `approvals`, `sources`, `team`, `billing`, `capabilities`, `activity`) | Un seul composant `StatCard` : cliquable, hauteur au contenu, masqué quand rien à dire |
| Panneaux de détail (`approvals/*-panel.tsx`, `sources/source-panel.tsx`, `intentions/intentions-list.tsx`) | L'élément ouvert dans l'URL, ouverture à l'arrivée sur grand écran |
| `components/states/*` | Généraliser : état vide avec action, partiel/obsolète |
| Bandeaux bas de page | Retirés, sauf parcours d'intention |
| `lib/i18n` | Pluriels réels à la place des « (s) » |

## Plan de livraison proposé

1. **Cette PR** : l'audit, à valider (Bilal, Karim).
2. **Fondations** : `StatCard` partagé, panneau ouvert depuis l'URL, états, pluriels —
   une PR, aucune page ne change d'apparence brutalement.
3. **Pages**, par ordre de parcours : Nouvelle intention (2 → 5) → À valider →
   Vue d'ensemble → Mes intentions → Sources → Capacités → Sécurité &
   gouvernance → le reste. Une PR par page ou petit groupe, avec captures
   avant/après (1440 et 1280 px) et vérification au clavier.
4. **Validation finale** : la checklist ci-dessous sur l'application réelle.

## Checklist de validation (par page refondue)

- [ ] Le menu et la navigation sont identiques avant/après (capture comparée).
- [ ] Une seule action primaire, identifiable sans lire les cartes.
- [ ] 1440 px et 1280 px sans débordement ; mobile lisible.
- [ ] Tout au clavier : tabulation dans l'ordre, focus visible, Échap ferme
      les panneaux.
- [ ] Contraste AA (axe, déjà dans les tests e2e).
- [ ] États vérifiés : vide, chargement, erreur, partiel/obsolète, permission
      insuffisante, action réussie, action échouée.
- [ ] Aucune valeur affichée sans source réelle.
- [ ] Captures avant/après jointes à la PR.

## Limites de cet audit

- Les étapes 2 à 5 du parcours d'intention et la fiche d'un élément n'ont
  pas été vues en conditions réelles : l'espace de démo n'a pas d'intention et
  aucun modèle de langage n'est configuré en local. À faire au début du lot
  « Nouvelle intention ».
- Paramètres non audité.
- Vu à 1440 px seulement ; 1280 px et mobile au moment de chaque page.
