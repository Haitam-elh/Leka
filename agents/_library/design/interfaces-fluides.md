---
titre: "Des interfaces fluides"
description: "Ce qui rend une interface vivante sous le doigt, scène par scène (toucher, saisir, glisser, lancer, atteindre un bord, rattraper) : réponse immédiate, suivi exact, interruption, ressorts réglés par amortissement et réponse, vitesse transmise, élan projeté, matières et profondeur, retours sensoriels, préférences d'accessibilité, typographie et règles de conduite."
---

# Des interfaces fluides

Une interface fluide donne l'impression de manipuler des objets. Quatre
promesses la font tenir : **le mouvement part de ce qui est affiché**, **il
garde la vitesse du doigt**, **il prolonge l'élan**, et **on peut le saisir et
l'inverser à tout instant**. Les ressorts les tiennent naturellement : ils
partent de leur position et de leur vitesse. Sur le web, on les obtient avec
Pointer Events, `requestAnimationFrame` et une bibliothèque de ressorts
(Motion par exemple).

Ce qu'on cherche à donner : se sentir en sécurité (rien ne surprend),
comprendre, réussir, et y prendre plaisir.

## Scène 1 : on touche

- Le retour arrive **au contact**, pas au relâchement.
- On chasse tout délai sur le chemin de la saisie : anti-rebond inutile,
  minuteur artificiel, attente d'une transition, délai de 300 ms au toucher
  (évité par `touch-action: manipulation` et une fenêtre correctement
  déclarée).
- Une cible garde une marge d'environ 10 px autour d'elle ; on valide au
  relâchement et on peut annuler en glissant hors de la cible.
- Un double toucher retarde le simple : on ne le paie que là où il existe.

```css
.bouton:active { transform: scale(0.97); transition: transform 100ms var(--ease-enter); }
```

## Scène 2 : on saisit et on glisse

- L'élément reste collé au doigt **à l'endroit où on l'a pris** ; le recentrer
  sous le doigt casse l'illusion.
- Un petit seuil (environ 10 px) avant de choisir l'axe du glisser ; ensuite,
  suivi exact, sans courbe ni retard.
- Le retour est continu pendant tout le geste, pas seulement à la fin.
- On écoute en parallèle tous les gestes plausibles dès le premier mouvement
  et on écarte les autres quand l'intention est claire.

```js
let origine = 0;
const historique = []; // [{ y, t }] des derniers instants, pour la vitesse

poignee.addEventListener("pointerdown", (e) => {
  poignee.setPointerCapture(e.pointerId);
  origine = e.clientY - panneau.getBoundingClientRect().top;
  historique.length = 0;
});
poignee.addEventListener("pointermove", (e) => {
  historique.push({ y: e.clientY, t: e.timeStamp });
  if (historique.length > 5) historique.shift();
  panneau.style.transform = `translateY(${e.clientY - origine}px)`;
});
```

## Scène 3 : on lâche

**La vitesse se transmet.** Au relâchement, l'animation repart exactement à la
vitesse du doigt, sans couture. Une API qui attend une vitesse relative la
reçoit normalisée par la distance restante :

```
vitesse relative = vitesse du geste / (cible - position actuelle)
```

Motion prend la vitesse absolue (`velocity`).

**L'élan se projette.** La position d'arrivée ne se décide pas au point de
relâchement : on projette où le geste allait, comme une décélération de
défilement, puis on prend le point d'accroche le plus proche.

```js
// d autour de 0,998 pour un défilement ordinaire, 0,99 pour un arrêt plus sec
const projection = (v /* px/s */, d = 0.998) => ((v / 1000) * d) / (1 - d);
const visee = positionActuelle + projection(vitesse);
const cible = accrochePlusProche(visee);
ressortVers(cible, { velocity: vitesse });
```

**Le sens décide.** Au relâchement, le signe de la vitesse dit si l'on valide
(on continue) ou si l'on revient.

## Scène 4 : on atteint un bord

Au-delà d'une limite, l'élément résiste de plus en plus au lieu de s'arrêter
net : un arrêt sec paraît figé, une résistance dit « il n'y a rien de plus ».

```js
const resister = (depasse, taille, k = 0.55) =>
  (depasse * taille * k) / (taille + k * Math.abs(depasse));
```

## Scène 5 : on rattrape

C'est le principe central : on peut saisir un élément en mouvement et le
renverser sans attendre. Une modale rattrapée pendant sa fermeture suit le
doigt ; elle ne finit pas de se fermer pour se rouvrir.

- La saisie n'est jamais bloquée pendant une transition.
- Une nouvelle animation part de la **valeur affichée** (on lit la
  transformation réelle), jamais de la valeur cible.
- Ce qui suit un geste n'utilise ni transition ni images clés, qu'on ne peut
  pas saisir proprement : un ressort repart de sa valeur courante.
- Quand le geste s'inverse, la vitesse se garde ; la couper net se voit.
- Un mouvement en deux dimensions se fait avec deux ressorts, un par axe.

## Régler un ressort

Un ressort ne joue pas une durée, il a un comportement : il change de cible
quand on le lui demande. Deux réglages suffisent pour raisonner :

- **l'amortissement** : à 1, il se pose sans dépasser ; en dessous, il dépasse
  et oscille ;
- **la réponse** : le temps qu'il met à rejoindre la cible, en secondes ; sa
  durée réelle découle de ses réglages.

Par défaut, amortissement 1 : net et discret. Un léger rebond (autour de 0,8)
seulement quand un geste portait un élan : une carte lancée rebondit, un menu
qui vient d'apparaître non.

| Situation | Amortissement | Réponse |
| --- | --- | --- |
| déplacer, replacer | 1 | 0,4 s |
| faire pivoter | 0,8 | 0,4 s |
| tiroir, feuille | 0,8 | 0,3 s |

Avec Motion, `bounce` et `duration` en sont l'équivalent :

```js
animate(carte, { y: 0 }, { type: "spring", bounce: 0, duration: 0.4 });        // retour posé
animate(carte, { y: cible }, { type: "spring", bounce: 0.2, duration: 0.4 });  // après un lancer
```

## Garder le sens de l'espace

- Ce qui entre par la droite ressort par la droite.
- Menus, popovers et feuilles naissent de ce qui les déclenche
  (`transform-origin` sur le déclencheur).
- Une transition réversible inverse sa courbe au retour.
- Les images intermédiaires vont vers l'état final ; elles n'interpolent pas
  à l'aveugle.

## Des images qui paraissent fluides

La fluidité tient au contenu des images autant qu'à leur nombre : un
déplacement par image sous le seuil de perception ; pour un mouvement très
rapide, un léger flou ou étirement qui dit la vitesse ; `transform` et
`opacity` seulement ; `will-change` posé juste avant un mouvement imminent.

## Les matières et la profondeur

- Barres, navigations et feuilles peuvent être des **couches translucides**
  (fond semi-transparent et `backdrop-filter: blur()`), le contenu défilant
  dessous.
- **La densité dit la hiérarchie** : plus sombre et opaque pour séparer des
  zones, plus légère pour attirer vers une commande. Jamais une surface claire
  translucide sur une autre : on ne lit plus rien.
- Plus une surface est grande, plus elle paraît épaisse : flou plus fort,
  ombre plus profonde.
- **Assombrir pour concentrer** (une tâche modale, sous un voile) ; **décaler
  sans voile** un panneau qui ne bloque pas.
- Sur une surface translucide, le texte est plus contrasté, un peu plus gras,
  légèrement espacé ; la couleur se pose sur une couche opaque.
- Sous un en-tête collant, plutôt qu'un filet, un léger dégradé ou flou là où
  le contenu passe dessous.
- Une surface en verre apparaît en animant ensemble son flou et son échelle,
  pas par un simple fondu.

```css
.barre-flottante {
  background: rgb(255 255 255 / 0.6);
  backdrop-filter: blur(20px) saturate(180%);
  border-top: 1px solid rgb(255 255 255 / 0.4);
}
```

## Le son et la vibration

- La cause doit être évidente : le retour part de l'événement qui le provoque.
- Image, son et vibration arrivent dans la même image ; un décalage détruit
  l'effet.
- Seulement là où ça compte (réussite, erreur, validation, accroche) : trop de
  retours et plus aucun ne s'entend.

## Les préférences de la personne

Trois signaux indépendants :

- `prefers-reduced-motion: reduce` : des fondus courts à la place des
  glissements, ressorts et parallaxes, sans rebond ; les changements
  d'opacité et de couleur utiles restent.
- `prefers-reduced-transparency: reduce` : des surfaces opaques, sans flou.
- `prefers-contrast: more` : des fonds presque pleins et une bordure nette.

On évite aussi les fonds plein écran qui bougent, les oscillations lentes (un
cycle toutes les cinq secondes environ) et les sauts brusques de luminosité :
le passage clair / sombre s'adoucit.

```css
@media (prefers-reduced-motion: reduce) {
  .feuille { transition: opacity 200ms ease; transform: none !important; }
}
@media (prefers-reduced-transparency: reduce) {
  .barre-flottante { background: white; backdrop-filter: none; }
}
```

## La typographie

- **L'approche suit la taille** : un grand titre se resserre (autour de
  `-0.02em`), un petit texte s'aère un peu, le corps reste près de 0. Une seule
  valeur pour toutes les tailles est fausse quelque part.
- **L'interligne va à l'inverse de la taille** : serré pour les titres, ample
  pour le corps ; plus ample pour les écritures à grandes ascendantes, plus
  serré dans une interface dense.
- **La hiérarchie vient de la graisse, de la taille et de l'interligne
  ensemble** ; la graisse met en avant sans prendre de place.
- **Le texte agrandi par la personne** fait grandir la mise en page (espaces
  en `rem` et `em`).
- **La police système d'abord** : elle ajuste déjà ses formes à la taille.

```css
:root { font: 100%/1.5 system-ui, sans-serif; }
.titre-principal {
  font-size: clamp(2rem, 5vw, 4rem);
  line-height: 1.05;
  letter-spacing: -0.02em;
  font-optical-sizing: auto;
}
```

## Les règles de conduite

1. **Faire avec raison**, et décider aussi ce qu'on ne fait pas.
2. **Laisser la main** : des choix, l'annulation facile, une confirmation
   seulement pour l'irréversible (sinon on confirme par réflexe).
3. **Agir dans l'intérêt de la personne** : demander ce qui est nécessaire au
   bon moment, prévoir les mauvais usages.
4. **S'appuyer sur le connu** : ce qui se ressemble se comporte pareil et vit
   au même endroit ; on ne casse une habitude que pour mieux, prouvé.
5. **S'adapter** à l'appareil, au contexte, aux capacités ; laisser
   personnaliser quand une seule mise en page ne va pas à tous.
6. **Simplifier sans appauvrir** : retirer l'inutile pour que l'essentiel
   ressorte ; l'ordre, l'espace et le contraste font la hiérarchie ; le chemin
   courant d'abord, l'avancé un niveau plus bas.
7. **Soigner** : chaque espacement, durée et alignement se défend ; un
   défilement qui tremble ou une icône décalée se lisent comme de la négligence.
8. **Le plaisir** vient des sept autres, pas de confettis ajoutés.

Sur le terrain : quatre sortes de retour (état, achèvement, avertissement,
erreur), la validation au fil de la saisie plutôt qu'à l'envoi ; chaque écran
répond à « où suis-je, où puis-je aller, qu'y a-t-il ici, comment sortir » ;
une commande vit près de ce qu'elle modifie ; des libellés précis plutôt que
des fourre-tout.

## Le tableau de référence

| Besoin | Technique | Valeur |
| --- | --- | --- |
| ressort d'interface par défaut | sans dépassement | amortissement 1, réponse 0,3 à 0,4 s |
| ressort après un lancer | léger rebond | amortissement 0,8 environ, réponse 0,3 à 0,4 s |
| transmettre la vitesse du geste | vitesse initiale du ressort | `vitesse / (cible - actuelle)` si normalisée |
| choisir l'arrivée d'un lancer | projeter l'élan | `actuelle + (v / 1000) * d / (1 - d)`, d autour de 0,998 |
| interrompre proprement | partir de la valeur affichée | lire la transformation à l'écran |
| inverser sans à-coup | garder la vitesse | un ressort qui change de cible |
| valider ou revenir | le signe de la vitesse | au relâchement |
| glisser exactement | Pointer Events et capture | respecter l'endroit saisi |
| un bord | résister | résistance croissante |
| une barre translucide | `backdrop-filter` | le contenu passe dessous |
| l'approche d'un titre | selon la taille | `-0.02em` pour un grand titre, 0 pour le corps |
| le mouvement réduit | un fondu | `@media (prefers-reduced-motion: reduce)` |
