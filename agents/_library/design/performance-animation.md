---
titre: "Une animation fluide"
description: "Tenir chaque image dans son budget : la démarche (recenser, diagnostiquer, rendre), les symptômes et leur remède, le budget par image, ce que coûte chaque propriété et par quoi la remplacer, le fil d'exécution, React, les variables héritées, le flou, will-change, et quand le JavaScript convient."
---

# Une animation fluide

Une revue de performance ne demande pas si l'animation est belle, mais si
chaque image arrive à temps. Une animation juste à 30 images par seconde est
une animation ratée.

Deux erreurs à éviter, la première surtout : **conclure sur une machine
rapide** (la référence est un téléphone moyen, et un écran à 120 Hz divise le
budget par deux) ; **poser `will-change` et s'arrêter là** (c'est le dernier
recours, pas le premier).

Ce que LEKA s'impose : `transform` et `opacity` par défaut, tout le reste se
justifie ; nommer la cause avant de toucher au code ; distinguer ce qui est
vérifié dans le code de ce qui demande un enregistrement sur appareil ;
jamais `transition: all` ; ne jamais sacrifier un comportement juste à une
optimisation que le navigateur peut refuser.

## La démarche

### 1. Recenser

Chaque animation du périmètre, avec son moteur, ses propriétés réelles
(`transition: all` et les raccourcis de Motion dépliés) et ce qui se passe en
même temps qu'elle :

| Élément | Moteur | Propriétés | Pendant |
| --- | --- | --- | --- |
| indicateur d'onglet | Motion, `layoutId` | mise en page | un changement de page |
| feuille | transition CSS | `transform` | un glisser |
| carte | transition CSS | `all` | un survol |

### 2. Diagnostiquer

Dans cet ordre, du plus fréquent au plus rare :

1. quelles propriétés s'animent vraiment ;
2. la saccade tombe-t-elle pendant un travail lourd (chargement, navigation,
   hydratation) ;
3. React se rend-il à chaque image ;
4. est-ce pire quand le contenu grandit ;
5. une variable CSS est-elle animée sur un parent ;
6. un flou dépasse-t-il 20 px ;
7. reste-t-il un décalage d'un pixel au début ou à la fin.

On confirme par un enregistrement : l'onglet Performance du navigateur pour
les images perdues et les tâches longues, l'inspecteur d'animations pour
ralentir. Sur un vrai téléphone moyen : ralentir le processeur d'un ordinateur
ne simule ni un petit processeur graphique ni une mémoire réduite.

### 3. Rendre

Pour chaque constat :

```
Élément : `fichier.tsx:42`
Cause : laquelle des causes ci-dessus
Avant : `transition: all 200ms` (anime `padding`, refait la mise en page)
Après : `transition: transform 200ms` avec `scale(0.97)`
Vérifié : dans le code / à enregistrer sur appareil
```

Trié par coût : la mise en page avant la peinture, le fil occupé avant le fil
libre.

## Symptômes et remèdes

| On voit | On fait |
| --- | --- |
| l'animation saccade | animer `transform` et `opacity`, pas `width`, `height`, `top`, `margin` |
| une ombre animée saccade | `filter: drop-shadow()` au lieu de `box-shadow`, ou un pseudo-élément ombré dont on anime l'opacité |
| ça saccade seulement pendant une navigation ou un chargement | passer en CSS ou en Web Animations API, hors du fil principal |
| les `x` / `y` de Motion perdent des images | une valeur `transform` complète |
| une animation écrite à la main saccade dans React | écrire dans `ref.current.style`, pas dans l'état |
| un glisser ralentit quand la liste grandit | cesser d'animer une variable héritée ; `transform` sur l'élément |
| un flou animé traîne, surtout dans Safari | rester sous 20 px de flou |
| des propriétés inattendues bougent | remplacer `transition: all` par la liste exacte |
| l'élément se décale d'un pixel au début ou à la fin | `will-change: transform`, seulement à ce moment-là |

## Le budget

À 60 images par seconde, 16,7 ms par image ; à 120 Hz, désormais courant,
8 ms. On vise le plus serré. Un recalcul de mise en page sur une page chargée
peut prendre plus de 100 ms : une douzaine d'images perdues d'un coup.

## Ce que coûte une propriété

| Niveau | Propriétés | Ce que fait le navigateur |
| --- | --- | --- |
| composition | `transform`, `opacity` (et selon les navigateurs `filter`, `clip-path`, `background-color`) | il déplace une couche déjà peinte : le moins cher |
| peinture | `box-shadow`, `border-radius`, `color` | il redessine l'élément à chaque image |
| mise en page | `width`, `height`, `padding`, `margin`, `top`, `left`, `border-width` | il recalcule la place de tout ce qui l'entoure : le plus cher |

Pour descendre d'un niveau :

| Au lieu de | Animer |
| --- | --- |
| `width`, `height`, `padding` pour grandir ou rétrécir | `scale()` |
| `top`, `left`, `margin` pour déplacer | `translate()`, en pourcentage de sa propre taille |
| `display` ou `visibility` | `opacity` |
| `box-shadow` | `filter: drop-shadow(…)` |

Une animation de mise en page ne saccade pas toujours (un élément en position
absolue, sans enfants), mais `padding` et `scale()` donnent le même rendu et
seul le second ne peut pas régresser sur un appareil plus lent. Animer la
marge d'une barre latérale déplace aussi tout le contenu voisin, à chaque
image.

## Où s'exécute l'animation

| Moteur | Fil |
| --- | --- |
| JavaScript image par image (`requestAnimationFrame`, bibliothèques qui l'utilisent) | toujours le fil principal |
| Web Animations API (`element.animate()`, l'`animate()` de Motion) | peut être accéléré |
| transitions et animations CSS | peuvent être accélérées |

Accéléré veut dire hors du fil principal : l'animation reste fluide quoi que
fasse le JavaScript, et c'est fiable pour `transform` et `opacity`. Le cas à
surveiller est **le mouvement qui joue pendant un travail lourd** : changement
de page, indicateur d'onglet pendant une navigation, tout ce qui accompagne un
chargement. Animé en JavaScript, il perd des images ; en CSS, il reste fluide.

Avec Motion :

```jsx
<motion.div animate={{ x: 100 }} />                          // fil principal : peut saccader
<motion.div animate={{ transform: "translateX(100px)" }} />  // peut être accéléré
```

Les raccourcis (`x`, `y`, `scale`, `rotate`) passent par des variables CSS,
jamais accélérées : on les garde quand rien ne charge en même temps, on passe
à la valeur complète quand l'animation doit survivre à un fil occupé.

L'accélération est un bonus que le navigateur peut refuser : ce n'est pas une
raison d'abandonner `translateY(100%)` pour un élément de taille inconnue. Le
comportement juste passe avant.

## React : jamais d'animation par l'état

Les bibliothèques animent hors du cycle de rendu. Le piège est l'animation
écrite à la main qui appelle `setState` à chaque image :

```jsx
setY(y);                                             // un rendu par image : des images perdues
ref.current.style.transform = `translateY(${y}px)`;  // aucun rendu
```

À chercher dans les gestionnaires `requestAnimationFrame`, `pointermove`,
`scroll` et de glisser.

## Deux pièges qui ont l'air corrects

- **Les variables héritées.** Écrire la distance d'un glisser dans une variable
  CSS que lit `translateY()` sur un parent recalcule le style de tous ses
  descendants à chaque image : plus il y a de contenu, plus c'est lent. On écrit
  `transform` sur l'élément lui-même.
- **Le flou.** `filter: blur()` coûte vite cher, surtout dans Safari. Moins de
  20 px ; 2 à 5 px suffisent à adoucir un fondu.

## `will-change`

Le passage d'une animation au processeur graphique peut décaler l'élément d'un
pixel au début ou à la fin ; `will-change: transform` prépare la couche à
l'avance. **Seulement quand on voit ce décalage ou qu'on a mesuré des images
perdues** : les navigateurs préparent déjà ce qui anime `transform` ou
`opacity`, et chaque couche coûte de la mémoire. Sur l'élément qui bouge,
jamais sur `*` ni sur un grand conteneur ; utile pour une peinture coûteuse
(un grand élément flouté), en gardant la couche petite, et retiré après.

## Le JavaScript, quand ?

Il ne pose problème que si la page est occupée pendant l'animation. Motion
apporte de vrais ressorts, la mise en page partagée, la sortie des éléments
démontés, les gestes avec élan. La répartition qui marche : le CSS pour le
simple et pour ce qui joue pendant un chargement ; Motion pour le complexe,
l'interruptible et le geste.
