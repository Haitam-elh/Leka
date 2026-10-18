---
titre: Les principes du design engineering
description: Le socle du designer de LEKA — comment juger une interface, le format d'un constat (avant, après, pourquoi), quand et comment animer, les composants qui donnent une impression de qualité, les gestes, la performance, l'accessibilité et la liste de contrôle d'une revue.
---

# Les principes du design engineering

Une interface réussie ne se remarque pas : chaque élément se comporte comme
la personne s'y attend, et elle passe à la suite sans y penser. C'est
l'addition de centaines de petites décisions justes — une courbe, une
durée, un état d'appui, une origine d'animation — qui donne l'impression
d'un produit soigné. Ce guide fixe ces décisions, avec leurs valeurs.

Trois convictions guident le jugement :

- **Le goût se travaille.** Ce n'est pas une préférence : c'est la capacité
  à voir pourquoi un détail élève l'ensemble. On le justifie toujours par
  une règle, jamais par « je préfère ».
- **Les détails invisibles s'additionnent.** Personne ne remarque un menu
  qui s'ouvre depuis son bouton ; tout le monde ressent une interface où
  rien n'est à sa place.
- **La qualité perçue est un avantage.** À fonctions égales, on choisit
  l'outil qui donne la meilleure sensation d'usage.

## Le format d'un constat

Chaque problème trouvé dans le code s'écrit dans un tableau, une ligne par
problème, jamais en liste « Avant : … / Après : … » :

| Avant | Après | Pourquoi |
| --- | --- | --- |
| `transition: all 250ms` | `transition: transform 180ms var(--ease-out), opacity 180ms var(--ease-out)` | `all` anime aussi des propriétés coûteuses que personne n'a choisies |
| `transform: scale(0)` à l'entrée | `transform: scale(0.96); opacity: 0` | rien n'apparaît de nulle part : on part d'une forme presque complète |
| menu ouvert en `ease-in` | `ease-out` avec une courbe forte | `ease-in` retarde le premier mouvement, celui que l'œil attend |
| bouton sans état `:active` | `transform: scale(0.97)` à l'appui | l'interface doit répondre au doigt ou au clic, immédiatement |
| popover centré sur lui-même | `transform-origin` sur son déclencheur | un menu naît du bouton qui l'ouvre (les modales, elles, restent centrées) |

Le pourquoi tient en une phrase et nomme la règle de ce guide qui fonde le
constat. L'emplacement (`fichier:ligne`) accompagne chaque ligne.

## Décider d'une animation

Quatre questions, dans cet ordre. Les deux premières décident si l'on
anime ; les deux suivantes, comment.

### 1. À quelle fréquence la personne la verra-t-elle ?

| Fréquence | Décision |
| --- | --- |
| Des centaines de fois par jour (raccourci clavier, palette de commandes, navigation principale) | Aucune animation |
| Des dizaines de fois par jour (survol, déplacement dans une liste, interrupteur courant) | La supprimer, ou la rendre presque imperceptible |
| De temps en temps (modale, tiroir, notification) | Une animation standard |
| Rarement, ou la première fois (accueil, réussite, célébration) | On peut se faire plaisir |

**Une action déclenchée au clavier ne s'anime jamais** : répétée sans cesse,
toute animation la rend lente et détachée du geste. Un outil ouvert cent
fois par jour s'ouvre instantanément.

### 2. À quoi sert-elle ?

Une animation doit pouvoir répondre à « pourquoi bouge-t-elle ? » par l'un
de ces mots :

- **Continuité spatiale** : une notification sort par où elle est entrée,
  ce qui rend le geste de la balayer évident.
- **Indication d'état** : un bouton qui se transforme montre que l'état a
  changé.
- **Explication** : une animation de présentation montre comment marche une
  fonction (pages marketing, premier usage).
- **Retour** : un bouton qui s'enfonce confirme que l'appui est pris.
- **Éviter une rupture** : un contenu qui apparaît ou disparaît sans
  transition donne une impression de panne.

« C'est joli » ne suffit pas pour un élément vu souvent.

### 3. Quelle courbe ?

- Un élément qui **entre ou sort** : `ease-out` — il démarre vite et paraît
  réactif.
- Un élément **déjà à l'écran qui se déplace ou se transforme** :
  `ease-in-out`.
- Un **survol, un changement de couleur** : `ease`.
- Un **mouvement continu** (défilement en boucle, barre de progression) :
  `linear`.
- Sinon : `ease-out`.

**`ease-in` n'a pas sa place dans une interface** : il démarre lentement, à
l'instant précis où l'œil regarde. À durée égale, `ease-out` paraît plus
rapide. Les courbes intégrées au CSS sont trop molles pour un mouvement
voulu : on les remplace par des courbes fortes, déclarées en jetons :

```css
--ease-out: cubic-bezier(0.23, 1, 0.32, 1);      /* entrées, sorties, retours */
--ease-in-out: cubic-bezier(0.77, 0, 0.175, 1);  /* déplacements à l'écran */
--ease-drawer: cubic-bezier(0.32, 0.72, 0, 1);   /* tiroir, à la manière d'iOS */
```

Une autre courbe se choisit dans une bibliothèque de courbes éprouvées,
jamais au hasard.

### 4. Quelle durée ?

| Élément | Durée |
| --- | --- |
| Retour d'appui d'un bouton | 100 à 160 ms |
| Infobulle, petit popover | 125 à 200 ms |
| Menu déroulant, liste de choix | 150 à 250 ms |
| Modale, tiroir | 200 à 500 ms |
| Présentation, marketing | plus long si besoin |

**Une animation d'interface reste sous 300 ms.** Un menu à 180 ms paraît
plus réactif qu'à 400 ms ; un indicateur de chargement qui tourne vite donne
l'impression d'un chargement plus court ; une fois une infobulle ouverte,
ses voisines s'ouvrent sans délai ni animation. La vitesse perçue compte
autant que la vitesse réelle.

## Les ressorts

Un ressort n'a pas de durée fixe : il se pose selon ses réglages physiques,
et garde sa vitesse quand on l'interrompt. On l'emploie pour :

- un glisser avec élan, un tiroir qu'on lance ;
- un élément qui doit sembler vivant ;
- un geste que la personne peut inverser en cours de route ;
- une interaction décorative qui suit la souris (et seulement décorative :
  une donnée qu'on lit ne bouge pas pour le style).

Deux façons de le régler :

```js
{ type: "spring", duration: 0.5, bounce: 0.2 }          // la plus simple à raisonner
{ type: "spring", mass: 1, stiffness: 100, damping: 10 } // plus de contrôle
```

Le rebond reste discret (0,1 à 0,3) et réservé aux gestes qui portent un
élan ou aux moments ludiques. Une animation CSS par images clés repart de
zéro quand on l'interrompt ; un ressort repart de là où il est.

## Les composants qui donnent une impression de qualité

- **Tout ce qui se presse répond à l'appui** : `transform: scale(0.97)` sur
  `:active`, avec `transition: transform 160ms ease-out`. L'échelle reste
  entre 0,95 et 0,98 ; elle entraîne le texte et l'icône, et c'est ce qui
  la rend physique.
- **Jamais depuis `scale(0)`** : on part de `scale(0.9)` à `scale(0.97)`,
  avec l'opacité à 0.
- **Un menu, un popover, une infobulle naissent de leur déclencheur** :
  `transform-origin` sur le bouton (`var(--transform-origin)` avec les
  primitives qui le fournissent). Les modales sont l'exception : elles ne
  dépendent d'aucun bouton et restent centrées.
- **Les infobulles attendent avant la première**, puis s'enchaînent sans
  délai ni animation tant qu'on reste dans la barre.
- **Une interface déclenchée en rafale utilise des transitions**, pas des
  images clés : une transition se réoriente en cours de route, des images
  clés repartent de zéro (notifications empilées, interrupteurs).
- **Un fondu enchaîné qui montre deux états superposés** se masque avec un
  léger flou pendant la transition (`filter: blur(2px)`, jamais plus de
  20 px : le flou coûte cher, surtout sur Safari).
- **Une entrée sans JavaScript** s'écrit avec `@starting-style` ; à défaut,
  un attribut posé après le premier rendu.

## Transformations et découpes

- `translateY(100%)` déplace un élément de sa propre hauteur, quelle
  qu'elle soit : c'est ainsi qu'on cache un tiroir ou une notification hors
  de l'écran, sans valeur en pixels.
- `scale()` agrandit aussi le contenu (texte, icônes) : c'est voulu pour un
  appui.
- `rotateX`, `rotateY` et `transform-style: preserve-3d` donnent de la
  profondeur sans JavaScript.
- `clip-path: inset(haut droite bas gauche)` est un outil d'animation
  puissant : une révélation au défilement (`inset(0 0 100% 0)` vers
  `inset(0 0 0 0)`), un bouton « maintenir pour supprimer » (un calque qui
  se remplit en 2 s `linear` à l'appui et se vide en 200 ms `ease-out` au
  relâchement), des onglets dont la couleur change d'un bloc (on duplique
  la liste, on découpe la copie active), un comparateur avant / après.

## Les gestes

- **Fermer d'un geste vif** : on mesure la vitesse (distance ÷ temps écoulé)
  et on ferme au-delà d'environ 0,11 px/ms, même si la distance est courte.
- **Au-delà d'une limite, on résiste** : l'élément suit de moins en moins le
  doigt, il ne bute pas contre un mur invisible.
- **On capture le pointeur** dès que le glisser commence, pour le suivre
  même hors de l'élément.
- **On ignore un second doigt** une fois le glisser lancé, sinon l'élément
  saute.

## La performance

- On anime `transform` et `opacity` ; animer `width`, `height`, `margin`,
  `padding`, `top` ou `left` recalcule la mise en page à chaque image.
- Changer une variable CSS sur un parent recalcule les styles de tous ses
  enfants : on écrit `transform` directement sur l'élément qui bouge.
- Avec Motion (Framer Motion), les raccourcis `x`, `y`, `scale` tournent sur
  le fil principal ; la chaîne complète (`transform: "translateX(100px)"`)
  reste fluide quand la page est occupée.
- Une animation CSS ou WAAPI continue pendant qu'une page charge ; une
  animation pilotée en JavaScript image par image saccade. CSS pour ce qui
  est prévu d'avance, JavaScript pour ce qui suit un geste.

## L'accessibilité

```css
@media (prefers-reduced-motion: reduce) {
  .panneau { transition: opacity 0.2s ease; transform: none; }
}
@media (hover: hover) and (pointer: fine) {
  .carte:hover { transform: translateY(-2px); }
}
```

Le mouvement réduit garde les fondus et les changements de couleur qui
aident à comprendre, et retire les déplacements. Un survol animé se réserve
aux pointeurs précis : sur un écran tactile, un appui déclenche un faux
survol qui reste collé.

## Ce qui fait un composant qu'on aime

- **De bons réglages par défaut** valent mieux que des options : la courbe,
  la durée et l'aspect livrés doivent être excellents tels quels.
- **Les cas limites se traitent sans bruit** : suspendre le minuteur d'une
  notification quand l'onglet est caché, combler l'espace entre deux
  éléments empilés pour garder le survol, capturer le pointeur pendant un
  glisser. Personne ne les voit, c'est le but.
- **La cohérence** : le mouvement épouse la personnalité du produit. Un
  outil professionnel reste net et rapide ; une application grand public
  peut rebondir davantage.
- **L'asymétrie** : lent là où la personne décide (maintenir 2 s pour
  supprimer), rapide là où le système répond (200 ms au relâchement).
- **La cascade** : plusieurs éléments qui entrent ensemble arrivent avec 30
  à 80 ms d'écart chacun ; c'est décoratif, cela ne bloque jamais la saisie.

## Vérifier une animation

- Au ralenti (durée multipliée par 2 à 5, ou l'inspecteur d'animations du
  navigateur) : les couleurs se mêlent-elles sans double image ? la courbe
  s'arrête-t-elle net ? l'origine est-elle juste ? les propriétés restent-
  elles synchrones ?
- Image par image, pour les décalages entre propriétés.
- Sur un vrai téléphone, pour tout geste.
- Le lendemain, avec un œil neuf.

Ce que seul l'écran révèle se signale « à vérifier à l'écran », avec la
vérification à faire.

## La liste de contrôle d'une revue

| Ce qu'on trouve | Ce qu'on propose |
| --- | --- |
| `transition: all` | les propriétés exactes, par exemple `transform 200ms var(--ease-out)` |
| une entrée depuis `scale(0)` | `scale(0.95)` avec `opacity: 0` |
| `ease-in` sur un élément d'interface | `ease-out`, ou une courbe forte |
| un popover qui grandit depuis son centre | l'origine sur son déclencheur (sauf modale) |
| une animation sur une action au clavier | aucune animation |
| plus de 300 ms sur un élément d'interface | 150 à 250 ms |
| un survol animé sans condition | `@media (hover: hover) and (pointer: fine)` |
| des images clés sur un élément déclenché en rafale | une transition CSS |
| les raccourcis `x` / `y` de Motion sur une page chargée | la chaîne `transform` complète |
| une entrée et une sortie de même durée sur un appui | lent pour décider, rapide pour répondre |
| tous les éléments qui apparaissent d'un coup | une cascade de 30 à 80 ms |
