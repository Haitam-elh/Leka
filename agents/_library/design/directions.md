---
titre: Proposer des directions de design
description: Proposer deux ou trois versions vraiment différentes d'un écran ou d'un composant, chacune sur un axe nommé (mise en page, densité, personnalité, mouvement, interaction), chacune au niveau d'exigence, avec ce qu'elle apporte et ce qu'elle coûte — ce que le simulateur de LEKA dessine côte à côte.
---

# Proposer des directions de design

Quand on propose un nouveau design, toute la valeur est dans la
**divergence** : trois nuances de la même idée n'apprennent rien. Chaque
proposition est une direction qu'on pourrait défendre seule, une autre
réponse à la même demande.

La divergence n'excuse pas une exécution faible : chaque proposition tient la
barre de `principes.md` — `ease-out` aux entrées, jamais `ease-in`, moins de
300 ms, l'origine juste, `transform` et `opacity`, le mouvement réduit. Une
proposition bâclée n'élargit pas l'exploration ; elle perd sur l'exécution
et n'apprend rien sur sa direction.

## 1. Cadrer

Une chose à la fois. Si la demande couvre plusieurs écrans (« le tableau de
bord »), on prend l'élément qui a le plus d'effet, on dit lequel et pourquoi,
et on propose le reste ensuite. On reformule la demande en une phrase : ce
qu'est l'élément, où il vit, ce qu'il doit faire.

## 2. Reconnaître le terrain

- **La pile** : framework, styles, bibliothèque d'animation.
- **Les jetons** : couleurs, rayons, espacements, polices, courbes et durées.
  Chaque proposition les emploie : elle doit pouvoir partir en production
  demain dans ce produit.
- **La personnalité** : un outil net de tous les jours, ou une application
  grand public — elle borne la proposition la plus audacieuse.
- **Le contexte** : sur quel fond, à côté de quoi, à quelles tailles.

## 3. Choisir les directions

Deux ou trois, cinq au plus si la demande le veut. Avant tout dessin, la
liste : un **nom qui décrit la direction** (« Calme », « Éditorial »,
« Dense », « Guidé ») — jamais « Option A » — et un **axe** :

- la mise en page (la colonne, la grille, l'ordre des sections) ;
- la densité (ce qu'on voit sans défiler) ;
- la personnalité (sobre, chaleureuse, technique) ;
- le mouvement (immobile, retours seulement, mise en scène) ;
- le modèle d'interaction (tout visible, divulgation progressive, guidé).

Si deux propositions ne diffèrent que par une couleur ou un libellé, c'est la
même : on en remplace une. Aucune proposition n'invente une fonction, un
chiffre ou un texte que le produit n'a pas.

## 4. Dans LEKA : le simulateur

Le designer ne dessine pas lui-même : il décrit l'écran d'aujourd'hui avec ses
valeurs, puis chaque direction élément par élément, avec ses valeurs, et
LEKA dessine l'écran d'aujourd'hui et chaque direction, côte à côte, sur
bureau, tablette et téléphone. Une description précise donne un dessin
fidèle : l'ordre des sections, les textes exacts, les couleurs, tailles,
espacements, rayons et ombres en valeurs.

## 5. Présenter honnêtement

| # | Direction | Axe | Quand c'est le bon choix | Ce qu'elle coûte |
| --- | --- | --- | --- | --- |
| 1 | Calme | peu de mouvement, des filets plutôt que des ombres | un outil de tous les jours | moins mémorable |
| 2 | Éditorial | grande typographie, beaucoup d'air | un moment qui mérite du poids | prend de la hauteur |

Une ligne pour ce qui la fait gagner, une pour ce qu'elle coûte. On ne
pré-choisit pas dans le tableau ; quand on recommande, c'est avec une raison
tirée de la personnalité du produit et de la fréquence d'usage, pas du seul
goût. Si deux directions ont convergé en chemin, on en retire une et on le
dit : deux directions franches valent mieux que trois gonflées.
