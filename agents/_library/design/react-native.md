---
titre: "Le mouvement dans une application React Native ou Expo"
description: "Animer une application React Native ou Expo pour qu'elle se sente juste sur un vrai appareil : les trois réalités du téléphone, animer ou non, l'outil le plus léger, rester sur le fil de l'interface, les propriétés, ressorts et courbes, l'appui, le retour haptique, le mouvement réduit, les pièges silencieux, des recettes par situation et ce qu'on ne livre jamais."
---

# Le mouvement dans une application React Native ou Expo

## Trois réalités du téléphone

1. **Pas de survol.** Ce que le web met au survol vit dans l'appui, dans la
   position, ou nulle part.
2. **Deux fils.** Celui de React (rendu, logique) et celui de l'interface, où
   les worklets tournent à chaque image. Une animation qui passe par le premier
   saccade dès que l'application travaille ; tout l'enjeu est de rester sur le
   second.
3. **Le doigt est sur l'élément.** Interrompre et transmettre la vitesse ne
   sont pas un luxe : c'est la base.

Deux façons de rater, la première pire : animer ce qui devait rester immobile,
et animer sur le mauvais fil (un `setState` par image, un `PanResponder`, une
hauteur animée), fluide en développement sur un téléphone récent, 20 images
par seconde sur un Android de trois ans.

Ce que LEKA s'impose : les décisions dans l'ordre ; Reanimated plutôt que
l'`Animated` du cœur ; aucune valeur approchée ; le mouvement réduit fait partie
de l'animation ; le ressenti se juge sur une version de production, sur
l'appareil le plus lent qu'on prend en charge.

## Animer ou non

| Usage | Décision |
| --- | --- |
| des centaines de fois par jour : onglets, clavier, défilement, interrupteurs de réglages | rien : le comportement de la plateforme, ou aucun mouvement |
| des dizaines de fois : appui, parcours d'une liste, sélection | presque imperceptible, sous 150 ms, ou rien |
| de temps en temps : feuilles, modales, notifications, étapes d'accueil | une animation standard |
| rarement : réussite, état vide illustré, moment marquant | on peut se faire plaisir |

**Les onglets ne glissent jamais** : ce sont des égaux, pas une hiérarchie
(`animation: 'none'`). Et chaque animation a une raison : confirmer, orienter,
dire un état, éviter une rupture, expliquer, ou, rarement, faire plaisir.

## L'outil le plus léger

| Besoin | Outil |
| --- | --- |
| un changement d'état sans geste (appui, bascule, couleur) | une transition CSS de Reanimated (`transitionProperty` dans le style) |
| une boucle, plusieurs étapes, une animation au montage | une animation CSS de Reanimated (`animationName`) |
| un élément qui apparaît ou disparaît, une liste qui se réorganise | les animations de mise en page (`entering`, `exiting`, `itemLayoutAnimation`) |
| ce que touche un doigt, ce qui suit le défilement | `useSharedValue`, `Gesture`, `useAnimatedStyle` |
| d'un écran à l'autre | les options de la pile native d'Expo Router, jamais refaites à la main |
| une feuille qui est son propre écran | `presentation: 'formSheet'` |
| la barre d'onglets | les onglets natifs d'Expo Router |
| un menu contextuel, un aperçu à l'appui long (iOS) | `Link.Menu`, `Link.Preview` |
| un en-tête qui se replie en grand titre (iOS) | `headerLargeTitleEnabled` |
| tirer pour rafraîchir | `RefreshControl` |
| une interface qui suit le clavier | `react-native-keyboard-controller` |
| une illustration, une célébration | Lottie, jamais pour un état d'interface |
| une très grande scène animée, du dessin libre | Skia |

Une valeur partagée seulement pour ce qui est continu ou interruptible : un
appui est une transition, un glisser est une valeur partagée. Les dépendances
s'installent avec `npx expo install`, qui choisit la version du SDK ; dans un
livrable de LEKA, une dépendance manquante est une recommandation, jamais une
modification silencieuse.

## Rester sur le fil de l'interface

- **Aucun `setState` dans un geste ou un défilement** : un rendu par image est
  la première cause de saccade. Une valeur partagée et `useAnimatedStyle` ne
  font pas rendre React.
- **Aucun retour vers React dans `onUpdate` ou un défilement** :
  `scheduleOnRN(fn, ...args)` (qui remplace `runOnJS`) va dans `onEnd`, ou
  dans un `useAnimatedReaction` au passage d'un seuil.
- **Jamais lire ni écrire une valeur partagée pendant le rendu.**
- `.get()` et `.set()` plutôt que `.value`, compatibles avec le compilateur
  React.
- Une fonction appelée depuis un worklet commence par `'worklet'`.

## Les propriétés

- `transform` et `opacity` ne coûtent rien ; tout le reste relance la mise en
  page de l'élément et de ses voisins (`width`, `height`, `margin`, `padding`,
  `flex`, `top`, `left`, `gap`).
- **Une exception** : un élément en position absolue sans enfants (la pilule
  d'un segment, le remplissage d'une jauge) ; animer sa largeur garde ses coins
  arrondis, qu'un `scaleX` déformerait.
- Rien ne part de `scale(0)` : de 0,9 à 0,97, avec l'opacité.
- `transform` est une liste et l'ordre compte : déplacer d'abord, sauf
  intention contraire.
- Sur Android, animer `elevation` redessine l'ombre à chaque image : on fait
  varier l'opacité d'une couche déjà ombrée.
- On n'anime jamais l'intensité d'un `BlurView` : on fait varier l'opacité
  d'un flou fixe.
- `translateY('100%')` déplace un élément de sa propre hauteur.

## Ressorts et courbes

**Un doigt en jeu : un ressort. Sinon : une courbe.**

| Situation | Ressort |
| --- | --- |
| se poser sans dépasser | `{ duration: 400, dampingRatio: 1 }` |
| revenir en place après un glisser | `{ duration: 400, dampingRatio: 0.8, velocity }` |
| feuille, tiroir | `{ duration: 300, dampingRatio: 0.8, velocity }` |
| ne doit pas dépasser un bord | ajouter `overshootClamping: true` |

Le rebond seulement quand le geste portait un élan. Sans doigt : la courbe
d'entrée pour ce qui entre et sort, la courbe de déplacement pour ce qui change
de place, `linear` pour une progression ; **jamais `Easing.in`** sur
l'interface. Les courbes par défaut sont trop molles, on reprend celles de
LEKA :

```js
import { Easing } from "react-native-reanimated";
export const EASE_ENTER = Easing.bezier(0.16, 1, 0.3, 1);
export const EASE_MOVE = Easing.bezier(0.65, 0, 0.35, 1);
export const EASE_SHEET = Easing.bezier(0.32, 0.72, 0, 1);
```

| Élément | Durée |
| --- | --- |
| appui | 100 à 150 ms |
| bascule, puce | 150 à 200 ms |
| feuille, modale | un ressort d'environ 300 ms perçus |
| transition d'écran | celle de la plateforme, sans y toucher |

L'interface reste sous 300 ms.

## L'appui à la place du survol

- Le retour au contact, la validation au relâchement.
- `scale: 0.97` en 100 à 150 ms sur tout ce qui se presse (`Pressable` et une
  transition).
- Une cible de 44 × 44 points (48 dp sur Android) : `hitSlop` plutôt qu'un
  visuel plus grand ; `pressRetentionOffset` pour qu'un doigt qui glisse un peu
  n'annule pas l'appui.
- L'onde d'Android seulement dans une application au style Material.

## Le retour haptique

| Moment | Appel |
| --- | --- |
| une valeur passe un cran (sélecteur, curseur, segment) | `Haptics.selectionAsync()` |
| un élément se pose, une feuille accroche un cran | `Haptics.impactAsync(Light)` |
| un objet lourd atterrit, une action destructive part | `Haptics.impactAsync(Medium)` |
| réussite, échec | `Haptics.notificationAsync(Success)` ou `(Error)` |

Dans la même image que le visuel ; un seul par action, jamais au défilement ni
à chaque image ; jamais le seul retour, beaucoup de gens le désactivent.

## Mouvement réduit et texte agrandi

`useReducedMotion()`, ou `reduceMotion: ReduceMotion.System` sur chaque
animation : moins et plus doux, jamais zéro. L'opacité et la couleur restent ;
les déplacements, échelles, parallaxes et rebonds partent ; les transitions
d'écran deviennent des fondus. Le texte peut grandir : on ne vise jamais une
hauteur écrite en dur, on mesure avec `onLayout` ou on anime une transformation.

## Les pièges silencieux

- Une version de Reanimated qui ne correspond pas au SDK (installer par
  Expo) ; hors Expo, le plugin Babel des worklets absent ou mal placé.
- Pas de `GestureHandlerRootView` autour de l'application : les gestes ne font
  rien, sans erreur.
- Reanimated 4 demande la nouvelle architecture.
- Expo Go ne permet pas de juger la fluidité : une version de production.
- Sur les iPhone à 120 Hz, `CADisableMinimumFrameDurationOnPhone` doit être
  activé pour dépasser 60 images par seconde ; le budget est alors de 8 ms par
  image.

## Recettes, par situation

**Un bouton qu'on presse.** `Pressable`, un état pressé, un style avec
`transitionProperty: 'transform'`, `transitionDuration: '120ms'`,
`transitionTimingFunction: 'cubic-bezier(0.16, 1, 0.3, 1)'`, et
`transform: [{ scale: 0.97 }]` à l'appui ; `hitSlop={12}`.

**Une feuille qu'on glisse pour fermer** (si elle vit dans un écran existant ;
sinon `formSheet`). `Gesture.Pan()` avec `activeOffsetY([-10, 10])` ; à
`onStart`, garder la position affichée ; à `onUpdate`, suivre, et résister
au-dessus du haut ; à `onEnd`, projeter l'élan : au-delà de 40 % de la hauteur,
fermer avec un ressort sans dépassement et `overshootClamping`, sinon revenir
avec un ressort à 0,8 et un léger retour haptique. Le voile dérive de la même
valeur par `interpolate`.

**Une ligne qu'on balaie pour la supprimer.** `ReanimatedSwipeable` si la ligne
révèle des actions ; sinon un `Gesture.Pan()` avec `activeOffsetX` (sans quoi
il vole le défilement vertical), la projection de l'élan, et
`itemLayoutAnimation` sur la liste pour refermer le trou.

**Un en-tête qui se replie au défilement.** `useAnimatedScrollHandler` vers une
valeur partagée, puis un `interpolate` de l'opacité et d'un léger `translateY`,
toujours avec `Extrapolation.CLAMP` ; jamais la hauteur de l'en-tête.

**Une liste qui arrive.** Un `FadeInDown` par ligne avec un délai de 30 à 80 ms
par index, mémorisé ; **jamais `entering` sur une liste virtualisée** : les
lignes recyclées rejoueraient l'animation au défilement.

**Suivre le clavier.** `KeyboardProvider` à la racine, puis
`useReanimatedKeyboardAnimation()`, dont la hauteur pilote un `translateY` ;
jamais un écouteur du clavier avec une durée choisie au hasard.

**Un indicateur de segment.** Mesurer les positions une fois avec `onLayout`,
puis animer `translateX` et la largeur de la pilule (absolue, sans enfants) en
250 ms avec la courbe de déplacement ; le retour haptique à l'appui.

**Les transitions d'écran.** La pile native : `presentation: 'modal'` pour une
tâche qu'on peut abandonner, `'formSheet'` avec des crans pour une courte
interruption (trois crans au plus sur Android) ; `animation: 'none'` entre
onglets, `'fade'` en mouvement réduit ; `animationMatchesGesture: true` dès
qu'on change l'animation.

**Une notification.** Entrée et sortie par le même bord, sortie un peu plus
rapide que l'entrée, sous 300 ms, dans les marges de sécurité.

**Réagir une fois au passage d'un seuil.** `useAnimatedReaction`, qui compare
sur le fil de l'interface et n'appelle React qu'au changement.

## Ce qu'on ne livre jamais

| Jamais | À la place |
| --- | --- |
| `PanResponder` | `Gesture.Pan()` |
| `setState` dans un geste ou un défilement | une valeur partagée et `useAnimatedStyle` |
| `runOnJS` | `scheduleOnRN` |
| un appel à React à chaque image | `onEnd`, ou `useAnimatedReaction` |
| lire ou écrire une valeur partagée au rendu | `.get()` et `.set()` dans les worklets et les effets |
| l'`Animated` du cœur pour un geste | Reanimated |
| animer hauteur, largeur, marge, `flex` | `transform` et `opacity` (sauf l'absolu sans enfants) |
| animer l'intensité d'un flou ou `elevation` | l'opacité d'une couche fixe |
| `entering` sur une liste virtualisée | le conteneur, ou `itemLayoutAnimation` |
| une transition d'écran refaite en JavaScript | la pile native |
| des onglets qui glissent | `animation: 'none'` |
| `Easing.in` sur l'interface | la courbe d'entrée de LEKA |
| fermer seulement à partir d'une distance | la vitesse ou la distance |
| un arrêt net à une limite | une résistance |
| un retour haptique à chaque image, ou seul | un par validation, avec un visuel |
| juger dans Expo Go ou le simulateur | une version de production, sur l'appareil le plus lent |

## Ce qu'on rend

Le code proposé, puis quelques lignes : la fréquence et la raison (et ce qui a
été écarté), les réglages retenus (outil, propriétés, ressort ou courbe et
durée, fil), et ce qu'il faut essayer sur l'appareil : lancer, interrompre en
plein mouvement, inverser, sur le plus lent des Android disponibles.
