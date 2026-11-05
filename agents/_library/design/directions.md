---
titre: "Proposer des directions de design"
description: "Proposer deux ou trois versions vraiment différentes d'un écran ou d'un composant, chacune sur un axe nommé (mise en page, densité, caractère, mouvement, interaction) et tenue à la barre de qualité de LEKA : cadrer, lire le terrain, choisir les directions, les faire dessiner par le simulateur de LEKA et les présenter honnêtement."
---

# Proposer des directions de design

Une proposition de design vaut par sa **divergence** : trois variantes de la
même idée n'apprennent rien. Chaque direction doit pouvoir se défendre seule,
comme une autre réponse à la même demande.

Diverger n'excuse pas une exécution faible. Chaque direction tient la barre de
`principes.md` : courbe d'entrée sur ce qui arrive, jamais `ease-in`, moins de
300 ms, la bonne origine, `transform` et `opacity`, le mouvement réduit. Une
direction bâclée perd sur l'exécution et ne dit rien sur son idée.

## 1. Cadrer

Une chose à la fois. Si la demande couvre plusieurs écrans (« le tableau de
bord »), on prend l'élément qui a le plus d'effet, on dit lequel et pourquoi,
et on garde le reste pour la suite. On reformule la demande en une phrase : ce
qu'est l'élément, où il vit, ce qu'il doit permettre.

## 2. Lire le terrain

| Ce qu'on lit | Pourquoi |
| --- | --- |
| la pile : framework, styles, bibliothèque d'animation | la direction doit s'écrire avec |
| les jetons : couleurs, rayons, espacements, polices, courbes, durées | chaque direction les emploie et pourrait partir en production demain |
| le caractère du produit : outil net du quotidien ou application grand public | il borne la direction la plus audacieuse |
| le contexte : sur quel fond, à côté de quoi, à quelles tailles | une direction se juge en situation |

## 3. Choisir les directions

Deux ou trois, cinq au plus si la demande le veut. Avant tout dessin, la liste :
chacune a un **nom qui la décrit** (« Calme », « Éditorial », « Dense »,
« Guidé », jamais « Option A ») et un **axe** :

- la mise en page : la colonne, la grille, l'ordre des sections ;
- la densité : ce qu'on voit sans défiler ;
- le caractère : sobre, chaleureux, technique ;
- le mouvement : immobile, retours seulement, mise en scène ;
- l'interaction : tout visible, divulgation progressive, parcours guidé.

Deux directions qui ne diffèrent que par une couleur ou un libellé n'en font
qu'une : on remplace l'une. Aucune direction n'invente une fonction, un chiffre
ou un texte que le produit n'a pas.

## 4. Les faire dessiner par LEKA

Le designer ne dessine pas : il décrit l'écran d'aujourd'hui avec ses valeurs,
puis chaque direction élément par élément, avec ses valeurs, et le simulateur
de LEKA dessine l'écran actuel et chaque direction côte à côte, sur bureau,
tablette et téléphone. Plus la description est précise, plus le dessin est
fidèle : l'ordre des sections, les textes exacts, les couleurs, tailles,
espacements, rayons et ombres en valeurs.

## 5. Présenter honnêtement

| # | Direction | Axe | Quand c'est le bon choix | Ce qu'elle coûte |
| --- | --- | --- | --- | --- |
| 1 | Calme | peu de mouvement, des filets plutôt que des ombres | un outil qu'on ouvre tous les jours | moins marquante |
| 2 | Éditorial | grande typographie, beaucoup d'air | un moment qui mérite du poids | prend de la hauteur |

Une ligne pour ce qui la fait gagner, une pour ce qu'elle coûte. Le tableau ne
choisit pas à l'avance ; une recommandation, s'il y en a une, s'appuie sur le
caractère du produit et la fréquence d'usage, pas sur le goût. Deux directions
qui se sont rejointes en chemin : on en retire une et on le dit. Deux directions
franches valent mieux que trois gonflées.
