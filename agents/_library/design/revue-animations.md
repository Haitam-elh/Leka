---
titre: Revoir des animations
description: Juger le mouvement d'un écran ou d'une pull request avec une barre haute — les dix exigences, ce qui se signale d'emblée, l'ordre des remèdes, le tableau avant / après / pourquoi et la décision Bloquer ou Approuver.
---

# Revoir des animations

Une revue du mouvement ne demande pas « est-ce que ça bouge ? » mais « est-ce
que ça se ressent juste ? ». Une transition qui fonctionne mais paraît
molle, part du mauvais endroit, se déclenche trop souvent ou saccade est
une régression. **Par défaut, on signale ; l'approbation se mérite.** Les
valeurs exactes à citer sont dans `principes.md` : on les recopie, on ne les
arrondit pas.

## Les dix exigences

Chaque animation du périmètre se mesure à ces dix points ; un manquement
est un constat.

1. **Une raison d'exister** — continuité spatiale, indication d'état,
   retour, explication, ou éviter une rupture. « Ça fait joli » sur un
   élément vu souvent : on bloque.
2. **Une fréquence respectée** — rien sur une action clavier ou vue des
   centaines de fois par jour ; peu sur ce qui revient des dizaines de fois.
3. **Une courbe réactive** — `ease-out` (ou une courbe forte) pour entrer et
   sortir ; jamais `ease-in` ; pas de courbe intégrée molle sur un mouvement
   voulu.
4. **Moins de 300 ms** pour un élément d'interface, sauf raison dite.
5. **Une origine et une physique justes** — un menu naît de son bouton ;
   rien ne part de `scale(0)` ; les modales restent centrées.
6. **Interruptible** — ce qui se déclenche en rafale ou suit un geste se
   réoriente (transition, ressort), sans repartir de zéro.
7. **Sur le compositeur** — on anime `transform` et `opacity` ; animer la
   mise en page, ou les raccourcis de Motion sur une page occupée, est un
   constat de performance.
8. **Accessible** — le mouvement réduit respecté (plus doux, pas nul) ; le
   survol animé réservé aux pointeurs précis.
9. **Asymétrique quand il le faut** — lent quand la personne décide (appui
   long, confirmation destructive), rapide quand le système répond.
10. **Cohérent** — le mouvement épouse la personnalité du produit ; un fondu
    qui montre deux états superposés se masque d'un léger flou. Dans le
    doute, supprimer l'animation est souvent le meilleur choix.

## Ce qui se signale d'emblée

- `transition: all`
- une entrée depuis `scale(0)`, ou un simple fondu sans transformation de
  départ
- `ease-in` sur une interaction ; une courbe intégrée sur un mouvement voulu
- une animation sur un raccourci clavier ou une palette de commandes
- plus de 300 ms sur un élément d'interface, sans raison
- `transform-origin: center` sur un menu ou une infobulle rattachés à un
  bouton
- des images clés sur des notifications, des interrupteurs, tout ce qui se
  déclenche en rafale
- l'animation de `width`, `height`, `margin`, `padding`, `top`, `left`
- les raccourcis `x` / `y` / `scale` de Motion sur une page qui charge
- une variable CSS posée sur un parent pour déplacer un enfant
- aucun traitement de `prefers-reduced-motion`
- un `:hover` animé sans condition
- la même durée à l'appui et au relâchement d'un geste qui demande une
  décision
- un groupe qui apparaît d'un bloc là où une cascade de 30 à 80 ms
  conviendrait

## L'ordre des remèdes

Proposer d'abord ce qui est en haut de la liste :

1. **Supprimer l'animation** (fréquente, sans but, déclenchée au clavier).
2. **La réduire** : plus courte, une transformation plus petite, moins de
   propriétés.
3. **Corriger la courbe** : `ease-in` vers `ease-out`, une courbe forte.
4. **Corriger l'origine et la physique** : l'origine sur le déclencheur,
   `scale(0.95)` avec l'opacité au lieu de `scale(0)`.
5. **La rendre interruptible** : des images clés vers une transition, ou un
   ressort pour un geste.
6. **La passer sur le compositeur** : la mise en page vers `transform` /
   `opacity`, les raccourcis vers la chaîne `transform`, WAAPI pour
   programmer sans bibliothèque.
7. **Rendre le temps asymétrique.**
8. **Finir** : flou sur un fondu, cascade, `@starting-style`, ressort pour un
   élément vivant.
9. **Accessibilité et cohérence** : mouvement réduit, survol conditionnel,
   accord avec la personnalité du composant.

## Ce que la revue rend

**1. Le tableau des constats** — un seul tableau, une ligne par problème,
`fichier:ligne` cité :

| Où | Avant | Après | Pourquoi |
| --- | --- | --- | --- |
| `menu.css:14` | `transition: all 300ms ease-in` | `transition: transform 200ms var(--ease-out), opacity 200ms var(--ease-out)` | `all` et `ease-in` : lent au départ, et des propriétés coûteuses animées |

**2. Le verdict** — les remarques restantes par niveau d'effet, du plus fort
au plus faible, en omettant les niveaux vides :

1. Ce qui fait sonner faux (courbe molle, apparition de nulle part,
   animation sur une action fréquente).
2. Ce qu'il fallait simplement retirer ou réduire.
3. La performance (propriétés hors compositeur, risque de saccade).
4. L'interruption et le rythme.
5. L'origine, la physique, la cohérence.
6. L'accessibilité.

Puis la décision, explicite :

- **Bloquer** : un mouvement qui sonne faux, une animation sur une action
  clavier ou très fréquente, `scale(0)` ou `ease-in` sur l'interface, ou une
  animation hors compositeur facile à corriger.
- **Approuver** : rien de tout cela, des durées et des courbes dans les
  bornes, l'interruption traitée là où il faut, le mouvement réduit
  respecté.

Quand le ressenti ne peut pas se juger dans le code (un fondu, le rebond
d'un ressort), on le dit et on donne la vérification : au ralenti, image par
image, et sur un vrai appareil pour un geste.
