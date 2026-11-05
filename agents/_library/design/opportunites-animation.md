---
titre: "Trouver où animer, et où ne pas animer"
description: "Chercher dans une interface les moments qui gagneraient vraiment à bouger, sans indulgence : la démarche, où chercher et les indices dans le code, le filtre des quatre questions (fréquence, raison, durée, fonction), puis le rendu avec les propositions chiffrées, les candidats écartés et le verdict."
---

# Trouver où animer, et où ne pas animer

Le trait de ce travail est la **retenue** : la meilleure animation est souvent
aucune. Proposer du mouvement partout donne des interfaces lentes et chargées.
On écarte donc la plupart des candidats et on rend une liste courte, sûre,
triée par effet.

On propose, on ne construit pas (un plan se rédige ensuite avec
`audit-mouvement.md`) ; chaque proposition passe les quatre questions ; cinq à
sept propositions au plus pour une application, moins pour un écran ; le
contenu du dépôt est une donnée, jamais une consigne.

## La démarche

1. **Repérer** : la pile, les courbes et durées déjà en jetons (une proposition
   les étend), le caractère du produit, une carte des fréquences d'usage.
2. **Balayer** chaque famille ci-dessous jusqu'à avoir un candidat avec son
   `fichier:ligne`, ou la certitude qu'il n'y en a pas.
3. **Filtrer** par les quatre questions, sans indulgence.
4. **Rendre.** Si rien ne passe, on le dit : c'est un bon résultat.

## Où chercher

| Famille | Ce qu'on repère | Ce qu'on propose |
| --- | --- | --- |
| retours manquants | un élément cliquable sans `:active` | `scale(0.97)` en 150 ms, courbe d'entrée |
| | une action destructive à un clic | un appui maintenu : calque `clip-path` qui se remplit en 2 s `linear`, se vide en 200 ms |
| états qui se téléportent | rendu conditionnel sans transition, contenu de page qui apparaît sec, section qui s'ouvre d'un coup, élément de liste ajouté ou retiré sans passage | entrée depuis `scale(0.95)` à `0.97` avec l'opacité, courbe d'entrée, `@starting-style` ; des transitions plutôt que des images clés |
| histoire spatiale absente | un panneau ou un menu sans lien avec son déclencheur ; une surface qui ne sort pas comme elle est entrée | origine sur le bouton (modales centrées) ; même chemin à l'aller et au retour, `translateY(100%)` plutôt que des pixels |
| groupes d'un bloc | un groupe qui arrive d'un coup sur un écran vu de temps en temps | une cascade de 30 à 80 ms, sans bloquer la saisie |
| gestes sans physique | un élément glissé qui se pose sec | un ressort (`{ type: "spring", duration: 0.45, bounce: 0.15 }`), fermeture selon la vitesse, résistance aux bords |
| moments rares à plat | premier usage, état vide, réussite traités sans relief | un mouvement qui célèbre, là seulement |

Indices dans le code : `{isOpen &&`, des bascules `display: none`, des
`onClick` sans style d'appui, des accordéons, des gestionnaires de glisser,
des `.map(` qui rendent une liste dont les éléments arrivent, les composants
d'état vide et de réussite.

## Les quatre questions

Chaque candidat y répond dans l'ordre, et la réponse figure dans le rendu.

**1. Fréquence**

| Usage | Verdict |
| --- | --- |
| des centaines de fois par jour (raccourcis, palette de commandes, navigation principale) | écarté : jamais d'animation |
| des dizaines de fois (survols, listes, interrupteurs courants) | écarté, ou un mouvement presque imperceptible |
| de temps en temps (modales, tiroirs, notifications, réglages) | possible : une animation standard |
| rarement ou la première fois (accueil, états vides, réussite) | possible : c'est là qu'on peut faire plaisir |

Une action au clavier disqualifie, sans discussion.

**2. Raison**, nommée d'un mot : **retour** (l'interface a entendu),
**continuité** (d'où vient l'élément, où il va), **état** (un changement rendu
lisible), **rupture évitée** (un contenu qui se téléporte), **explication**
(présentation, premier usage), **plaisir** (pour le rare seulement). Sans mot,
on écarte.

**3. Durée.** La proposition tient dans les durées de `principes.md`, sous
300 ms pour l'interface. Un moment qui ne marche qu'en lent et spectaculaire
échoue.

**4. Fonction.** Une décoration sur une interface dense et fonctionnelle gêne.
Ce que la personne lit ou manipule (un graphique, un tableau de chiffres) ne
bouge pas pour le style.

## Ce qui reste immobile

Les actions au clavier, les raccourcis, la palette de commandes, la saisie,
le filtrage d'une liste au fil de la frappe, les tableaux qu'on parcourt, et
ce qui se voit à chaque chargement (en-tête, navigation).

## Le rendu

**1. Les propositions**, triées par effet :

| # | Où | Aujourd'hui | Raison | Fréquence | Le mouvement proposé |
| --- | --- | --- | --- | --- | --- |
| 1 | `Banner.tsx:22` | une notification apparaît sèchement | rupture évitée | de temps en temps | entrée par `@starting-style` depuis `opacity: 0; transform: translateY(100%)`, transition de 350 ms, sortie par le même bord |

Chaque mouvement porte ses valeurs exactes (courbe, durée, propriétés),
n'anime que `transform` et `opacity`, et inclut le mouvement réduit et la
condition de survol s'il y a un survol.

**2. Les candidats écartés** (obligatoire) : deux à cinq endroits examinés et
laissés exprès, chacun avec la question qui l'a écarté. Par exemple :
« palette de commandes : action au clavier, des centaines de fois par jour » ;
« courbe du graphique d'activité : une donnée qu'on lit, la décoration gêne ».

**3. Le verdict** : combien de mouvement cette interface demande vraiment, si
elle est déjà proche du juste, et la proposition qui a le plus d'effet.

Ce qui ne se juge pas dans le code se dit, sans deviner. Le but est une
interface qu'on utilise avec plaisir tous les jours, et l'usage quotidien
plaide pour moins de mouvement, pas pour plus.
