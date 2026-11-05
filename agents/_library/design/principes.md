---
titre: "Les principes du designer de LEKA"
description: "Le socle de toute revue du designer de LEKA : ce qu'on attend d'un écran, la forme d'un constat, les réglages de mouvement de LEKA (durées, courbes, ressorts), le bon comportement de chaque composant (bouton, menu, info-bulle, modale, tiroir, notification, liste, onglets, action destructive), les gestes, le coût, l'accessibilité et la vérification."
---

# Les principes du designer de LEKA

Ce guide sert à toutes les revues. Il dit ce que LEKA attend d'un écran, la
forme d'un constat, puis, composant par composant, ce qu'on vérifie et ce
qu'on propose. Les valeurs qu'il donne se reprennent telles quelles.

## 1. Ce qu'on attend d'un écran

On lit un écran comme la personne qui l'ouvre :

1. **Ce qu'elle vient faire.** Une action principale, visible la première.
   Deux boutons de même poids pour des choses d'importance différente : un
   constat.
2. **Dans quel ordre elle lit.** Tailles, graisses et couleurs suivent
   l'échelle du système et dessinent cet ordre.
3. **Ce qui se passe quand ça ne va pas.** Chargement, vide, erreur,
   désactivé, succès, focus : chaque état existe et dit quelque chose.
4. **Si l'écran parle la même langue que les autres.** Jetons et composants
   du dépôt ; une valeur écrite en dur là où un jeton existe se signale,
   regroupée par fichier.
5. **Si ce qui bouge aide.** Les parties 3 à 5 de ce guide.
6. **Si l'écran tient dans la vraie vie.** Données longues ou absentes,
   téléphone, clavier seul.

Un constat repose toujours sur une règle : celles de ce guide, le système du
dépôt ou le reste de son code. Une préférence de goût, face à un choix
cohérent du dépôt, se tait. Un détail juste ne se voit pas ; vingt détails
faux font une interface qui accroche sans qu'on sache dire pourquoi : c'est
ce que la revue cherche.

## 2. La forme d'un constat

Une ligne de tableau par problème, avec son emplacement `fichier:ligne`, sa
sévérité, l'extrait actuel, le remplacement exact et une phrase de pourquoi :
la règle et ce que la personne ressent.

| Où | Avant | Après | Pourquoi |
| --- | --- | --- | --- |
| `ProjectMenu.tsx:31` | `className="transition-all duration-500"` | `className="transition-[opacity,transform] duration-200 ease-[var(--ease-enter)]"` | le menu traîne et anime des propriétés que personne n'a choisies |
| `Toast.tsx:18` | `from { transform: scale(0) }` | `from { transform: translateY(8px); opacity: 0 }` | une notification arrive, elle ne surgit pas d'un point |
| `SaveButton.tsx:12` | aucun état pressé | `active:scale-[0.97] transition-transform duration-150` | sans réponse au doigt, on doute que l'appui soit pris |
| `Popover.tsx:40` | `transition-timing-function: ease-in` | `var(--ease-enter)` | `ease-in` retarde le premier mouvement, celui que l'œil attend |

Pas de liste « Avant : … / Après : … » : toujours le tableau.

## 3. Les réglages de mouvement de LEKA

### Les durées

| Ce qui bouge | Durée |
| --- | --- |
| une réponse à l'appui | 100 à 160 ms |
| une info-bulle, un petit popover | 120 à 200 ms |
| un menu, une liste de choix | 150 à 250 ms |
| une modale, un tiroir, une feuille | 200 à 450 ms |
| une présentation, une page marketing | ce que le propos demande |

Un élément d'interface reste sous 300 ms. La vitesse ressentie compte autant
que la vraie : un menu à 180 ms paraît plus vif qu'à 400 ms ; un indicateur
de chargement qui tourne vite fait paraître l'attente plus courte.

### Les courbes

```css
--ease-enter: cubic-bezier(0.16, 1, 0.3, 1);   /* ce qui entre, sort ou répond */
--ease-move: cubic-bezier(0.65, 0, 0.35, 1);   /* ce qui se déplace à l'écran */
--ease-sheet: cubic-bezier(0.32, 0.72, 0, 1);  /* tiroirs et feuilles */
```

- Ce qui entre, sort ou répond **décélère** : rapide au départ, posé à
  l'arrivée. À durée égale, il paraît plus rapide.
- Ce qui est déjà à l'écran et change de place **accélère puis freine**.
- Un survol ou une couleur : une transition douce et courte.
- `linear` pour ce qui tourne en continu ou suit le temps réel.
- **`ease-in` jamais** sur un élément d'interface : il part lentement à
  l'instant où l'œil guette le premier mouvement.
- Les courbes par défaut du CSS sont trop molles pour un mouvement voulu ;
  toute autre courbe se prend parmi des courbes connues, jamais au jugé.

### Les ressorts

Un ressort se pose selon ses réglages, sans durée fixe, et garde sa vitesse
si on l'interrompt. On le prend quand un geste porte un élan (tiroir lancé),
quand la personne peut inverser le mouvement en cours, quand un élément doit
paraître vivant, ou pour un effet décoratif qui suit la souris (jamais pour
une donnée qu'on lit).

```js
{ type: "spring", duration: 0.45, bounce: 0.15 }         // simple à raisonner
{ type: "spring", stiffness: 260, damping: 26, mass: 1 }  // plus fin
```

Rebond entre 0,1 et 0,3, réservé aux gestes avec élan et aux moments ludiques.

## 4. Composant par composant

Avant d'animer quoi que ce soit, on se demande combien de fois la personne
le verra et à quoi sert le mouvement :

| Usage | Ce qu'on fait |
| --- | --- |
| des centaines de fois par jour (raccourci, palette de commandes, navigation) | rien ne bouge |
| des dizaines de fois (survol, parcours de liste, interrupteur) | rien, ou un retour à peine perceptible |
| de temps en temps (modale, tiroir, notification) | une animation standard |
| rarement (premier usage, réussite) | on peut prendre plus de place |

Le mouvement doit orienter (d'où vient l'élément), dire un changement d'état,
expliquer une fonction, confirmer une action ou éviter qu'un contenu saute.
Pour un élément vu souvent, « c'est joli » ne suffit pas. Une action lancée
au clavier ne s'anime jamais.

**Un bouton, tout ce qui se presse.** Il répond à l'appui : `scale(0.97)` sur
`:active`, transition de `transform` en 150 ms, entre 0,95 et 0,98. Le texte
et l'icône rétrécissent avec lui, c'est ce qui le rend physique. Sa largeur
ne change pas quand son libellé passe à « Enregistrement… ».

**Un menu, un popover, une liste de choix.** Il sort de son déclencheur :
`transform-origin` du côté du bouton (les bibliothèques de primitives
fournissent souvent la variable), départ à `scale(0.95)` et `opacity: 0`,
150 à 220 ms en courbe d'entrée. Jamais depuis `scale(0)`.

**Une info-bulle.** La première attend un court instant avant d'apparaître ;
tant que le pointeur reste dans la même barre, les suivantes s'ouvrent sans
délai ni animation.

**Une modale.** Elle ne dépend d'aucun bouton : centrée, fondu et léger
agrandissement (0,96 vers 1), 200 à 300 ms ; le fond s'assombrit en fondu.

**Un tiroir, une feuille.** Caché par `translateY(100%)` ou `translateX(100%)`,
c'est-à-dire de sa propre taille sans valeur en pixels, courbe de feuille,
300 à 450 ms ; il se ferme d'un geste (partie 5).

**Une notification.** Elle entre et ressort par le même bord, ce qui rend
évident le geste de la balayer. Elles s'empilent en transitions, pas en images
clés : une transition se réoriente en cours de route quand une nouvelle
arrive, des images clés repartiraient de zéro. Son minuteur se suspend quand
l'onglet est caché ou quand on la survole.

**Une liste qui arrive.** Les éléments se suivent de 30 à 80 ms chacun ;
c'est décoratif et ne bloque jamais la saisie. Une liste qu'on filtre au fil
de la frappe ne s'anime pas.

**Des onglets.** L'indicateur glisse de l'ancien au nouvel onglet avec la
courbe de déplacement. Pour une couleur de fond qui change d'un bloc, on
superpose une copie de la liste dans la couleur active et on la découpe sur
l'onglet choisi avec `clip-path: inset()`.

**Un contenu qui se dévoile.** `clip-path: inset(0 0 100% 0)` vers `inset(0)` ;
au défilement, seulement sur une page de présentation, et une seule fois.

**Une action destructive.** Lente pour décider, rapide pour répondre : un
calque se remplit en 2 s `linear` tant qu'on maintient l'appui, et se vide en
200 ms au relâchement.

**Deux états superposés pendant un fondu.** Un léger flou pendant le passage
(`filter: blur(2px)`) cache la double image ; jamais au-delà de 20 px, le
flou coûte cher, surtout dans Safari.

**Une entrée sans JavaScript.** `@starting-style` ; à défaut, un attribut posé
juste après le premier rendu.

**De la profondeur sans JavaScript.** `rotateX`, `rotateY` et
`transform-style: preserve-3d`. Un comparateur avant / après se fait avec
`clip-path`.

## 5. Les gestes

- **Fermer d'un geste vif** : on mesure la vitesse (distance ÷ temps) et on
  ferme au-delà d'environ 0,11 px/ms, même sur une courte distance.
- **Résister aux bords** : au-delà d'une limite, l'élément suit de moins en
  moins le doigt au lieu de s'arrêter net.
- **Capturer le pointeur** dès le début d'un glisser, pour le suivre même
  hors de l'élément.
- **Ignorer un second doigt** une fois le glisser lancé, sinon l'élément
  saute.
- **Interrompre** : un élément rattrapé en pleine course repart de sa
  position et de sa vitesse, ce que fait un ressort.

## 6. Ce que ça coûte

- On anime `transform` et `opacity` ; `width`, `height`, `margin`, `padding`,
  `top`, `left` refont la mise en page à chaque image.
- Une variable CSS changée sur un parent recalcule le style de tous ses
  enfants : on écrit le `transform` sur l'élément qui bouge.
- Avec Motion, les raccourcis `x`, `y`, `scale` passent par le fil principal ;
  une valeur `transform` complète reste fluide quand la page travaille.
- Une animation CSS ou Web Animations API continue pendant un chargement ; une
  animation pilotée image par image en JavaScript saccade. CSS pour ce qui est
  prévu d'avance, JavaScript pour ce qui suit un geste.

Le détail : `performance-animation.md`.

## 7. Pour tout le monde

```css
@media (prefers-reduced-motion: reduce) {
  .panneau { transition: opacity 200ms ease; transform: none; }
}
@media (hover: hover) and (pointer: fine) {
  .carte:hover { transform: translateY(-2px); }
}
```

- Le mouvement réduit retire les déplacements et garde les fondus et les
  changements de couleur qui aident à comprendre.
- Un survol animé se réserve aux pointeurs précis : sur un écran tactile, un
  appui laisse un faux survol collé.
- Tout se fait au clavier, avec un focus visible ; texte à 4,5:1 de contraste ;
  cible tactile d'au moins 44 px.

## 8. Ce qui fait la différence

- **Des réglages par défaut excellents** plutôt que des options.
- **Les cas limites traités en silence** : minuteur suspendu, espace comblé
  entre deux éléments empilés pour ne pas perdre le survol, pointeur capturé.
- **Un caractère constant** : un outil professionnel reste net et rapide, une
  application grand public peut rebondir davantage.

## 9. Vérifier

- Au ralenti (durées multipliées par 2 à 5, ou l'inspecteur d'animations du
  navigateur) : pas de double image, une arrivée nette, la bonne origine, des
  propriétés synchrones.
- Image par image pour les décalages entre propriétés.
- Sur un vrai téléphone pour tout geste.
- Le lendemain, avec un regard neuf.

Ce que seul l'écran révèle se dit « à vérifier à l'écran », avec la
vérification à faire.

## 10. Le tableau de contrôle

| On trouve | On propose |
| --- | --- |
| `transition: all` | les propriétés exactes, ex. `transform 200ms var(--ease-enter)` |
| une entrée depuis `scale(0)` | `scale(0.95)` avec `opacity: 0` |
| `ease-in` sur un élément d'interface | la courbe d'entrée |
| un popover qui grandit depuis son centre | l'origine sur son déclencheur (sauf modale) |
| une animation sur une action au clavier | aucune |
| plus de 300 ms sur un élément d'interface | 150 à 250 ms |
| un survol animé sans condition | `@media (hover: hover) and (pointer: fine)` |
| des images clés sur un élément déclenché en rafale | une transition |
| les raccourcis `x` / `y` de Motion sur une page chargée | une valeur `transform` complète |
| entrée et sortie de même durée sur un appui maintenu | lent pour décider, rapide pour répondre |
| tout un groupe qui apparaît d'un bloc | une cascade de 30 à 80 ms |
