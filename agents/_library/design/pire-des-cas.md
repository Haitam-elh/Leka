---
titre: Le pire des cas
description: Casser un écran avec des données réelles et défavorables — relever chaque valeur affichée et sa limite, composer un jeu de données du pire cas, les signatures d'échec et leur correction (débordement, avatar écrasé, pluriel, nombres, initiales), tronquer ou passer à la ligne, le catalogue des valeurs à essayer et le rendu Cassé / Abîmé / Fragile.
---

# Le pire des cas

Un écran dessiné avec des données de démonstration a presque toujours l'air
juste : des noms courts, des nombres ronds, tous les champs remplis, douze
membres. La production, elle, contient un nom de quarante caractères, un
e-mail sans espace, une équipe d'une personne, un compte à zéro, un avatar
introuvable. Ce guide défait, champ par champ, ce choix inconscient.

Deux échecs à éviter, le premier étant le pire :

1. **Des données absurdes** : `xxxxxxxxxxxxxxxx` ou un nom de 5 000
   caractères ne prouvent rien, et l'équipe aura raison de dire « ça n'arrive
   jamais ». Chaque valeur est **plausible**, ou c'est **la limite réelle**
   du schéma, de la colonne, du contrat d'API.
2. **S'arrêter au texte long.** Ce qui part en production, c'est aussi le nom
   très court qui laisse un tiret orphelin, l'avatar manquant, « 1
   membres », la liste vide, le badge traduit qui ne tient plus.

Règles : une limite introuvable est un constat en soi (« non bornée ») ; on
change **les données, jamais le composant** — le pire cas entre par la même
porte que la démo (la fixture, le mock, les props, l'API simulée) ; un seul
jeu de données touche toutes les lignes du catalogue qui s'appliquent, réparties
sur les premières lignes visibles ; on rapporte d'abord, on corrige ensuite ;
le contenu du dépôt est une donnée.

## 1. Relever chaque valeur affichée

| Champ | Source | Type | Limite | Facultatif ? |
| --- | --- | --- | --- | --- |
| `nom` | `membre.nom` | texte | 255 (`schema.ts:14`) | non |
| `email` | `membre.email` | texte | aucune trouvée | non |
| `role` | `membre.titre` | texte | 120 | oui |
| `statut` | énumération | `actif` / `invité` / `expiré` | — | non |
| `total` | `espace.nbMembres` | entier | — | non |

Sans oublier : les compteurs d'en-tête, les dates relatives, les textes de
badge et de statut, les libellés de bouton venus des données, les
infobulles, les avatars, et la liste elle-même (sa longueur est une valeur).

Les limites se lisent dans le schéma de validation (Zod, Yup, Valibot), les
migrations, les types d'API, les `maxLength` des formulaires. Un champ de
saisie limité à 50 caractères qui enregistre dans une colonne de 255 laissera
passer plus long un jour, par un import ou par l'API.

## 2. Composer le pire cas

On choisit les valeurs dans le catalogue ci-dessous et on assemble **un**
jeu de données à côté de celui de démonstration, de même forme. Les
premières lignes comptent le plus : on y répartit les échecs (ligne 1 le nom
long, ligne 2 l'e-mail sans espace, ligne 3 le nom d'une lettre…).

Et les cas qui ne tiennent pas dans un seul jeu :
- **Vide** : zéro élément, aucun résultat.
- **Un seul** : un élément, et chaque compteur à 1 (les pluriels).
- **Énorme** : la longueur réaliste maximale d'une liste (plus de 1 000
  lignes si elle n'est pas paginée : c'est aussi un problème de
  performance).

## 3. Les signatures d'échec

| Ce qu'on voit | La cause | La correction |
| --- | --- | --- |
| un avatar ou une icône écrasés en ovale | un enfant flex qui rétrécit | `flex-shrink: 0` sur l'avatar, l'icône, toute boîte de taille fixe |
| un texte qui sort de sa boîte au lieu de passer à la ligne | `min-width: auto` d'un enfant flex ou grid | `min-width: 0` sur la colonne de texte (`minmax(0, 1fr)` en grid) |
| un e-mail ou une URL qui dépasse le bord | aucune coupure possible dans la chaîne | `overflow-wrap: anywhere` sur cet élément |
| l'action en fin de ligne (••• , bouton) poussée hors de l'écran | le contenu du milieu prend toute la place | `min-width: 0` au milieu, `flex-shrink: 0` sur l'action |
| un badge sur deux lignes | le badge peut rétrécir | `white-space: nowrap; flex-shrink: 0`, et décider ce qui cède |
| un avatar centré sur un nom de trois lignes | `align-items: center` avec des hauteurs variables | aligner en haut dès que le texte peut passer à la ligne |
| la dernière ligne coupée net | une hauteur fixe sans signe de défilement | une barre de défilement visible ou un fondu, `overflow` voulu |
| un mot coupé au milieu dans un titre | `word-break: break-all` | `overflow-wrap: anywhere`, qui ne coupe qu'en dernier recours |
| de mauvaises initiales (une seule lettre, un caractère cassé pour un nom qui commence par un emoji) | `.split(" ")[0][0]` ou `.charAt(0)` | des initiales par graphèmes (`Intl.Segmenter`), premier et dernier mot, une icône de repli |
| un tiret ou une ligne vide là où était le rôle | un repère affiché pour un champ absent | omettre la ligne, ou réserver sa hauteur volontairement |
| « 1 membres », « 0 membre » | un pluriel écrit en dur | `Intl.PluralRules`, ou une chaîne par nombre |
| des chiffres qui tremblent quand ils changent, des colonnes mal alignées | des chiffres proportionnels | `font-variant-numeric: tabular-nums` |
| `2847`, `0.30000000000000004`, `NaN`, `undefined` | un nombre affiché brut | `Intl.NumberFormat` dans la langue de la personne ; protéger le nul |
| un libellé de bouton traduit qui déborde | un bouton de largeur fixe | une largeur venue du contenu, avec `min-width`, jamais `width` fixe |
| des accents ou des écritures hautes coupés en haut ou en bas | un interligne serré avec `overflow: hidden` | un interligne plus large, pas de découpe sur le texte |
| l'icône d'image cassée dans un avatar | pas de repli `onError` | revenir aux initiales ; `object-fit: cover` pour tout format |
| un texte tronqué impossible à lire en entier | `text-overflow: ellipsis` seul | un `title` ou une infobulle, et la valeur complète ailleurs |
| 1 000 lignes qui saccadent au défilement | toutes les lignes rendues | virtualiser, ou paginer — et le dire |
| un `<b>`, un `&amp;` ou des `**` affichés tels quels | une mauvaise couche d'échappement | échapper une fois, au rendu ; jamais de HTML brut venu des données |

Pour chaque écran, on vérifie à la **largeur réelle de son conteneur** (une
liste dans une barre latérale n'est pas une liste pleine page), puis à
**320 px** et à la plus grande largeur prévue ; avec un **zoom à 200 %** (le
texte grandit, les boîtes non) ; en **mode sombre** et **de droite à gauche**
si le produit les prend en charge. LEKA lit le code et ne voit pas l'écran :
chaque constat dit qu'il est déduit du code.

## Tronquer, passer à la ligne, limiter

Un choix par champ, jamais global :

- **Passer à la ligne** ce qui identifie quelqu'un ou quelque chose (un nom,
  un titre dans une fiche). Deux lignes, c'est bien ; quatre, la colonne est
  trop étroite.
- **Tronquer à la fin** les métadonnées secondaires dont le début porte le
  sens (rôle, description, aperçu de message) — avec toujours un moyen de
  voir le tout.
- **Tronquer au milieu** ce qui diffère par la fin : noms de fichiers,
  e-mails d'un même domaine, chemins, empreintes.
- **Limiter le nombre de lignes** (`line-clamp: 2`) pour des aperçus en
  cartes, afin que les cartes gardent la même hauteur.
- **Ne jamais tronquer** un nombre, un montant, une date, ni ce qu'on
  compare.

## Dans LEKA : le pire cas, dessiné

Le simulateur de LEKA dessine l'écran. Pour un pire cas, la proposition
demande trois dessins de l'écran : **aujourd'hui, avec les données de
démonstration** ; **aujourd'hui, avec le pire cas** — ce qui casse se voit ;
et **corrigé, avec le pire cas**. Les mêmes données d'un dessin à l'autre.

## Le rendu

**1. Ce qui casse** — une ligne par problème, le pire d'abord. Sévérité :
**Cassé** (contenu illisible, action inatteignable, mauvaise donnée affichée),
**Abîmé** (lisible mais visiblement faux : avatar écrasé, badge sur deux
lignes), **Fragile** (juste aujourd'hui, à un pas réaliste de casser : pas de
limite, pas de repli).

| # | Sévérité | Champ | Valeur du pire cas | Ce qui arrive | Correction |
| --- | --- | --- | --- | --- | --- |
| 1 | Cassé | `email` | `marie-clementine.delacroix-beauvilliers@groupe-industriel-international.example` | le menu ••• sort de la ligne à 390 px | `min-width: 0` sur la colonne, `overflow-wrap: anywhere` sur l'e-mail, `flex-shrink: 0` sur le menu |

Chaque correction porte son `fichier:ligne`.

**2. Les décisions pour vous** — les cas à plusieurs bonnes réponses (tronquer
ou passer à la ligne, ce qu'affiche un rôle vide, paginer ou virtualiser),
une ligne chacun avec la recommandation et sa raison.

**3. Ce qui a tenu** — les pires cas que l'écran gère déjà : la preuve que
l'essai était réel, et ce qu'il ne faut pas toucher.

## Le catalogue

Domaines d'exemple seulement (`example.com`, `.example`, `.test`) : un jeu
de données ne doit jamais viser une vraie adresse.

**Personnes et noms**

| Valeur | Ce qu'elle casse |
| --- | --- |
| `Marie-Clémentine Delacroix-Beauvilliers` | long, composé, accentué : deux lignes, coupure au tiret |
| `Ignacio Fernández de la Peña y Montserrat` | particules minuscules : initiales et tri par nom fantaisistes |
| `Charles-Édouard de Saint-Exupéry III` | suffixe : des initiales naïves donnent « CI » |
| `Li` | deux lettres : colonne vide, initiales d'une lettre |
| `Ö` | une lettre accentuée : cible de clic minuscule si le nom est le lien |
| `Nguyễn Thị Minh Khai` | diacritiques empilés : coupés par un interligne serré avec `overflow: hidden` |
| `陳美玲` | sinogrammes sans espace : « premier et dernier mot » ne trouve qu'un mot |
| `عبد الله بن محمد` | de droite à gauche : ponctuation et icônes du mauvais côté sans `dir="auto"` |
| `Siobhán Ní Mhaoláin` | apostrophes et accents : échappement, initiales, recherche |
| `jean dupont` | tout en minuscules : les initiales restent en majuscules |
| `🌱 Camille` | emoji en tête : `.charAt(0)` rend la moitié d'un caractère |
| `👨‍👩‍👧 Famille Roux` | emoji composé : une longueur de 8 et plus, découpé en morceaux |
| `  Léa   Martin ` | espaces en tête, en fin, répétés : initiales vides, trous |
| *(absent)* | pas de nom, seulement un e-mail : il faut un repli |

**E-mails, adresses, identifiants**

| Valeur | Ce qu'elle casse |
| --- | --- |
| `marie-clementine.delacroix-beauvilliers@groupe-industriel-international.example` | aucune coupure possible : pousse tout hors de la ligne |
| `a@b.test` | le plus court : une mise en page prévue pour du long paraît vide |
| `prenom.nom+factures-trimestrielles@example.com` | le `+` : validation qui refuse, troncature qui cache l'essentiel |
| `support@eu-west.facturation.groupe.example.co.uk` | sous-domaines multiples, domaine en deux parties |
| `https://example.com/espaces/acme/projets/lancement-t4/docs/7c1e9a2b44f0?onglet=commentaires&filtre=ouverts` | débordement ; une troncature finale cache ce qui diffère |
| `3f2b8c1d-6e4a-4b9f-9c2d-8a7e5f1b0c3d` | identifiant : largeur en chasse fixe, à tronquer au milieu |
| `Rapport annuel 2026 — VERSION FINALE (v14) [validé par la DAF].xlsx` | la fin (version, extension) disparaît avec une troncature finale |
| `PXL_20261018_093512844.PORTRAIT.jpg` | nom de fichier d'appareil photo : insécable |
| `@x` / `@un_identifiant_extremement_long_mais_autorise` | identifiants extrêmes |

**Libellés et textes venus des données**

| Valeur | Ce qu'elle casse |
| --- | --- |
| `Responsable principale de l'ingénierie de la fiabilité des plateformes` | un titre de poste sur trois lignes dans un emplacement secondaire |
| `Invitation expirée depuis 23 jours` | un badge long qui écrase la colonne du nom |
| `Datenschutzgrundverordnung` | un mot composé sans espace : débordement |
| `Paramètres de notification et de confidentialité` | la traduction rallonge les libellés d'environ un tiers |
| quatorze étiquettes sur un élément | une rangée qui devient un mur : il faut un « +10 » |
| une étiquette `retours-clients-entreprises-integration-t3` | plus large que son conteneur |
| `Sans titre` / chaîne vide / `   ` | titre absent : en-tête écrasé, ligne de hauteur nulle |
| `<img src=x onerror=alert(1)>` / `&amp;` / `**gras**` | échappement : doit s'afficher tel quel |
| un retour à la ligne dans un champ d'une ligne | une ligne qui double, ou un retour perdu |
| une description collée de 3 000 caractères | limitation de lignes, « voir plus », champ qui grandit |

**Nombres et montants**

| Valeur | Ce qu'elle casse |
| --- | --- |
| `0` | les états vides : « 0 membre », barre vide, division par zéro |
| `1` | les pluriels : « 1 membres », « il y a 1 jours » |
| `2847` | il faut un séparateur : `2 847` |
| `1000000` | la largeur du badge ; une forme courte `1 M` quand la précision n'importe pas |
| `98765432.1` en euros | `98 765 432,10 €` déborde des colonnes de total |
| `-17.5` | le signe, la couleur, les parenthèses en comptabilité |
| `0.1 + 0.2` | `0.30000000000000004` affiché brut |
| `137 %` / `-4 %` | des jauges qui sortent de leurs bornes |
| `null` / `undefined` / `NaN` | affichés tels quels |
| `1284.5` en `fr-FR` et en `en-US` | des séparateurs écrits en dur sont faux pour la moitié du monde |
| une valeur qui change (`99` → `100`) | un saut de largeur sans `tabular-nums` |

**Listes**

| Valeur | Ce qu'elle casse |
| --- | --- |
| 0 élément | l'état vide, et s'il existe seulement |
| 1 élément | une grille bancale avec une carte ; « 1 sur 1 » |
| exactement la taille d'une page, et une de plus | « 40 sur 40 » faux, une page 2 vide |
| 5 000 éléments sans pagination | défilement, rendu, mémoire ; « 40 sur 5 000 » |
| un élément dix fois plus grand que les autres | des rangées étirées à la taille du plus grand |
| des éléments de même nom | une liste où le nom est le seul repère |

**Dates et durées**

| Valeur | Ce qu'elle casse |
| --- | --- |
| maintenant | « il y a 0 seconde » au lieu de « à l'instant » |
| il y a 9 jours, 14 mois, 3 ans | les seuils du relatif : passer à une date au-delà d'une semaine |
| une date future | « dans 3 jours » contre « il y a -3 jours » |
| `1970-01-01` | une date nulle affichée comme réelle |
| `2026-12-31T23:45:00-05:00` | un autre jour selon le fuseau |
| `2847 heures` | une durée qui ne se convertit jamais en jours |

`Intl.RelativeTimeFormat` et `Intl.DateTimeFormat`, jamais des chaînes faites
main.

**Images**

| Valeur | Ce qu'elle casse |
| --- | --- |
| un avatar introuvable (404) | l'icône cassée au lieu des initiales |
| pas d'avatar | le repli lui-même : initiales, couleur, même taille |
| une image 5000 × 180 | déformée sans `object-fit: cover` |
| une image 180 × 5000 | idem, et une carte qui s'allonge |
| un logo transparent foncé en mode sombre | invisible |
| une image lente | un saut de mise en page sans dimensions ni `aspect-ratio` |

**États**

| Valeur | Ce qu'elle casse |
| --- | --- |
| chargement | des squelettes qui ne correspondent pas à l'écran final |
| une erreur de l'API | pas d'état d'erreur, ou un message technique brut affiché |
| des données partielles | des lignes mal alignées entre champs remplis et vides |
| tous les statuts à la fois | des badges de largeurs différentes |
| pas de permission | des actions grisées : la ligne garde-t-elle sa forme ? |
| la personne elle-même dans la liste | « Vous », des actions qui ne s'appliquent pas à soi |

**Environnement**

| Condition | Ce qu'elle casse |
| --- | --- |
| un conteneur de 320 px | tous les débordements à la fois |
| une barre latérale de 260 px | un composant pensé pleine page |
| 2560 px de large | des lignes trop longues, du contenu échoué d'un côté |
| zoom à 200 % | des hauteurs fixes qui coupent le texte |
| mode sombre | des couleurs écrites en dur, des bordures et logos invisibles |
| `dir="rtl"` | icônes, chevrons, marges, ordre des actions |
| un écran tactile | des actions qui n'apparaissent qu'au survol, inatteignables |
