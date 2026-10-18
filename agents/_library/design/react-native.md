---
titre: Le mouvement dans une application React Native ou Expo
description: Animer une application React Native ou Expo pour qu'elle se sente juste sur un vrai appareil — animer ou non, le bon fil d'exécution, l'outil le moins coûteux (transitions Reanimated, animations de mise en page, valeurs partagées et gestes, navigation native), les propriétés, ressort ou courbe, l'appui à la place du survol, le retour haptique, le mouvement réduit, les pièges de configuration et des recettes.
---

# Le mouvement dans une application React Native ou Expo

Sur téléphone, trois choses changent tout :

1. **Il n'y a pas de survol** : ce que le web met au survol doit vivre dans
   l'appui, la position, ou nulle part.
2. **Il y a deux environnements d'exécution** : celui de React (le rendu, la
   logique) et celui de l'interface, où les worklets s'exécutent à chaque
   image. Une animation qui touche le premier saccade dès que l'application
   travaille. Tout l'art est de rester dans le second.
3. **Le doigt est sur l'élément** : l'interruption et la transmission de
   vitesse ne sont pas un luxe, c'est la base.

Deux échecs, le premier étant le pire : animer ce qui ne devait pas bouger, et
animer sur le mauvais fil (un `setState` par image, un `PanResponder`, une
hauteur animée) — fluide en développement sur un téléphone récent, 20 images
par seconde sur un Android de trois ans.

Règles : on suit la séquence ; Reanimated plutôt que l'`Animated` du cœur ;
aucune valeur approchée ; le mouvement réduit fait partie de l'animation ; le
ressenti se juge sur une version de production, sur l'appareil le plus lent
qu'on prend en charge.

## La séquence

### 1. Animer ou non ?

| Fréquence | Décision |
| --- | --- |
| des centaines de fois par jour (onglets, clavier, défilement, interrupteurs de réglages) | rien : le comportement de la plateforme, ou aucun |
| des dizaines de fois (appui, navigation dans une liste, sélection) | presque imperceptible : moins de 150 ms, ou rien |
| de temps en temps (feuilles, modales, notifications, étapes d'accueil) | une animation standard |
| rarement (réussite, état vide illustré, célébration) | le budget plaisir |

**On ne fait jamais glisser les onglets** : ce sont des égaux, pas une
hiérarchie ; `animation: 'none'`.

### 2. Pour quoi ?

Retour, continuité spatiale, indication d'état, éviter une rupture,
explication, plaisir (rare seulement). Sans raison, on s'arrête.

### 3. L'outil le moins coûteux

| Besoin | Outil |
| --- | --- |
| un changement d'état sans geste (appui, bascule, couleur) | une transition CSS de Reanimated (`transitionProperty` dans le style) |
| une boucle, plusieurs étapes, une animation au montage | une animation CSS de Reanimated (`animationName`) |
| un élément qui apparaît, disparaît, une liste qui se réorganise | les animations de mise en page (`entering`, `exiting`, `itemLayoutAnimation`) |
| ce que touche un doigt, ce qui dépend du défilement | `useSharedValue` + `Gesture` + `useAnimatedStyle` |
| d'un écran à l'autre | les options de la pile native d'Expo Router — jamais refait à la main |
| une feuille qui est son propre écran | `presentation: 'formSheet'` |
| la barre d'onglets | les onglets natifs d'Expo Router |
| menu contextuel, aperçu à l'appui long | `Link.Menu` / `Link.Preview` (iOS) |
| un en-tête qui se replie en grand titre | `headerLargeTitleEnabled` de la pile native (iOS) |
| tirer pour rafraîchir | `RefreshControl` |
| une interface qui suit le clavier | `react-native-keyboard-controller` |
| une illustration, une célébration | Lottie (jamais pour un état d'interface) |
| une très grande scène animée, du dessin libre | Skia |

Une valeur partagée seulement pour ce qui est continu ou interruptible : un
appui est une transition, un glisser est une valeur partagée.

Les dépendances s'installent avec `npx expo install`, qui choisit la version
qui va avec le SDK. Dans LEKA, une dépendance manquante est une
recommandation du livrable, jamais une modification silencieuse.

### 4. Les propriétés

- `transform` et `opacity` sont gratuits ; tout le reste relance la mise en
  page de l'élément et de ses voisins (`width`, `height`, `margin`,
  `padding`, `flex`, `top`, `left`, `gap`).
- **L'exception** : un élément positionné en absolu, sans enfants (une pilule
  d'onglet, le remplissage d'une jauge) — animer sa largeur garde ses coins
  arrondis, ce qu'un `scaleX` déformerait.
- Jamais depuis `scale(0)` : `0.9` à `0.97`, avec l'opacité.
- `transform` est une liste, et l'ordre compte : déplacer d'abord, sauf
  intention contraire.
- Sur Android, animer `elevation` redessine l'ombre à chaque image : on fait
  plutôt varier l'opacité d'une couche déjà ombrée.
- On n'anime jamais l'intensité d'un `BlurView` : on fait varier l'opacité
  d'un flou fixe.
- `translateY('100%')` déplace un élément de sa propre hauteur.

### 5. Ressort ou courbe

**Si un doigt était en jeu, un ressort.** Sinon, une courbe. Les ressorts se
règlent par la durée et l'amortissement :

| Interaction | Réglage |
| --- | --- |
| se poser sans dépasser | `{ duration: 400, dampingRatio: 1 }` |
| revenir en place après un glisser | `{ duration: 400, dampingRatio: 0.8, velocity }` |
| feuille, tiroir | `{ duration: 300, dampingRatio: 0.8, velocity }` |
| ne doit pas dépasser un bord | ajouter `overshootClamping: true` |

Le rebond seulement quand le geste portait un élan. Sans doigt : `ease-out`
pour entrer et sortir, `ease-in-out` pour un déplacement, `linear` pour une
progression ; **jamais `Easing.in`** sur l'interface. Les courbes intégrées
sont trop molles :

```js
import { Easing } from "react-native-reanimated";
const EASE_OUT = Easing.bezier(0.23, 1, 0.32, 1);
const EASE_IN_OUT = Easing.bezier(0.77, 0, 0.175, 1);
const EASE_SHEET = Easing.bezier(0.32, 0.72, 0, 1);
```

Durées : appui 100–150 ms ; bascule, puce 150–200 ms ; feuille, modale :
ressort d'environ 300 ms perçus ; transition d'écran : celle de la
plateforme, sans y toucher. Moins de 300 ms pour l'interface.

### 6. Rester hors du fil de React

- **Jamais de `setState` dans un geste ou un défilement** : un rendu par
  image est la première cause de saccade. Valeur partagée et
  `useAnimatedStyle` : React ne se redessine pas.
- **Jamais de retour vers React dans `onUpdate` ou un défilement** :
  `scheduleOnRN(fn, ...args)` (qui remplace `runOnJS`) va dans `onEnd`, ou
  dans un `useAnimatedReaction` au passage d'un seuil.
- **Jamais lire ou écrire une valeur partagée pendant le rendu.**
- `.get()` / `.set()` plutôt que `.value` (compatible avec le compilateur
  React).
- Une fonction appelée depuis un worklet commence par `'worklet'`.

### 7. L'appui à la place du survol

- Le retour à l'appui, la validation au relâchement.
- `scale: 0.97` en 100–150 ms sur tout ce qui se presse (`Pressable` et une
  transition).
- Cible de 44 × 44 points (48 dp sur Android) : `hitSlop` plutôt qu'un visuel
  plus grand ; `pressRetentionOffset` pour qu'un doigt qui glisse un peu
  n'annule pas l'appui.
- L'effet d'onde d'Android seulement dans une application au style Material.

### 8. Le retour haptique

| Moment | Appel |
| --- | --- |
| une valeur passe un cran (sélecteur, curseur, segment) | `Haptics.selectionAsync()` |
| un élément se pose, un cran de feuille accroche | `Haptics.impactAsync(Light)` |
| un objet lourd atterrit, une action destructive part | `Haptics.impactAsync(Medium)` |
| réussite, échec | `Haptics.notificationAsync(Success / Error)` |

Dans la même image que le visuel ; un seul par action, jamais au défilement
ni à chaque image ; jamais le seul retour (beaucoup de personnes le coupent).

### 9. Mouvement réduit et texte agrandi

`useReducedMotion()`, ou `reduceMotion: ReduceMotion.System` sur chaque
animation : moins et plus doux, pas zéro — l'opacité et la couleur restent,
les déplacements, échelles, parallaxes et rebonds partent ; les transitions
d'écran deviennent des fondus. Le texte peut grandir : on ne vise jamais une
hauteur codée en dur, on mesure avec `onLayout` ou on anime une
transformation.

## Ce qui casse le mouvement sans prévenir

- Une version de Reanimated qui ne correspond pas au SDK (installer par
  Expo) ; le plugin Babel des worklets absent ou mal placé hors Expo.
- `GestureHandlerRootView` qui n'enveloppe pas l'application : les gestes ne
  font rien, sans erreur.
- Reanimated 4 demande la nouvelle architecture.
- Expo Go n'est pas un lieu pour juger la fluidité : une version de
  production.
- Sur les iPhone à 120 Hz, `CADisableMinimumFrameDurationOnPhone` doit être
  activé pour dépasser 60 images par seconde — budget de 8 ms par image.

## Recettes

**Un appui** : `Pressable`, un état pressé, un style avec
`transitionProperty: 'transform'`, `transitionDuration: '120ms'`,
`transitionTimingFunction: 'cubic-bezier(0.23, 1, 0.32, 1)'`, et
`transform: [{ scale: 0.97 }]` à l'appui ; `hitSlop={12}`.

**Une feuille qu'on glisse pour fermer** (seulement si elle vit dans un écran
existant ; sinon `formSheet`) : `Gesture.Pan()` avec `activeOffsetY([-10,
10])` ; à `onStart`, mémoriser la position affichée ; à `onUpdate`, suivre,
et résister au-dessus du haut ; à `onEnd`, projeter l'élan : au-delà de 40 %
de la hauteur, fermer avec un ressort sans dépassement et
`overshootClamping`, sinon revenir avec un ressort à 0,8 et un léger retour
haptique. Le voile dérive de la même valeur par `interpolate`.

**Glisser pour supprimer une ligne** : `ReanimatedSwipeable` quand la ligne
révèle des actions ; sinon un `Gesture.Pan()` avec `activeOffsetX` (sans quoi
il vole le défilement vertical), la projection de l'élan, et
`itemLayoutAnimation` sur la liste pour refermer le trou.

**Un en-tête qui se replie au défilement** : `useAnimatedScrollHandler` vers
une valeur partagée, un `interpolate` de l'opacité et d'un léger
`translateY`, toujours avec `Extrapolation.CLAMP` ; jamais la hauteur de
l'en-tête.

**L'entrée d'une liste** : un `FadeInDown` par ligne avec un délai par index
de 30 à 80 ms, mémorisé ; **jamais `entering` sur une liste virtualisée**
(les lignes recyclées rejouent l'animation au défilement).

**Suivre le clavier** : `KeyboardProvider` à la racine, puis
`useReanimatedKeyboardAnimation()` dont la hauteur pilote un `translateY` —
jamais un écouteur du clavier avec une durée choisie au hasard.

**Un indicateur de segment** : mesurer les positions une fois avec
`onLayout`, puis animer `translateX` et la largeur de la pilule (positionnée
en absolu, sans enfants) en 250 ms `ease-in-out` ; le retour haptique à
l'appui.

**Les transitions d'écran** : la pile native ; `presentation: 'modal'` pour
une tâche qu'on peut abandonner, `'formSheet'` avec des crans pour une courte
interruption (trois crans au plus sur Android) ; `animation: 'none'` entre
onglets, `'fade'` en mouvement réduit ; `animationMatchesGesture: true` dès
qu'on change l'animation.

**Une notification** : entrée et sortie au même bord, sortie un peu plus
rapide que l'entrée, sous 300 ms, en respectant les marges de sécurité.

**Déclencher une fois au passage d'un seuil** : `useAnimatedReaction` qui
compare sur le fil de l'interface et n'appelle React qu'au changement.

## À ne jamais livrer

| Jamais | À la place |
| --- | --- |
| `PanResponder` | `Gesture.Pan()` |
| `setState` dans un geste ou un défilement | valeur partagée + `useAnimatedStyle` |
| `runOnJS` | `scheduleOnRN` |
| un appel à React à chaque image | `onEnd`, ou `useAnimatedReaction` |
| lire ou écrire une valeur partagée au rendu | `.get()` / `.set()` dans worklets et effets |
| l'`Animated` du cœur pour un geste | Reanimated |
| animer hauteur, largeur, marge, flex | `transform` et `opacity` (sauf l'absolu sans enfants) |
| animer l'intensité d'un flou ou `elevation` | l'opacité d'une couche fixe |
| `entering` sur une liste virtualisée | le conteneur, ou `itemLayoutAnimation` |
| une transition d'écran refaite en JavaScript | la pile native |
| des onglets qui glissent | `animation: 'none'` |
| `Easing.in` sur l'interface | `Easing.bezier(0.23, 1, 0.32, 1)` |
| fermer seulement à partir d'une distance | la vitesse ou la distance |
| un arrêt net à une limite | une résistance |
| du retour haptique à chaque image, ou seul | un par validation, avec un visuel |
| juger dans Expo Go ou le simulateur | une version de production, l'appareil le plus lent |

## Ce qu'on rend

Le code proposé, puis en quelques lignes : fréquence et raison (et ce qui a
été écarté), les ingrédients (outil, propriétés, ressort ou courbe et durée,
fil), et ce qu'il faut essayer sur l'appareil (lancer, interrompre en plein
mouvement, inverser, sur le plus lent des Android disponibles).
