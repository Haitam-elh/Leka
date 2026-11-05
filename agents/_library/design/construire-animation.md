---
titre: "Construire une animation"
description: "Écrire une animation juste du premier coup : les sept décisions dans l'ordre (animer ou non, pourquoi, quel outil, quelles propriétés, courbe ou ressort, interruption et sortie, mouvement réduit et pointeurs), puis le code prêt à poser pour chaque composant courant, ce qu'on ne livre jamais et ce qu'on rend."
---

# Construire une animation

Deux façons de rater une animation, la première bien pire que la seconde :
**faire bouger ce qui devait rester immobile**, et **faire bouger la bonne
chose avec de mauvais réglages** (`ease-in` à l'entrée, `scale(0)`, des images
clés sur des notifications, une durée qui alourdit un menu).

On décide, on donne la raison en une ligne, on écrit le code. On ne propose
jamais un éventail d'options. Les valeurs viennent de `principes.md`, jamais
approchées ; on étend les jetons du dépôt au lieu d'en créer de parallèles ;
le mouvement réduit et la condition de survol font partie de l'animation ;
l'outil le plus léger qui suffit gagne (pas de bibliothèque pour un fondu).

## Les sept décisions

1. **Animer ou non.** Selon la fréquence d'usage (`principes.md`). Pour une
   action au clavier ou vue des centaines de fois par jour : non, on le dit, et
   on propose l'équivalent immobile (un changement d'état immédiat, un repère
   fixe).
2. **Pourquoi.** Confirmer, orienter, dire un changement d'état, éviter une
   rupture, expliquer, ou plus rarement faire plaisir. Sans raison, on
   s'arrête. Une donnée qu'on lit ne bouge pas pour le style.
3. **Quel outil.** Le premier de cette liste qui convient :

   | Besoin | Outil |
   | --- | --- |
   | survol, appui, couleur, bascule par une classe ou un attribut | transition CSS |
   | entrée au montage, sans état JavaScript | `@starting-style` |
   | mouvement prévu d'avance, fluide même pendant un chargement | animation CSS |
   | contrôle en JavaScript avec la fluidité du CSS, sans dépendance | Web Animations API (`element.animate()`) |
   | ressorts, mise en page animée, sortie d'un composant démonté, valeurs liées à un geste | Motion |

   Si le besoin est un composant entier (notification, tiroir, palette, menu),
   on choisit d'abord la bonne bibliothèque (`bibliotheques.md`) au lieu de le
   refaire.
4. **Quelles propriétés.** `transform` et `opacity` ; `clip-path` ensuite ;
   `height` toléré pour un accordéon. Jamais depuis `scale(0)` ; l'origine sur
   le déclencheur (sauf une modale) ; les `translate` en pourcentage ; avec
   Motion, une valeur `transform` complète ; jamais une variable CSS posée sur
   un parent pour déplacer un enfant.
5. **Courbe et durée, ou ressort.** Les jetons et durées de `principes.md`. Un
   ressort pour un élan, un élément vivant, un geste réversible ou un suivi
   décoratif du pointeur.
6. **Interruption et sortie.** Des transitions plutôt que des images clés pour
   ce qui se déclenche en rafale ; des ressorts pour les gestes ; la sortie
   repart par où l'élément est entré ; lent quand la personne décide, rapide
   quand le système répond.
7. **Mouvement réduit et pointeurs.** Livrés avec l'animation :

   ```css
   @media (prefers-reduced-motion: reduce) {
     .element { transition: opacity 200ms ease; transform: none; }
   }
   @media (hover: hover) and (pointer: fine) {
     .element:hover { transform: translateY(-2px); }
   }
   ```

## Le code, composant par composant

Les courbes sont les jetons `--ease-enter`, `--ease-move` et `--ease-sheet` de
`principes.md`. Les états d'ouverture se lisent sur les attributs que posent
les primitives du dépôt (`data-state="open"`, `data-starting-style`,
`data-ending-style` selon la bibliothèque).

**Ce qui se presse**

```css
.pressable { transition: transform 150ms var(--ease-enter); }
.pressable:active { transform: scale(0.97); }
```

`:active` est un vrai appui : aucune condition de survol ici.

**Menu, popover, liste de choix**

```css
.flottant {
  transform-origin: var(--transform-origin);
  transition: opacity 180ms var(--ease-enter), transform 180ms var(--ease-enter);
}
.flottant[data-starting-style],
.flottant[data-ending-style] { opacity: 0; transform: scale(0.95); }
```

**Info-bulle**

```css
.bulle {
  transform-origin: var(--transform-origin);
  transition: opacity 130ms var(--ease-enter), transform 130ms var(--ease-enter);
}
.bulle[data-starting-style],
.bulle[data-ending-style] { opacity: 0; transform: scale(0.97); }
.bulle[data-instant] { transition-duration: 0ms; } /* les suivantes, sans attendre */
```

**Modale**, centrée puisqu'elle ne dépend d'aucun bouton

```css
.modale {
  transform-origin: center;
  transition: opacity 240ms var(--ease-enter), transform 240ms var(--ease-enter);
}
.modale[data-starting-style],
.modale[data-ending-style] { opacity: 0; transform: scale(0.96); }
.voile { transition: opacity 240ms var(--ease-enter); }
```

**Tiroir, feuille**

```css
.feuille { transform: translateY(0); transition: transform 450ms var(--ease-sheet); }
.feuille[data-closed] { transform: translateY(100%); }
```

**Notification**

```css
.notification {
  transition: opacity 350ms ease, transform 350ms ease;
  @starting-style { opacity: 0; transform: translateY(100%); }
}
```

Une notification peut être un peu plus douce et plus lente que le reste de
l'interface si c'est son caractère. Quand la pile se réorganise, l'opacité et
la hauteur se règlent à l'œil, puis se revérifient le lendemain.

**Accordéon**

```css
.depli { overflow: hidden; transition: height 200ms var(--ease-enter), opacity 200ms var(--ease-enter); }
```

Court, car c'est l'une des rares animations qui refait la mise en page. La
hauteur se mesure (ou vient d'une primitive) : on n'anime jamais vers `auto`.
Alternative sans mesure : une grille `grid-template-rows: 0fr` vers `1fr`.

**Un groupe qui arrive** (vu de temps en temps)

```css
.arrivee { opacity: 0; transform: translateY(8px); animation: arriver 280ms var(--ease-enter) forwards; }
.arrivee:nth-child(2) { animation-delay: 50ms; }
.arrivee:nth-child(3) { animation-delay: 100ms; }
@keyframes arriver { to { opacity: 1; transform: translateY(0); } }
```

**Maintenir pour confirmer** (action destructive)

```css
.remplissage { clip-path: inset(0 100% 0 0); transition: clip-path 200ms var(--ease-enter); }
.confirmer:active .remplissage { clip-path: inset(0); transition: clip-path 2s linear; }
.confirmer:active { transform: scale(0.97); }
```

`linear` est juste ici : le calque mesure une progression.

**Onglets dont la couleur change d'un bloc**

Une copie de la liste, stylée comme active, posée par-dessus ; on n'en laisse
voir que l'onglet choisi en animant sa découpe :

```css
.onglets-copie { clip-path: inset(0 60% 0 20%); transition: clip-path 240ms var(--ease-move); }
```

**Révélation au défilement** (page de présentation seulement, une seule fois)

```css
.devoile { clip-path: inset(0 0 100% 0); transition: clip-path 600ms var(--ease-move); }
.devoile[data-visible] { clip-path: inset(0); }
```

**Glisser pour fermer**

```js
const vitesse = Math.abs(ecart) / (performance.now() - debut);
if (Math.abs(ecart) >= SEUIL || vitesse > 0.11) fermer();
feuille.style.transform = `translateY(${ecart}px)`; // sur l'élément, jamais via une variable du parent
```

Capturer le pointeur au début, ignorer un second doigt, résister au-delà des
bords, se poser avec un ressort qui garde la vitesse (`interfaces-fluides.md`).

**Un fondu enchaîné sans double image**

```css
.vue { transition: filter 200ms ease, opacity 200ms ease; }
.vue.en-passage { filter: blur(2px); opacity: 0.7; }
```

**Sans bibliothèque, en JavaScript**

```js
bloc.animate(
  [{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0)" }],
  { duration: 900, fill: "forwards", easing: "cubic-bezier(0.65, 0, 0.35, 1)" },
);
```

## Ce qu'on ne livre jamais

| Jamais | À la place |
| --- | --- |
| `transition: all` | les propriétés exactes |
| une entrée depuis `scale(0)` | `scale(0.95)` avec `opacity: 0` |
| `ease-in` sur un élément d'interface | la courbe d'entrée |
| les courbes par défaut du CSS sur un mouvement voulu | les jetons de `principes.md` |
| une animation sur une action au clavier ou très fréquente | rien |
| plus de 300 ms sans raison | 150 à 250 ms |
| un popover qui grandit depuis son centre | l'origine sur son déclencheur |
| des images clés pour ce qui se déclenche en rafale | des transitions |
| animer la mise en page | `transform` et `opacity` |
| les raccourcis de Motion sur une page qui charge | une valeur `transform` complète |
| un survol animé sans condition | `@media (hover: hover) and (pointer: fine)` |
| aucun mouvement réduit | une version plus douce, jamais rien |
| un groupe qui arrive d'un bloc | une cascade de 30 à 80 ms |

## Ce qu'on rend

Le code, puis quelques lignes : la décision des étapes 1 et 2 (fréquence,
raison, et ce qui a été écarté), les réglages retenus (outil, propriétés,
courbe et durée ou ressort), et ce qu'il faudra vérifier au ressenti quand le
code ne suffit pas.
