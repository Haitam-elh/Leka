---
titre: Une animation fluide
description: Garder chaque image dans son budget — le budget par image, ce qu'une propriété coûte (composition, peinture, mise en page) et par quoi la remplacer, le fil principal et l'accélération matérielle, Motion, React qui se redessine à chaque image, les variables CSS héritées, le flou, will-change, l'ordre du diagnostic et la forme d'un constat.
---

# Une animation fluide

La question n'est jamais « est-ce que c'est beau ? » mais « chaque image
arrive-t-elle à temps ? ». Une animation juste qui tourne à 30 images par
seconde ne vaut rien : la performance est ce qui permet au bon mouvement
d'exister.

Deux pièges, le premier étant le pire : **conclure que tout va bien sur une
machine rapide** (la référence, c'est un téléphone moyen, et sur un écran à
120 Hz le budget est divisé par deux) ; **poser `will-change` et s'en
contenter** (c'est la dernière étape, pas la première).

Règles : `transform` et `opacity` par défaut, tout le reste se justifie ;
nommer la cause avant de changer le code ; ne jamais conclure depuis une
machine rapide — dire ce qui est vérifié dans le code et ce qui demande un
enregistrement sur appareil ; jamais `transition: all` ; ne pas sacrifier la
justesse à une optimisation que le navigateur accorde ou non.

## Le tableau des symptômes

| Ce qu'on voit | Ce qu'on fait |
| --- | --- |
| l'animation saccade | animer `transform` / `opacity`, pas `width`, `height`, `top`, `margin` |
| une ombre animée saccade | `filter: drop-shadow()` au lieu de `box-shadow` |
| ça saccade seulement pendant une navigation ou un chargement | passer l'animation en CSS ou WAAPI, hors du fil principal |
| les `x` / `y` de Motion perdent des images | la chaîne `transform` complète |
| une animation faite main saccade dans React | écrire dans `ref.current.style`, pas dans l'état |
| un glisser ralentit quand la liste grandit | ne plus animer une variable CSS héritée ; `transform` sur l'élément |
| un flou animé traîne (surtout Safari) | moins de 20 px de flou |
| des propriétés inattendues s'animent | remplacer `transition: all` par la liste exacte |
| l'élément se décale d'un pixel au début ou à la fin | `will-change: transform`, seulement à ce moment-là |

## Le budget

À 60 images par seconde, chaque image dispose de 16,7 ms ; à 120 Hz,
désormais courant, de 8 ms. On vise le plus petit. Un recalcul de mise en
page sur une page complexe peut prendre plus de 100 ms : une douzaine
d'images perdues, pas une.

## Ce qu'une propriété coûte

| Niveau | Propriétés | Coût |
| --- | --- | --- |
| composition seule | `transform`, `opacity` (et, selon les navigateurs, `filter`, `clip-path`, `background-color`) | le moins cher : l'élément a sa propre couche |
| peinture et composition | `box-shadow`, `border-radius`, `color` | on redessine à chaque image |
| mise en page, peinture et composition | `width`, `height`, `padding`, `margin`, `top`, `left`, `border-width` | le plus cher : un élément qui grandit déplace tout autour |

Pour descendre d'un niveau :

| Au lieu de | On anime |
| --- | --- |
| `width` / `height` / `padding` pour grandir ou rétrécir | `scale()` |
| `top` / `left` / `margin` pour déplacer | `translate()` (en pourcentage de sa propre taille) |
| une bascule `display` / `visibility` | `opacity` |
| `box-shadow` | `filter: drop-shadow(…)` |

Une animation de mise en page ne perd pas toujours des images (un élément
positionné en absolu, sans enfants) — mais `padding` et `scale()` rendent la
même chose et un seul des deux ne peut pas régresser sur un appareil plus
lent. Et animer la marge d'une barre latérale déplace aussi tout le contenu
d'à côté, à chaque image.

## Où l'animation s'exécute

| Moteur | Fil |
| --- | --- |
| JavaScript + `requestAnimationFrame` (bibliothèques image par image) | toujours le fil principal |
| WAAPI (`element.animate()`, l'`animate()` de Motion) | peut être accéléré |
| transitions et animations CSS | peuvent être accélérées |

Accéléré veut dire hors du fil principal : l'animation reste fluide quoi que
fasse le JavaScript. Fiables : `transform`, `opacity`. Le cas à surveiller est
**le mouvement qui joue pendant un travail lourd** : changement de page,
indicateur d'onglet pendant une navigation, tout ce qui accompagne un
chargement ou une hydratation. Un indicateur d'onglet animé en JavaScript au
moment où la page suivante se charge perd des images ; en CSS, il reste
fluide.

Avec Motion :

```jsx
<motion.div animate={{ x: 100 }} />                          // fil principal, peut saccader
<motion.div animate={{ transform: "translateX(100px)" }} />  // accéléré
```

Les raccourcis (`x`, `y`, `scale`, `rotate`) passent par des variables CSS,
qui ne sont pas accélérées. On les garde quand rien ne charge en même temps,
on passe à la chaîne quand l'animation doit survivre à un fil occupé.

L'accélération est un bonus que le navigateur peut refuser selon les
versions : ce n'est pas une raison d'abandonner `translateY(100%)` pour un
élément de taille inconnue. La justesse passe avant.

## React : ne pas animer par l'état

Les bibliothèques animent hors du cycle de rendu. Le piège, c'est une
animation faite main qui appelle `setState` à chaque image :

```jsx
setY(nouveauY);                                         // un rendu par image : perd des images
ref.current.style.transform = `translateY(${nouveauY}px)`; // aucun rendu
```

À chercher dans les gestionnaires `requestAnimationFrame`, `pointermove`,
`scroll` et de glisser.

## Deux pièges qui ont l'air corrects

- **Les variables CSS héritées** : écrire la distance d'un glisser dans une
  variable que lit `translateY()` sur le parent recalcule les styles de tous
  les descendants à chaque image. Plus il y a de contenu, plus c'est lent. On
  écrit `transform` sur l'élément.
- **Le flou** : `filter: blur()` coûte vite cher, surtout sur Safari. Moins de
  20 px ; 2 à 5 px suffisent pour adoucir un fondu.

## `will-change`

Le passage d'une animation du processeur au processeur graphique peut
décaler l'élément d'un pixel au début ou à la fin ; `will-change: transform`
le promeut d'avance. **Seulement quand on voit ce décalage ou qu'on a mesuré
des images perdues** : les navigateurs promeuvent déjà ce qui anime
`transform` ou `opacity`, et chaque couche coûte de la mémoire. Sur
l'élément qui bouge, jamais sur `*` ni sur un grand conteneur ; utile pour
une peinture coûteuse (un grand élément flouté), en gardant la couche
petite.

## Faut-il éviter l'animation en JavaScript ?

Non. Le fil principal ne pose problème que quand la page est occupée pendant
l'animation. Motion apporte de vrais ressorts, des animations de mise en
page partagée, des sorties d'éléments démontés, des gestes avec élan. La
répartition qui marche : CSS pour le simple et pour ce qui joue pendant un
chargement ; Motion pour le complexe, l'interruptible et le geste.

## La démarche

**1. Recenser** chaque animation du périmètre avec son moteur, ses
propriétés réelles (`transition: all` et les raccourcis de Motion dépliés)
et ce qui joue en même temps :

| Élément | Moteur | Propriétés | Joue pendant |
| --- | --- | --- | --- |
| indicateur d'onglet | Motion `layoutId` | mise en page | un changement de route |
| tiroir | transition CSS | `transform` | un glisser |
| carte au survol | transition CSS | `all` | un survol |

**2. Diagnostiquer**, dans cet ordre (du plus fréquent au plus rare) :
quelles propriétés s'animent ; la saccade coïncide-t-elle avec un travail
lourd ; React se redessine-t-il à chaque image ; est-ce pire quand le contenu
grandit ; une variable CSS est-elle animée ; un flou dépasse-t-il 20 px ;
reste-t-il un décalage d'un pixel. On confirme par un enregistrement
(l'onglet Performance pour les images perdues et les tâches longues,
l'inspecteur d'animations pour ralentir), sur un vrai téléphone moyen : le
ralentissement du processeur sur un ordinateur ne simule ni un petit
processeur graphique, ni une mémoire réduite.

**3. Rendre**, pour chaque constat :

```
Élément : `fichier.tsx:42`
Cause : <laquelle des causes ci-dessus>
Avant : `transition: all 200ms` (anime `padding`, recalcule la mise en page)
Après : `transition: transform 200ms` avec `scale(0.97)`
Vérifié : dans le code / à enregistrer sur appareil
```

Trié par coût : la mise en page avant la peinture, le fil occupé avant le
fil libre.
