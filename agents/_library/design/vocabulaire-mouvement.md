---
titre: Le vocabulaire du mouvement
description: Mettre le mot juste sur un effet décrit vaguement (« le truc qui rebondit quand le menu s'ouvre ») — un glossaire des entrées et sorties, du rythme, des transformations, des transitions entre états, du défilement, des retours d'interaction, des courbes, des ressorts, du mouvement en boucle, des finitions, de la performance et des principes.
---

# Le vocabulaire du mouvement

Les gens décrivent ce qu'ils voient ou ressentent (« ça rebondit », « ça se
dessine tout seul ») plutôt que le terme exact. Ce glossaire fait le lien. On
répond par le terme le plus proche, puis un ou deux voisins avec ce qui les
distingue ; si rien ne correspond, on le dit, et on décrit l'effet avec ces
mots (« une *cascade* d'*entrées à l'échelle* »).

## Apparaître et disparaître

- **Fondu (entrant, sortant)** — l'élément apparaît ou disparaît par son
  opacité.
- **Glissement** — il entre depuis un bord de l'écran.
- **Entrée à l'échelle** — il grandit d'un peu plus petit jusqu'à sa taille,
  souvent avec un fondu.
- **Apparition avec rebond** — il dépasse légèrement sa taille et revient.
- **Révélation** — le contenu se découvre progressivement, par une découpe ou
  un masque.
- **Entrée / sortie** — l'animation jouée à l'ajout ou au retrait d'un
  élément.

## Rythme et enchaînement

- **Images clés** — des points définis (0 %, 50 %, 100 %) entre lesquels le
  navigateur complète.
- **Interpolation** — le calcul des valeurs intermédiaires pour un mouvement
  continu.
- **Cascade** — plusieurs éléments animés l'un après l'autre, avec un petit
  décalage.
- **Orchestration** — plusieurs animations réglées pour n'en former qu'une.
- **Délai**, **durée** — avant de commencer, et combien de temps.
- **Mode de remplissage** — garder le style de la première ou de la dernière
  image avant ou après l'animation.
- **Animation par paliers** — des sauts discrets, comme un compte à rebours.

## Transformations

- **Translation**, **échelle**, **rotation**, **inclinaison** — déplacer,
  agrandir, tourner, cisailler.
- **Bascule 3D** — une rotation dans l'espace (`rotateX`, `rotateY`).
- **Perspective** — l'intensité de la profondeur 3D.
- **Point d'origine** — le point depuis lequel on agrandit ou on tourne.
- **Animation depuis le déclencheur** — l'élément naît de ce qui l'ouvre
  (un menu depuis son bouton) au lieu de son propre centre.

## Passer d'un état à l'autre

- **Fondu enchaîné** — l'un s'efface pendant que l'autre apparaît, au même
  endroit.
- **Transition de continuité** — avant et après reliés visuellement (le même
  rectangle qui grandit).
- **Métamorphose** — une forme qui devient une autre.
- **Élément partagé** — un élément voyage et se transforme d'un endroit à un
  autre (une vignette qui devient une fiche).
- **Animation de mise en page** — un élément qui change de taille ou de place
  s'y rend au lieu de sauter.
- **Accordéon** — une section qui se déplie et se replie.
- **Transition orientée** — un sens pour avancer, l'autre pour revenir.

## Défilement

- **Révélation au défilement** — les éléments entrent quand ils arrivent dans
  la fenêtre.
- **Animation pilotée par le défilement** — sa progression suit la position.
- **Parallaxe** — l'arrière-plan et le premier plan défilent à des vitesses
  différentes.
- **Transition de page**, **transition de vue** — à la navigation ; la vue
  relie des éléments communs.

## Retours d'interaction

- **Survol** — un changement quand le pointeur passe dessus.
- **Retour d'appui** — un léger enfoncement au clic ou au toucher.
- **Maintenir pour confirmer** — une progression qui se remplit pendant
  l'appui.
- **Glisser**, **glisser pour réordonner**, **balayer pour fermer**.
- **Effet élastique** — la résistance puis le retour au-delà d'une limite.
- **Secousse** — un tremblement bref qui signale un refus.
- **Onde** — un cercle qui s'étend depuis le point touché.

## Courbes

- **Courbe d'accélération** — comment la vitesse évolue pendant l'animation.
- **Décélération (`ease-out`)** — rapide puis lent ; le choix par défaut de
  l'interface.
- **Accélération (`ease-in`)** — lent puis rapide ; à éviter, ça paraît mou.
- **Accélération-décélération (`ease-in-out`)** — pour ce qui se déplace
  d'un point à un autre à l'écran.
- **Linéaire** — vitesse constante ; pour un chargement, un défilement en
  boucle.
- **Courbe de Bézier** — une courbe sur mesure.
- **Courbe asymétrique** — qui accélère et ralentit différemment.

## Ressorts

- **Ressort** — un mouvement dicté par une physique (tension, masse,
  amortissement) plutôt qu'une durée.
- **Raideur**, **amortissement**, **masse** — la force qui ramène, la vitesse
  à se poser, le poids ressenti.
- **Rebond** — un dépassement puis un retour.
- **Durée perçue** — quand le ressort semble posé.
- **Élan**, **vitesse** — ce qu'un mouvement porte après un geste.
- **Animation interruptible** — qu'on peut réorienter en cours de route.

## En boucle

- **Défilement continu**, **boucle**, **aller-retour**, **orbite**,
  **pulsation**, **flottement**, **animation au repos**.

## Finitions

- **Flou** — pour adoucir, ou masquer une imperfection.
- **Découpe**, **masque** — révéler une partie ; le masque a des bords doux.
- **Comparateur avant / après** — une séparation qu'on fait glisser.
- **Tracé** — un chemin SVG qui se dessine.
- **Changement de texte animé**, **compteur qui défile**, **machine à
  écrire**.
- **Squelette, reflet** — un emplacement animé pendant le chargement.
- **Chiffres à chasse fixe** — pour que les nombres ne bougent pas en
  changeant.

## Performance

- **Images par seconde**, **saccade**, **image perdue**.
- **Composition** — le processeur graphique déplace une couche sans refaire
  la mise en page.
- **`will-change`** — prévenir le navigateur d'une animation imminente.
- **Recalculs en rafale** — animer une propriété de mise en page à chaque
  image.

## Principes

- **Mouvement utile** — il oriente, répond, relie ; il ne décore pas.
- **Anticipation** — un petit élan à l'envers avant le mouvement.
- **Inertie de fin** — des parties qui se posent un peu après le reste.
- **Écrasement et étirement** — une déformation qui dit le poids et la
  vitesse.
- **Vitesse perçue** — la bonne animation rend une interface plus rapide à
  l'œil.
- **Fréquence d'usage** — plus on voit une animation, plus elle doit être
  courte et discrète.
- **Continuité spatiale** — un élément garde son identité et sa place d'un
  état à l'autre.
- **Mouvement réduit** — respecter la préférence en adoucissant ou en
  retirant le mouvement.
