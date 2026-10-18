---
titre: Des interfaces fluides
description: Ce qui rend une interface vivante sous le doigt — répondre sans délai, suivre le geste un pour un, pouvoir tout interrompre, des ressorts réglés par amortissement et réponse, transmettre la vitesse, projeter l'élan, revenir par le même chemin, résister aux limites, les matières translucides, le retour sonore et haptique, le mouvement réduit, la typographie (approche, interligne) et les principes de conception qui portent le tout.
---

# Des interfaces fluides

Une interface paraît vivante quand **le mouvement part de la position
affichée, hérite de la vitesse du doigt, prolonge son élan, et peut être
saisi et renversé à tout instant**. Les ressorts sont l'outil naturel de ces
quatre exigences : ils partent d'où ils sont et tiennent compte de la
vitesse. Ce guide traduit pour le web (CSS, Pointer Events,
`requestAnimationFrame`, bibliothèques de ressorts comme Motion) les leçons
des interfaces tactiles les plus abouties.

Une interface fluide sert quatre besoins : se sentir en sécurité (rien ne
surprend), comprendre, accomplir, et y prendre plaisir.

## 1. Répondre sans délai

- Le retour arrive **à l'appui**, pas au relâchement : un bouton se marque
  dès que le doigt le touche.
- Chaque délai sur le chemin de la saisie se chasse : anti-rebonds, minuteurs
  artificiels, attentes de transition, délai de 300 ms au toucher.
- Pendant un glisser, un curseur, un tiroir, le retour est **continu** :
  l'interface suit le doigt tout du long, elle n'anime pas seulement à la fin.

```css
.bouton:active { transform: scale(0.97); transition: transform 100ms ease-out; }
```

## 2. Suivre le doigt un pour un

L'élément saisi reste collé au doigt et respecte l'endroit où on l'a pris :
le recentrer sous le doigt casse l'illusion. Pointer Events avec
`setPointerCapture`, et un court historique des positions et des instants
pour connaître la vitesse au relâchement.

```js
el.addEventListener("pointerdown", (e) => {
  el.setPointerCapture(e.pointerId);
  const prise = e.clientY - el.getBoundingClientRect().top; // l'endroit saisi
  // garder les dernières positions et leurs instants pour la vitesse
});
```

## 3. Pouvoir tout interrompre — le principe central

On peut saisir un élément en plein mouvement et le renverser sans attendre la
fin. Une modale qu'on rattrape pendant sa fermeture suit le doigt ; elle ne
termine pas de se fermer pour se rouvrir.

- On ne bloque jamais la saisie pendant une transition.
- Une nouvelle animation part de la **valeur affichée**, jamais de la valeur
  cible : on lit la transformation réelle à l'écran.
- Pas de transitions ni d'images clés pour ce qui suit un geste : on ne peut
  pas les saisir proprement. Les ressorts repartent de la valeur courante.
- Quand le geste s'inverse, on **conserve la vitesse** au lieu de couper net
  (sinon, un « mur » de vitesse se voit).
- Un mouvement en deux dimensions se décompose en deux ressorts, X et Y.

## 4. Un comportement plutôt qu'une animation

Une animation de durée fixe ne réagit pas à une nouvelle saisie ; un ressort
change simplement de cible. On les règle par deux paramètres faciles à
raisonner :

- **l'amortissement** (le dépassement) : 1,0 se pose sans rebond ; en
  dessous, ça dépasse et oscille ;
- **la réponse** : le temps pour rejoindre la cible, en secondes. Ce n'est pas
  une durée : la durée du ressort découle de ses réglages.

Par défaut : **amortissement 1,0** (net, discret). Un léger rebond
(**amortissement ≈ 0,8**) seulement quand le geste portait un élan (un
lancer, un relâchement de glisser). Un menu qui vient d'apparaître ne rebondit
pas ; une carte qu'on a lancée, si.

| Interaction | Amortissement | Réponse |
| --- | --- | --- |
| déplacer, replacer | 1,0 | 0,4 |
| rotation | 0,8 | 0,4 |
| tiroir, feuille | 0,8 | 0,3 |

Avec Motion, le couple `bounce` / `duration` correspond à peu près :

```js
import { animate } from "motion";
animate(el, { y: 0 }, { type: "spring", bounce: 0, duration: 0.4 });       // sans dépassement
animate(el, { y: cible }, { type: "spring", bounce: 0.2, duration: 0.4 }); // après un lancer
```

## 5. Transmettre la vitesse

Au relâchement, l'animation continue **exactement à la vitesse du doigt** :
pas de couture entre le glisser et l'animation. Certaines API veulent une
vitesse relative, normalisée par la distance restante :

```
vitesseRelative = vitesseDuGeste / (cible − valeurActuelle)
```

Motion prend directement la vitesse absolue (option `velocity`).

## 6. Projeter l'élan

On ne choisit pas la position d'arrivée depuis le point de relâchement : on
**projette** où le geste allait, comme une décélération de défilement, puis
on prend le point d'accroche le plus proche de cette projection.

```js
// décélération ≈ 0,998 pour un défilement normal, 0,99 plus sec
function projeter(vitesse /* px/s */, deceleration = 0.998) {
  return ((vitesse / 1000) * deceleration) / (1 - deceleration);
}
const arrivee = positionActuelle + projeter(vitesseAuRelachement);
const cible = pointLePlusProche(arrivee);
animerAvecRessort(cible, { velocity: vitesseAuRelachement });
```

## 7. La cohérence spatiale

- **Revenir par le même chemin** : un panneau entré par la droite sort par la
  droite.
- **Partir de sa source** : un menu, un popover, une feuille naissent de
  l'élément qui les déclenche (`transform-origin` sur le déclencheur).
- **Inverser la courbe au retour** pour une transition réversible.
- **Annoncer la destination** : les images intermédiaires pointent vers
  l'état final, elles n'interpolent pas à l'aveugle.

## 8. Résister aux limites

Au-delà d'un bord, l'élément résiste de plus en plus au lieu de s'arrêter net
(un arrêt sec semble figé ; une résistance dit « il n'y a rien de plus ») :

```js
function resister(depassement, dimension, constante = 0.55) {
  return (depassement * dimension * constante) / (dimension + constante * Math.abs(depassement));
}
```

## 9. Le détail des gestes

- **Toucher** : marquer à l'appui, valider au relâchement ; une marge
  d'environ 10 px autour de la cible ; on peut annuler en glissant hors de la
  cible.
- **Glisser** : un petit seuil (≈ 10 px) avant de choisir un axe, puis un
  suivi un pour un.
- On détecte en parallèle tous les gestes plausibles dès le premier
  mouvement, puis on écarte les perdants quand l'intention est claire.
- Le double toucher retarde le simple : on ne le paie que là où il existe.

## 10. Des images fluides

La fluidité tient au contenu des images, pas seulement à leur nombre : un
déplacement par image sous le seuil de perception ; pour un mouvement très
rapide, un léger flou ou étirement qui dit la vitesse ; `transform` et
`opacity` seulement ; `will-change` quand le mouvement est imminent.

## 11. Les matières et la profondeur

- Barres d'outils, navigation et feuilles en **couches translucides**
  (`backdrop-filter: blur()` sur un fond semi-transparent), le contenu
  défilant dessous.
- **Le poids de la matière dit la hiérarchie** : plus sombre et dense pour
  séparer les zones, plus légère pour attirer vers une commande. Jamais une
  surface translucide claire sur une autre : la lisibilité s'effondre.
- Une grande surface paraît plus épaisse : flou plus fort, ombre plus
  profonde.
- **Assombrir pour concentrer** (une tâche modale, avec un voile) ; **décaler
  sans voile** pour un panneau parallèle qui ne bloque pas.
- Sur une surface translucide, un texte plus contrasté, un peu plus gras,
  légèrement espacé ; la couleur sur une couche opaque.
- Plutôt qu'un filet sous un en-tête collant, un léger dégradé ou flou là où
  le contenu passe dessous.
- Une surface en verre apparaît en animant ensemble le flou et l'échelle,
  pas par un simple fondu.

```css
.barre {
  background: rgba(255, 255, 255, 0.6);
  backdrop-filter: blur(20px) saturate(180%);
  border-top: 1px solid rgba(255, 255, 255, 0.4);
}
```

## 12. Le son et le toucher

- **La cause est évidente** : le retour part de l'événement qui le provoque
  (l'interrupteur bascule, l'élément se pose).
- **Tout arrive dans la même image** : le visuel, le son et la vibration ;
  un décalage détruit l'illusion.
- **Seulement là où ça compte** : réussite, erreur, validation, accroche. Trop
  de retours font qu'on n'en entend plus aucun.

## 13. Le mouvement réduit et l'accessibilité

Trois signaux, indépendants :

- `prefers-reduced-motion: reduce` — des fondus courts ou des changements
  sans mouvement à la place des glissements, ressorts et parallaxes ; pas de
  rebond ; les changements d'opacité et de couleur utiles restent.
- `prefers-reduced-transparency: reduce` — des surfaces plus opaques, sans
  flou.
- `prefers-contrast: more` — des fonds presque pleins et une bordure nette.

On évite aussi les fonds plein écran qui bougent, les oscillations lentes
(un cycle toutes les cinq secondes environ) et les sauts brusques de
luminosité (on adoucit le passage clair / sombre).

```css
@media (prefers-reduced-motion: reduce) {
  .feuille { transition: opacity 200ms ease; transform: none !important; }
}
@media (prefers-reduced-transparency: reduce) {
  .barre { background: white; backdrop-filter: none; }
}
```

## 14. La typographie

- **L'approche dépend de la taille** : un grand titre se resserre
  (approche négative, autour de `-0.02em`), un petit texte s'aère un peu ; le
  corps reste près de 0. Une seule valeur pour toutes les tailles est fausse
  quelque part.
- **L'interligne varie à l'inverse de la taille** : serré pour les grands
  titres, plus ample pour le corps ; plus ample pour les écritures à hautes
  ascendantes ; plus serré pour une interface dense.
- **La hiérarchie vient du trio graisse, taille, interligne**, pas de la
  taille seule ; la graisse met en avant sans prendre de place.
- **Le texte agrandi par la personne** fait grandir la mise en page avec lui
  (espacements en `rem` / `em`).
- **La police système d'abord** : elle sait déjà ajuster ses formes à la
  taille.

```css
:root { font: 100%/1.5 system-ui, sans-serif; }
.titre-affiche {
  font-size: clamp(2rem, 5vw, 4rem);
  line-height: 1.05;
  letter-spacing: -0.02em;
  font-optical-sizing: auto;
}
```

## 15. Les principes qui portent le tout

1. **L'intention** : faire avec raison, et décider ce qu'on ne fait pas.
2. **Le contrôle** : laisser des choix ; pardonner (annuler facilement) ;
   confirmer seulement l'irréversible, sinon la confirmation devient un
   réflexe.
3. **La responsabilité** : agir dans l'intérêt de la personne — demander au
   bon moment ce qui est nécessaire, anticiper les mauvais usages.
4. **Le familier** : s'appuyer sur ce que les gens connaissent ; ce qui se
   ressemble se comporte pareil et vit au même endroit ; ne casser une
   habitude que si c'est prouvé meilleur.
5. **La souplesse** : s'adapter à l'appareil, au contexte, aux capacités ;
   laisser personnaliser quand une seule mise en page ne convient pas à tous.
6. **La simplicité, pas le dépouillement** : retirer l'inutile pour que
   l'essentiel ressorte ; hiérarchie par l'ordre, l'espace, le contraste ; le
   chemin courant d'abord, l'avancé un niveau plus bas.
7. **Le soin** : chaque espacement, durée, alignement est un choix
   défendable ; un défilement qui tremble ou une icône mal alignée se lisent
   comme de la négligence.
8. **Le plaisir** : le résultat des sept autres, pas des confettis ajoutés.

Et quelques règles de terrain : quatre sortes de retour (état, achèvement,
avertissement, erreur), validées en ligne et non à l'envoi ; chaque écran
répond à « où suis-je, où puis-je aller, qu'y a-t-il, comment sortir » ; une
commande vit près de ce qu'elle modifie ; des libellés précis valent mieux
que des fourre-tout.

## En pratique

| Besoin | Technique | Valeur |
| --- | --- | --- |
| ressort d'interface par défaut | sans dépassement | amortissement 1,0, réponse 0,3–0,4 |
| ressort après un lancer | léger rebond | amortissement ≈ 0,8, réponse 0,3–0,4 |
| passer la vitesse du geste | vitesse initiale du ressort | `vitesse / (cible − actuelle)` si normalisée |
| point d'arrivée d'un lancer | projection de l'élan | `actuelle + (v/1000)·d/(1−d)`, d ≈ 0,998 |
| interrompre proprement | partir de la valeur affichée | lire la transformation à l'écran |
| inverser sans à-coup | garder la vitesse | un ressort qui se réoriente |
| décider revenir ou valider | le signe de la vitesse | au relâchement |
| glisser un pour un | Pointer Events + capture | respecter l'endroit saisi |
| une limite | résister | résistance croissante |
| une barre translucide | une couche `backdrop-filter` | le contenu passe dessous |
| l'approche d'un titre | selon la taille | `-0.02em` pour l'affiche, ~0 pour le corps |
| le mouvement réduit | un fondu | `@media (prefers-reduced-motion)` |
