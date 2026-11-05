---
titre: "Le vocabulaire du mouvement"
description: "Mettre le mot juste sur un effet décrit vaguement (« le truc qui rebondit quand le menu s'ouvre ») : on part de ce que la personne dit avoir vu, on trouve le terme, ses voisins et ce qui les distingue ; entrées et sorties, rythme, transformations, changements d'état, défilement, retours d'interaction, courbes, ressorts, boucles, finitions, performance et principes."
---

# Le vocabulaire du mouvement

Les gens décrivent ce qu'ils voient (« ça rebondit », « ça se dessine tout
seul »), rarement le terme exact. On part donc de leurs mots. On répond par le
terme le plus proche, puis un ou deux voisins avec ce qui les sépare. Si rien
ne correspond, on le dit et on décrit l'effet en combinant ces termes (« une
*cascade* d'*entrées à l'échelle* »).

## Ce que la personne dit, le terme

### Ça apparaît, ça disparaît

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « ça s'estompe », « ça apparaît doucement » | **fondu** (entrant, sortant) | seule l'opacité change |
| « ça arrive du bord » | **glissement** | entre depuis un bord de l'écran |
| « ça grossit en arrivant » | **entrée à l'échelle** | part d'un peu plus petit, souvent avec un fondu |
| « ça rebondit en s'ouvrant » | **apparition avec rebond** | dépasse légèrement sa taille puis revient |
| « ça se découvre petit à petit » | **révélation** | par une découpe ou un masque |
| « l'animation quand on ajoute un élément » | **entrée** / **sortie** | jouée à l'ajout ou au retrait |

### Le rythme

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « les étapes de l'animation » | **images clés** | des points fixés (0 %, 50 %, 100 %), le navigateur complète |
| « le calcul entre deux positions » | **interpolation** | les valeurs intermédiaires d'un mouvement continu |
| « les éléments arrivent l'un après l'autre » | **cascade** | un petit décalage entre chacun |
| « plusieurs animations qui n'en font qu'une » | **orchestration** | réglées ensemble |
| « le temps avant que ça commence », « combien de temps ça dure » | **délai**, **durée** | |
| « ça garde la dernière position » | **mode de remplissage** | le style de la première ou dernière image conservé |
| « ça avance par à-coups, comme un compte à rebours » | **animation par paliers** | des sauts discrets |

### Ça se transforme

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « ça bouge », « ça grandit », « ça tourne », « ça penche » | **translation**, **échelle**, **rotation**, **inclinaison** | déplacer, agrandir, tourner, cisailler |
| « ça bascule en 3D » | **bascule 3D** | rotation dans l'espace (`rotateX`, `rotateY`) |
| « l'effet de profondeur » | **perspective** | l'intensité de la profondeur |
| « ça grandit depuis un coin » | **point d'origine** | le point depuis lequel on agrandit ou on tourne |
| « le menu sort du bouton » | **animation depuis le déclencheur** | naît de ce qui l'ouvre, pas de son propre centre |

### On passe d'un état à un autre

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « l'un s'efface pendant que l'autre arrive » | **fondu enchaîné** | au même endroit |
| « on voit que c'est le même objet avant et après » | **transition de continuité** | avant et après reliés (le même rectangle qui grandit) |
| « une forme devient une autre » | **métamorphose** | |
| « la vignette devient la fiche » | **élément partagé** | un élément voyage et se transforme d'un endroit à l'autre |
| « ça glisse à sa nouvelle place au lieu de sauter » | **animation de mise en page** | taille ou position animées |
| « la section se déplie » | **accordéon** | se déplie et se replie |
| « on avance d'un côté, on revient de l'autre » | **transition orientée** | un sens pour avancer, l'autre pour revenir |

### Au défilement

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « ça apparaît quand on descend » | **révélation au défilement** | à l'entrée dans la fenêtre |
| « ça avance en même temps que le défilement » | **animation pilotée par le défilement** | sa progression suit la position |
| « le fond va moins vite que le reste » | **parallaxe** | des plans à des vitesses différentes |
| « l'animation entre deux pages » | **transition de page**, **transition de vue** | la seconde relie les éléments communs |

### En réponse à la personne

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « ça change quand on passe la souris » | **survol** | |
| « le bouton s'enfonce » | **retour d'appui** | un léger rétrécissement au clic ou au toucher |
| « il faut rester appuyé pour supprimer » | **maintenir pour confirmer** | une progression qui se remplit pendant l'appui |
| « on le déplace », « on change l'ordre », « on le jette sur le côté » | **glisser**, **glisser pour réordonner**, **balayer pour fermer** | |
| « ça résiste puis ça revient » | **effet élastique** | au-delà d'une limite |
| « ça tremble quand c'est refusé » | **secousse** | un tremblement bref |
| « un cercle qui s'étend où on a touché » | **onde** | |

## Les courbes

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « la façon dont ça accélère » | **courbe d'accélération** | l'évolution de la vitesse |
| « ça part vite et se pose doucement » | **décélération** (`ease-out`) | le choix par défaut d'une interface |
| « ça démarre lentement » | **accélération** (`ease-in`) | à éviter : ça paraît mou |
| « ça accélère puis freine » | **accélération-décélération** (`ease-in-out`) | pour ce qui va d'un point à un autre à l'écran |
| « vitesse constante » | **linéaire** | chargements, défilements en boucle |
| « une courbe sur mesure » | **courbe de Bézier** | |
| « ça accélère et ralentit différemment » | **courbe asymétrique** | |

## Les ressorts

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « ça bouge comme un vrai objet » | **ressort** | une physique (tension, masse, amortissement) plutôt qu'une durée |
| « plus nerveux », « se pose plus vite », « plus lourd » | **raideur**, **amortissement**, **masse** | la force qui ramène, la vitesse à se poser, le poids ressenti |
| « ça dépasse puis revient » | **rebond** | |
| « quand ça a l'air arrivé » | **durée perçue** | |
| « ça continue sur sa lancée » | **élan**, **vitesse** | ce qu'un mouvement porte après un geste |
| « on peut le rattraper en route » | **animation interruptible** | réorientable en cours de route |

## En boucle

« Ça tourne sans fin », « ça va et vient », « ça respire », « ça flotte » :
**défilement continu**, **boucle**, **aller-retour**, **orbite**,
**pulsation**, **flottement**, **animation au repos**.

## Les finitions

| Ce qu'on entend | Le terme | Ce qui le distingue |
| --- | --- | --- |
| « c'est un peu flou pendant le passage » | **flou** | adoucir, ou masquer une imperfection |
| « on ne voit qu'une partie » | **découpe**, **masque** | le masque a des bords doux |
| « on fait glisser une barre entre avant et après » | **comparateur avant / après** | |
| « le trait se dessine » | **tracé** | un chemin SVG |
| « le texte change en s'animant », « les chiffres défilent », « ça s'écrit lettre par lettre » | **changement de texte animé**, **compteur qui défile**, **machine à écrire** | |
| « les blocs gris qui brillent pendant le chargement » | **squelette**, **reflet** | |
| « les chiffres ne bougent pas en changeant » | **chiffres à chasse fixe** | |

## La performance

« Ça accroche », « ça rame » : **images par seconde**, **saccade**, **image
perdue**. Les termes voisins : **composition** (le processeur graphique déplace
une couche sans refaire la mise en page), **`will-change`** (prévenir le
navigateur d'une animation imminente), **recalculs en rafale** (une propriété
de mise en page animée à chaque image).

## Les principes

| Ce qu'on entend | Le terme |
| --- | --- |
| « ça sert à quelque chose, pas juste joli » | **mouvement utile** |
| « un petit recul avant de partir » | **anticipation** |
| « des morceaux qui arrivent un peu après le reste » | **inertie de fin** |
| « ça s'écrase en tombant » | **écrasement et étirement** |
| « ça a l'air plus rapide » | **vitesse perçue** |
| « plus on la voit, plus elle doit être discrète » | **fréquence d'usage** |
| « on sait toujours où est passé l'objet » | **continuité spatiale** |
| « l'option pour moins d'animations » | **mouvement réduit** |
