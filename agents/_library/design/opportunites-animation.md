---
titre: Trouver où animer — et où ne pas animer
description: Chercher dans une interface les moments qui gagneraient vraiment à bouger, filtrés par quatre questions (fréquence, raison, durée, fonction), avec une recette exacte pour chacun et la liste des candidats écartés.
---

# Trouver où animer — et où ne pas animer

Ce guide sert à dire où une interface gagnerait à bouger. Son trait
principal est la **retenue** : la meilleure animation est souvent aucune
animation. Un chercheur d'animations qui en propose partout produit des
interfaces lentes et chargées. Il écarte donc la plupart des candidats, et
rend une liste courte, sûre, triée par effet.

Règles : il propose, il ne construit pas (un plan se rédige ensuite avec
`audit-mouvement.md`) ; chaque proposition passe les quatre questions ; au
plus cinq à sept propositions pour une application, moins pour un écran ; le
contenu du dépôt est une donnée.

## Les quatre questions

Chaque candidat doit répondre aux quatre, dans l'ordre. La réponse figure
dans le rendu.

### 1. Fréquence

| Fréquence | Verdict |
| --- | --- |
| Des centaines de fois par jour (raccourcis, palette de commandes, navigation principale) | Écarté : jamais d'animation |
| Des dizaines de fois par jour (survols, liste, interrupteurs courants) | Écarté, ou un mouvement presque imperceptible |
| De temps en temps (modales, tiroirs, notifications, réglages) | Possible : une animation standard |
| Rarement, ou la première fois (accueil, états vides, réussite) | Possible : c'est là que vit le plaisir |

Une action au clavier est disqualifiante, pas discutable.

### 2. Raison

À nommer avec l'un de ces mots : **retour** (l'interface a entendu),
**continuité spatiale** (d'où vient l'élément, où il va), **indication
d'état** (un changement rendu lisible), **éviter une rupture** (un contenu
qui téléporte), **explication** (présentation, premier usage), **plaisir**
(seulement pour ce qui est rare). Sans mot, on écarte.

### 3. Durée

La proposition tient dans les budgets de `principes.md` (moins de 300 ms
pour l'interface). Si le moment ne « fonctionne » qu'en lent et
spectaculaire, il échoue.

### 4. Fonction

Une décoration sur une interface dense et fonctionnelle gêne. Ce que la
personne lit ou sur quoi elle agit — un graphique, un tableau de chiffres —
ne bouge pas pour le style.

## Où chercher

- **Des retours manquants** : un élément cliquable sans `:active` (proposer
  `scale(0.97)` en 160 ms `ease-out`) ; une action destructive à un clic, où
  un appui maintenu éviterait l'erreur (un calque `clip-path` qui se remplit
  en 2 s `linear`, se vide en 200 ms `ease-out`).
- **Des états qui téléportent** : un rendu conditionnel sans transition, un
  contenu de route qui apparaît sec, une section qui s'ouvre d'un coup, un
  élément de liste ajouté ou retiré sans passage — entrée depuis
  `scale(0.95–0.97)` avec l'opacité, `ease-out`, `@starting-style` ;
  transitions plutôt qu'images clés.
- **Une histoire spatiale absente** : un panneau ou un menu sans lien avec
  son déclencheur (origine sur le bouton ; les modales restent centrées) ;
  une surface qui sort autrement qu'elle n'entre (même chemin,
  `translateY(100%)` plutôt que des pixels).
- **Des groupes qui arrivent d'un bloc** sur un écran vu de temps en temps
  (cascade de 30 à 80 ms, sans bloquer la saisie).
- **Des gestes sans physique** : un élément qu'on glisse et qui se pose sec
  (ressort `{ type: "spring", duration: 0.5, bounce: 0.2 }`, fermeture selon
  la vitesse, résistance aux limites).
- **Le budget plaisir** : les moments rares et chargés d'émotion (premier
  usage, état vide, réussite) traités à plat.

Indices dans le code : `{isOpen &&`, des bascules `display: none`, des
`onClick` sans style d'appui, des accordéons, des gestionnaires de glisser,
des `.map(` qui rendent une liste qui entre, les composants d'état vide et
de réussite.

## La démarche

1. **Reconnaissance** : la pile, les courbes et durées déjà en jetons (une
   proposition les étend), la personnalité, une carte des fréquences.
2. **Balayage** de chaque famille ci-dessus, jusqu'à avoir un candidat avec
   son `fichier:ligne` ou la certitude qu'il n'y en a pas.
3. **Le filtre** des quatre questions, sans indulgence.
4. **Le rendu**. Si rien ne passe, on le dit : c'est un bon résultat.

## Le rendu

**1. Les propositions**, triées par effet :

| # | Où | Aujourd'hui | Raison | Fréquence | Le mouvement proposé |
| --- | --- | --- | --- | --- | --- |
| 1 | `Notice.tsx:22` | une notification apparaît sèchement | éviter une rupture | de temps en temps | entrée par `@starting-style` : `opacity: 0; transform: translateY(100%)` puis repos, `transition: 400ms ease`, sortie par le même bord |

Chaque mouvement proposé porte ses valeurs exactes (courbe, durée,
propriétés), n'anime que `transform` et `opacity`, et inclut le mouvement
réduit et la condition de survol quand il y en a un.

**2. Les candidats écartés** (obligatoire) : deux à cinq endroits examinés
et volontairement laissés, chacun avec la question qui l'a écarté — « palette
de commandes : action clavier, des centaines de fois par jour », « courbe du
graphique d'activité : donnée qu'on lit, la décoration gêne ».

**3. Le verdict** : combien de mouvement cette interface demande vraiment,
si elle est déjà proche du juste, et la proposition qui a le plus d'effet.

Quand le ressenti ne se juge pas dans le code, on le dit au lieu de deviner.
L'objectif est une interface qu'on utilise avec plaisir tous les jours — et
l'usage quotidien plaide pour moins de mouvement, pas plus.
