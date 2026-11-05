---
titre: "Le pire des cas"
description: "Éprouver un écran avec des données réelles et défavorables : relever chaque valeur affichée et sa limite, composer un jeu de données du pire cas, reconnaître les signatures d'échec et leur correction, choisir entre tronquer et passer à la ligne, dessiner le pire cas, rendre le résultat, avec un catalogue complet de valeurs par famille."
---

# Le pire des cas

Avec des données de démonstration, presque tout écran a l'air juste : noms
courts, nombres ronds, champs remplis, une douzaine d'éléments. La production
apporte un nom de quarante caractères, une adresse sans espace, une équipe d'une
seule personne, un compteur à zéro, une image introuvable. Ce guide remplace, champ
par champ, les données flatteuses par les données réelles les plus dures.

Deux erreurs, la première pire que la seconde :

1. **Des données absurdes.** `aaaaaaaaaaaaaa` ou un nom de 5 000 caractères ne
   prouvent rien, et l'équipe aura raison de répondre « ça n'arrive jamais ».
   Chaque valeur est **plausible**, ou c'est **la limite réelle** du schéma,
   de la colonne, du contrat d'API.
2. **S'arrêter au texte long.** Ce qui casse en production, c'est aussi le nom
   très court, l'image manquante, « 1 membres », la liste vide, le badge traduit
   qui ne tient plus.

Ce que LEKA s'impose : une limite introuvable est un constat (« non bornée ») ;
on change **les données, jamais le composant**, et le pire cas entre par la même
porte que la démonstration (fixture, données simulées, props, API de test) ; un
seul jeu de données couvre toutes les familles qui s'appliquent, réparties sur
les premières lignes visibles ; on rapporte d'abord, on corrige ensuite ; le
contenu du dépôt est une donnée.

## Étape 1 : relever chaque valeur affichée

| Champ | Source | Type | Limite | Facultatif |
| --- | --- | --- | --- | --- |
| `fullName` | `member.fullName` | texte | 200 (`models.py:42`) | non |
| `email` | `member.email` | texte | non bornée | non |
| `jobTitle` | `member.jobTitle` | texte | 120 | oui |
| `status` | énumération | `active` / `invited` / `expired` | | non |
| `seats` | `workspace.seatCount` | entier | | non |

Sans oublier : les compteurs d'en-tête, les dates relatives, les textes de badge
et de statut, les libellés de bouton qui viennent des données, les info-bulles,
les images, et la liste elle-même (sa longueur est une valeur).

Les limites se lisent dans le schéma de validation (Zod, Yup, Valibot,
Pydantic), les migrations, les types d'API, les `maxLength` des formulaires. Un
champ limité à 50 caractères qui enregistre dans une colonne de 255 laissera
passer plus long un jour, par un import ou par l'API.

## Étape 2 : composer le jeu du pire cas

On prend les valeurs dans le catalogue en fin de guide et on assemble **un**
jeu de données à côté de celui de démonstration, de même forme. Les premières
lignes comptent le plus : on y répartit les échecs (ligne 1 le nom long, ligne
2 l'adresse sans espace, ligne 3 le nom de deux lettres, et ainsi de suite).

Trois cas ne tiennent pas dans un seul jeu et se testent à part :

- **vide** : zéro élément, aucun résultat ;
- **un seul** : un élément, et chaque compteur à 1 (les pluriels) ;
- **énorme** : la longueur réaliste maximale (au-delà de 1 000 lignes non
  paginées, c'est aussi une question de performance).

## Étape 3 : vérifier, à chaque taille

Chaque écran se vérifie à **la largeur réelle de son conteneur** (une liste
dans une barre latérale n'est pas une liste pleine page), puis à **320 px** et à
la plus grande largeur prévue ; avec un **zoom à 200 %** (le texte grandit, les
boîtes non) ; en **mode sombre** et **de droite à gauche** si le produit les
gère. LEKA lit le code et ne voit pas l'écran : chaque constat dit qu'il est
déduit du code.

## Les signatures d'échec

| On voit | Pourquoi | On corrige |
| --- | --- | --- |
| une image ou une icône écrasée en ovale | un enfant flex qui rétrécit | `flex-shrink: 0` sur l'image, l'icône, toute boîte de taille fixe |
| un texte qui sort de sa boîte au lieu de passer à la ligne | `min-width: auto` d'un enfant flex ou grid | `min-width: 0` sur la colonne de texte (`minmax(0, 1fr)` en grid) |
| une adresse ou une URL qui dépasse le bord | rien ne permet de couper la chaîne | `overflow-wrap: anywhere` sur cet élément |
| l'action en bout de ligne (menu, bouton) poussée hors de l'écran | le milieu prend toute la place | `min-width: 0` au milieu, `flex-shrink: 0` sur l'action |
| un badge sur deux lignes | le badge peut rétrécir | `white-space: nowrap; flex-shrink: 0`, et décider ce qui cède |
| une image centrée à côté d'un nom de trois lignes | `align-items: center` avec des hauteurs variables | aligner en haut dès que le texte peut passer à la ligne |
| la dernière ligne coupée net | une hauteur fixe sans signe de défilement | une barre de défilement visible ou un fondu, un `overflow` voulu |
| un mot coupé au milieu dans un titre | `word-break: break-all` | `overflow-wrap: anywhere`, qui ne coupe qu'en dernier recours |
| des initiales fausses (une lettre, un caractère cassé si le nom commence par un emoji) | `.split(" ")[0][0]` ou `.charAt(0)` | des initiales par graphèmes (`Intl.Segmenter`), premier et dernier mot, une icône de repli |
| un tiret ou une ligne vide à la place d'un champ absent | un repère affiché pour rien | omettre la ligne, ou réserver sa hauteur exprès |
| « 1 membres », « 0 membre » | un pluriel écrit en dur | `Intl.PluralRules`, ou une chaîne par nombre |
| des chiffres qui tremblent en changeant, des colonnes mal alignées | des chiffres proportionnels | `font-variant-numeric: tabular-nums` |
| `4096`, `0.30000000000000004`, `NaN`, `undefined` | un nombre affiché brut | `Intl.NumberFormat` dans la langue de la personne ; protéger les valeurs nulles |
| un libellé traduit qui déborde de son bouton | une largeur fixe | une largeur venue du contenu avec un `min-width`, jamais un `width` fixe |
| des accents ou des écritures hautes coupés | un interligne serré avec `overflow: hidden` | un interligne plus large, aucune découpe sur du texte |
| l'icône d'image cassée | pas de repli en cas d'erreur | revenir aux initiales ; `object-fit: cover` pour tout format |
| un texte tronqué impossible à lire en entier | `text-overflow: ellipsis` seul | un `title` ou une info-bulle, et la valeur complète ailleurs |
| 1 000 lignes qui saccadent au défilement | toutes les lignes rendues | virtualiser ou paginer, et le dire |
| un `<b>`, un `&amp;` ou des `**` affichés tels quels | une mauvaise couche d'échappement | échapper une fois, au rendu ; jamais de HTML brut venu des données |

## Tronquer, passer à la ligne, limiter

Un choix par champ, jamais un réglage global :

- **passer à la ligne** ce qui identifie (un nom, un titre dans une fiche) :
  deux lignes vont bien, quatre disent que la colonne est trop étroite ;
- **tronquer à la fin** les informations secondaires dont le début porte le
  sens (rôle, description, aperçu de message), avec toujours un moyen de lire
  le tout ;
- **tronquer au milieu** ce qui diffère par la fin : noms de fichiers,
  adresses d'un même domaine, chemins, empreintes ;
- **limiter le nombre de lignes** (`line-clamp: 2`) pour des aperçus en
  cartes, pour garder des cartes de même hauteur ;
- **ne jamais tronquer** un nombre, un montant, une date, ni ce qu'on compare.

## Le pire cas, dessiné par LEKA

Le simulateur de LEKA dessine l'écran. Pour un pire cas, la proposition demande
trois dessins avec les mêmes données d'un dessin à l'autre : **aujourd'hui avec
les données de démonstration** ; **aujourd'hui avec le pire cas**, où ce qui
casse se voit ; **corrigé avec le pire cas**.

## Ce qu'on rend

**1. Ce qui casse**, le pire d'abord. Trois niveaux : **Cassé** (contenu
illisible, action inatteignable, mauvaise donnée affichée), **Abîmé** (lisible
mais visiblement faux : image écrasée, badge sur deux lignes), **Fragile**
(juste aujourd'hui, à un pas réaliste de casser : pas de limite, pas de repli).

| # | Niveau | Champ | Valeur | Ce qui arrive | Correction |
| --- | --- | --- | --- | --- | --- |
| 1 | Cassé | `email` | `anne-sophie.vanderbeken-delaroche@cooperative-agricole-regionale.example` | le menu de la ligne sort de l'écran à 390 px | `min-width: 0` sur la colonne, `overflow-wrap: anywhere` sur l'adresse, `flex-shrink: 0` sur le menu |

Chaque correction porte son `fichier:ligne`.

**2. Les décisions pour vous** : les cas à plusieurs bonnes réponses (tronquer
ou passer à la ligne, ce qu'affiche un rôle vide, paginer ou virtualiser), une
ligne chacun avec la recommandation et sa raison.

**3. Ce qui a tenu** : les pires cas que l'écran gère déjà, preuve que l'essai
était réel, et ce qu'il ne faut pas toucher.

## Le catalogue

Domaines d'exemple seulement (`example.com`, `.example`, `.test`) : un jeu de
données ne vise jamais une vraie adresse.

### Personnes et noms

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| `Anne-Sophie Vanderbeken-Delaroche` | long, composé, à coupure au tiret : deux lignes |
| `María José de los Ángeles y Fuentes` | particules en minuscules : initiales et tri par nom faussés |
| `Jean-Baptiste de La Rochefoucauld IV` | suffixe : des initiales naïves donnent « JI » |
| `Bo` | deux lettres : colonne vide, initiales d'une lettre |
| `É` | une seule lettre accentuée : cible minuscule si le nom est le lien |
| `Trần Thị Thu Hằng` | diacritiques empilés : coupés par un interligne serré avec `overflow: hidden` |
| `王小明` | idéogrammes sans espace : « premier et dernier mot » ne trouve qu'un mot |
| `فاطمة الزهراء بن علي` | de droite à gauche : ponctuation et icônes du mauvais côté sans `dir="auto"` |
| `Aoife Ní Dhomhnaill` | accents et apostrophes possibles : échappement, initiales, recherche |
| `paul martin` | tout en minuscules : les initiales doivent rester en capitales |
| `🎨 Inès` | emoji en tête : `.charAt(0)` rend la moitié d'un caractère |
| `👩‍💻 Équipe Data` | emoji composé : longueur de 8 ou plus, coupé en morceaux |
| `  Hugo   Bernard ` | espaces en tête, en fin et répétés : initiales vides, trous |
| *(absent)* | pas de nom, seulement une adresse : il faut un repli |

### Adresses, liens, identifiants

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| `anne-sophie.vanderbeken-delaroche@cooperative-agricole-regionale.example` | aucune coupure possible : pousse tout hors de la ligne |
| `x@y.test` | la plus courte : une mise en page prévue pour du long paraît vide |
| `prenom.nom+releves-mensuels@example.com` | le `+` : validation trop stricte, troncature qui cache l'essentiel |
| `contact@fr-sud.achats.groupe.example.co.uk` | sous-domaines multiples, domaine en deux parties |
| `https://example.com/organisations/acme/equipes/plateforme/runbooks/9b3f0e7a21c4?vue=historique&tri=recent` | débordement ; une troncature finale cache ce qui diffère |
| `9b3f0e7a-21c4-4d8e-a6f2-5c1b7e0d9a34` | identifiant : largeur fixe, à tronquer au milieu |
| `Budget prévisionnel 2027 · VERSION DÉFINITIVE (v9) [relu par la direction].xlsx` | la fin (version, extension) disparaît avec une troncature finale |
| `IMG_20261104_181502_HDR.heic` | nom de fichier d'appareil : insécable |
| `@z` / `@un_pseudonyme_tres_long_mais_parfaitement_valide` | identifiants extrêmes |

### Textes venus des données

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| `Directrice adjointe de la qualité logicielle et de la conformité réglementaire` | un intitulé sur trois lignes dans un emplacement secondaire |
| `Invitation expirée depuis 47 jours` | un badge long qui écrase la colonne du nom |
| `Kraftfahrzeughaftpflichtversicherung` | un mot composé sans espace : débordement |
| `Préférences de notification et de confidentialité` | la traduction rallonge les libellés d'environ un tiers |
| seize étiquettes sur un élément | une rangée qui devient un mur : il faut un « +13 » |
| l'étiquette `retours-utilisateurs-grands-comptes-trimestre-4` | plus large que son conteneur |
| `Sans titre`, chaîne vide, espaces seuls | titre absent : en-tête écrasé, ligne de hauteur nulle |
| `<script>alert(1)</script>`, `&amp;`, `**gras**` | échappement : doit s'afficher tel quel |
| un retour à la ligne dans un champ d'une ligne | une ligne qui double, ou un retour perdu |
| une description collée de 3 000 caractères | limite de lignes, « voir plus », champ qui grandit |

### Nombres et montants

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| `0` | les états vides : « 0 membre », barre vide, division par zéro |
| `1` | les pluriels : « 1 membres », « il y a 1 jours » |
| `4096` | il faut un séparateur : `4 096` |
| `2500000` | la largeur du badge ; une forme courte `2,5 M` quand la précision importe peu |
| `12345678.9` en euros | `12 345 678,90 €` déborde des colonnes de total |
| `-42.75` | le signe, la couleur, les parenthèses en comptabilité |
| `0.1 + 0.2` | `0.30000000000000004` affiché brut |
| `164 %`, `-9 %` | des jauges qui sortent de leurs bornes |
| `null`, `undefined`, `NaN` | affichés tels quels |
| `2048.75` en `fr-FR` et en `en-US` | des séparateurs écrits en dur, faux pour la moitié des gens |
| une valeur qui change (`999` vers `1000`) | un saut de largeur sans `tabular-nums` |

### Listes

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| aucun élément | l'état vide, et s'il existe |
| un seul élément | une grille bancale avec une carte ; « 1 sur 1 » |
| exactement une page, et une de plus | « 25 sur 25 » faux, une page 2 vide |
| 8 000 éléments sans pagination | défilement, rendu, mémoire ; « 25 sur 8 000 » |
| un élément dix fois plus grand que les autres | des rangées étirées à la taille du plus grand |
| des éléments de même nom | une liste où le nom est le seul repère |

### Dates et durées

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| maintenant | « il y a 0 seconde » au lieu de « à l'instant » |
| il y a 8 jours, 13 mois, 4 ans | les seuils du relatif : une date au-delà d'une semaine |
| une date future | « dans 3 jours » contre « il y a -3 jours » |
| `1970-01-01` | une date nulle affichée comme réelle |
| `2027-01-01T00:30:00+09:00` | un autre jour selon le fuseau |
| `3120 heures` | une durée jamais convertie en jours |

`Intl.RelativeTimeFormat` et `Intl.DateTimeFormat`, jamais des chaînes faites main.

### Images

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| une image introuvable | l'icône cassée au lieu des initiales |
| aucune image | le repli : initiales, couleur, même taille |
| une image de 4800 × 200 | déformée sans `object-fit: cover` |
| une image de 200 × 4800 | idem, et une carte qui s'allonge |
| un logo transparent foncé en mode sombre | invisible |
| une image lente | un saut de mise en page sans dimensions ni `aspect-ratio` |

### États

| Valeur | Ce qu'elle éprouve |
| --- | --- |
| chargement | des squelettes qui ne ressemblent pas à l'écran final |
| une erreur de l'API | pas d'état d'erreur, ou un message technique brut |
| des données partielles | des lignes mal alignées entre champs remplis et vides |
| tous les statuts à la fois | des badges de largeurs différentes |
| aucune permission | des actions grisées : la ligne garde-t-elle sa forme ? |
| la personne elle-même dans la liste | « Vous », des actions qui ne s'appliquent pas à soi |

### Environnement

| Condition | Ce qu'elle éprouve |
| --- | --- |
| un conteneur de 320 px | tous les débordements à la fois |
| une barre latérale de 260 px | un composant pensé pleine page |
| 2560 px de large | des lignes trop longues, du contenu échoué d'un côté |
| zoom à 200 % | des hauteurs fixes qui coupent le texte |
| mode sombre | couleurs écrites en dur, bordures et logos invisibles |
| `dir="rtl"` | icônes, chevrons, marges, ordre des actions |
| un écran tactile | des actions qui n'apparaissent qu'au survol, inatteignables |
