---
titre: Construire une animation
description: Écrire une animation qui passerait une revue exigeante du premier coup — la séquence de décisions (animer ou non, raison, outil, propriétés, courbe ou ressort, interruption, mouvement réduit) et des recettes prêtes pour le bouton, le menu, l'infobulle, la modale, le tiroir, la notification, l'accordéon, la cascade, l'appui maintenu, les onglets, la révélation, le glisser pour fermer.
---

# Construire une animation

Construire une animation, c'est prendre des décisions dans un ordre qui
garantit qu'elle sonnera juste. Deux échecs possibles, le premier étant le
pire : **animer ce qui ne devait pas bouger**, et **animer la bonne chose avec
les mauvais ingrédients** (`ease-in` à l'entrée, `scale(0)`, des images clés
sur une notification, une durée qui alourdit un menu).

On tranche, on dit la raison en une ligne, on écrit le code — jamais un menu
d'options.

Règles : la séquence se suit dans l'ordre (les étapes 1 et 2 décident de
tout) ; aucune valeur approchée — toutes viennent de `principes.md` ; on
étend les jetons du dépôt au lieu d'en créer d'autres ; le mouvement réduit et
la condition de survol font partie de l'animation, pas d'une suite ; l'outil
le moins coûteux qui suffit (pas de bibliothèque pour un fondu).

## La séquence

1. **Animer ou non ?** Selon la fréquence (`principes.md`). Une action au
   clavier ou vue des centaines de fois par jour : on n'anime pas, on le dit,
   et on propose l'alternative sans mouvement (un changement d'état
   immédiat, un repère statique).
2. **Pour quoi ?** Retour, continuité spatiale, indication d'état, éviter une
   rupture, explication, ou plaisir (rare seulement). Sans raison, on
   s'arrête. Une donnée qu'on lit ne bouge pas pour le style.
3. **Quel outil ?** Le premier qui convient :

   | Besoin | Outil |
   | --- | --- |
   | survol, appui, couleur, bascule pilotée par une classe ou un attribut | une transition CSS |
   | une entrée au montage, sans état JavaScript | `@starting-style` |
   | un mouvement prévu d'avance qui doit rester fluide pendant un chargement | une animation CSS (hors du fil principal) |
   | du contrôle en JavaScript avec la performance du CSS, sans dépendance | WAAPI (`element.animate()`) |
   | ressorts, mise en page animée, sorties de composants démontés, valeurs pilotées par un geste | Motion |

   Si le besoin est un *composant* (notification, tiroir, palette, menu), on
   choisit d'abord la bonne bibliothèque (`bibliotheques.md`) au lieu d'en
   bricoler un.
4. **Quelles propriétés ?** `transform` et `opacity` ; `clip-path` en
   quatrième ; `height` toléré pour un accordéon. Jamais depuis `scale(0)` ;
   origine sur le déclencheur (sauf modale) ; `translate` en pourcentage ;
   avec Motion, la chaîne `transform` complète ; jamais une variable CSS sur
   un parent pour déplacer un enfant.
5. **Courbe et durée, ou ressort.** Les courbes et budgets de
   `principes.md`. Un ressort quand il y a un élan, un élément vivant, un
   geste qu'on peut inverser, ou un suivi décoratif du pointeur.
6. **Interruption et sortie.** Transitions plutôt qu'images clés pour ce
   qui se déclenche en rafale ; ressorts pour les gestes ; on sort par où l'on
   est entré ; lent quand la personne décide, rapide quand le système répond.
7. **Mouvement réduit et pointeurs.** Livrés avec l'animation :

   ```css
   @media (prefers-reduced-motion: reduce) {
     .element { transition: opacity 0.2s ease; transform: none; }
   }
   @media (hover: hover) and (pointer: fine) {
     .element:hover { transform: translateY(-2px); }
   }
   ```

## Les recettes

Les courbes sont les jetons `--ease-out`, `--ease-in-out` et `--ease-drawer`
de `principes.md`.

**Bouton (tout ce qui se presse)**

```css
.bouton { transition: transform 160ms var(--ease-out); }
.bouton:active { transform: scale(0.97); }
```

`:active` est un vrai appui au doigt : pas de condition de survol ici.

**Menu, popover, liste de choix**

```css
.popover {
  transform-origin: var(--transform-origin);
  transition: opacity 200ms var(--ease-out), transform 200ms var(--ease-out);
}
.popover[data-starting-style],
.popover[data-ending-style] { opacity: 0; transform: scale(0.95); }
```

**Infobulle**

```css
.infobulle {
  transform-origin: var(--transform-origin);
  transition: transform 125ms var(--ease-out), opacity 125ms var(--ease-out);
}
.infobulle[data-starting-style],
.infobulle[data-ending-style] { opacity: 0; transform: scale(0.97); }
.infobulle[data-instant] { transition-duration: 0ms; } /* les suivantes, sans attendre */
```

**Modale** (centrée : elle ne dépend d'aucun bouton)

```css
.modale {
  transform-origin: center;
  transition: opacity 250ms var(--ease-out), transform 250ms var(--ease-out);
}
.modale[data-starting-style],
.modale[data-ending-style] { opacity: 0; transform: scale(0.96); }
.voile { transition: opacity 250ms var(--ease-out); }
```

**Tiroir**

```css
.tiroir { transform: translateY(0); transition: transform 500ms var(--ease-drawer); }
.tiroir[data-closed] { transform: translateY(100%); }
```

**Notification**

```css
.notification {
  opacity: 1;
  transform: translateY(0);
  transition: opacity 400ms ease, transform 400ms ease;
  @starting-style { opacity: 0; transform: translateY(100%); }
}
```

Une notification peut être un peu plus lente et plus douce que le reste de
l'interface si c'est la personnalité du composant. Quand la pile se
réorganise, l'opacité et la hauteur se règlent à l'œil — et se revérifient
le lendemain.

**Accordéon**

```css
.contenu { overflow: hidden; transition: height 200ms var(--ease-out), opacity 200ms var(--ease-out); }
```

Court : c'est l'une des rares animations qui recalcule la mise en page. La
hauteur se mesure (ou vient d'une primitive), on n'anime pas vers `auto`.

**Cascade d'un groupe** (vu de temps en temps)

```css
.element { opacity: 0; transform: translateY(8px); animation: entrer 300ms var(--ease-out) forwards; }
.element:nth-child(2) { animation-delay: 50ms; }
.element:nth-child(3) { animation-delay: 100ms; }
@keyframes entrer { to { opacity: 1; transform: translateY(0); } }
```

**Appui maintenu pour confirmer** (action destructive)

```css
.calque { clip-path: inset(0 100% 0 0); transition: clip-path 200ms var(--ease-out); }
.bouton:active .calque { clip-path: inset(0 0 0 0); transition: clip-path 2s linear; }
.bouton:active { transform: scale(0.97); }
```

`linear` est juste ici : le calque est une progression.

**Onglets dont la couleur change d'un bloc**

On duplique la liste d'onglets, on stylise la copie comme active, et on ne
laisse voir que l'onglet actif en animant sa découpe :

```css
.onglets-actifs { clip-path: inset(0 60% 0 20%); transition: clip-path 250ms var(--ease-in-out); }
```

**Révélation au défilement** (pages marketing seulement, une seule fois)

```css
.revele { clip-path: inset(0 0 100% 0); transition: clip-path 600ms var(--ease-in-out); }
.revele[data-visible] { clip-path: inset(0 0 0 0); }
```

**Glisser pour fermer**

```js
const vitesse = Math.abs(distance) / (Date.now() - debut);
if (Math.abs(distance) >= SEUIL || vitesse > 0.11) fermer();
element.style.transform = `translateY(${distance}px)`; // sur l'élément, pas via une variable du parent
```

Capturer le pointeur au début ; ignorer un second doigt ; résister au-delà
des limites ; se poser avec un ressort qui garde la vitesse.

**Un fondu qui ne se pose pas**

```css
.contenu { transition: filter 200ms ease, opacity 200ms ease; }
.contenu.en-transition { filter: blur(2px); opacity: 0.7; }
```

**Programmer sans bibliothèque**

```js
element.animate(
  [{ clipPath: "inset(0 0 100% 0)" }, { clipPath: "inset(0 0 0 0)" }],
  { duration: 1000, fill: "forwards", easing: "cubic-bezier(0.77, 0, 0.175, 1)" },
);
```

## À ne jamais livrer

| Jamais | À la place |
| --- | --- |
| `transition: all` | les propriétés exactes |
| une entrée depuis `scale(0)` | `scale(0.95)` et `opacity: 0` |
| `ease-in` sur un élément d'interface | `ease-out` ou une courbe forte |
| l'`ease-out` intégré sur un mouvement voulu | `cubic-bezier(0.23, 1, 0.32, 1)` |
| une animation sur une action clavier ou très fréquente | rien |
| plus de 300 ms sans raison | 150 à 250 ms |
| une origine centrée sur un popover | l'origine sur le déclencheur |
| des images clés sur ce qui se déclenche en rafale | des transitions |
| animer la mise en page | `transform`, `opacity` |
| les raccourcis de Motion sur une page qui charge | la chaîne `transform` |
| un survol animé sans condition | `@media (hover: hover) and (pointer: fine)` |
| pas de mouvement réduit | une version plus douce, pas nulle |
| tout qui arrive d'un bloc | une cascade de 30 à 80 ms |

## Ce qu'on rend

Le code, puis en quelques lignes : le résultat des étapes 1 et 2 (fréquence
et raison, et ce qui a été écarté), les ingrédients (outil, propriétés,
courbe et durée ou ressort), et ce qu'il faudra vérifier au ressenti quand
le code ne suffit pas.
