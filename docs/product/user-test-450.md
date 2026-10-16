# Test utilisateur chronométré — de l'inscription à la première réponse utile (LEKA-450)

Recette de LEKA-445 (décision de Karim du 14/10, point 2). Responsable :
Karim, avec l'appui de Bilal pour la mesure.

Ce document est le protocole écrit demandé par le ticket : il se suit tel
quel le jour du test, et se rend rempli (grille d'observation et compte
rendu) dans le ticket.

**Les documents de la séance**, prêts à imprimer ou à remplir
(`docs/product/user-test-450/`) :

- `recette-445.md` — la liste de contrôle de la recette de Karim (critère 1) ;
- `consentement.md` — l'accord de participation et d'enregistrement ;
- `grille.md` — la grille d'observation d'une séance, avec la mesure ;
- `compte-rendu-modele.md` — le compte rendu et la synthèse (critère 5).

---

## 1. Avant le test

- [ ] **La recette fonctionnelle de Karim est faite**, et ses retours sont
      notés en commentaire de LEKA-450. Le test n'a pas lieu avant.
- [ ] Les blocages trouvés par la recette sont corrigés et déployés, ou
      acceptés comme connus (listés dans le ticket).
- [ ] L'environnement est choisi (voir § 3) et vérifié la veille : inscription,
      e-mail de confirmation reçu, démo qui s'ouvre, une question qui reçoit
      une réponse.
- [ ] La personne testée a donné son accord écrit pour l'enregistrement de
      l'écran et de la voix, et sait qu'on teste LEKA, pas elle.

## 2. La personne testée

- **Extérieure à l'équipe** : ni Karim, ni Bilal, ni Haitam, ni quelqu'un qui a
  déjà vu LEKA en démonstration.
- **Du public visé** : quelqu'un qui travaille dans ou avec une équipe
  informatique (développeur, responsable technique, DSI, chef de projet
  technique), à l'aise avec un ordinateur.
- **Sans préparation** : elle ne lit rien sur LEKA avant le test.
- Une personne par séance. Idéalement trois séances, avec trois profils
  différents, pour distinguer un problème de LEKA d'un problème de la personne.

## 3. L'environnement

- **La production** (`https://leka-core.com`), dans l'état où un vrai
  visiteur la trouve.
- **Un compte neuf** : une adresse e-mail que la personne n'a jamais utilisée
  sur LEKA, à laquelle elle a accès pendant le test (sa boîte personnelle ou
  une adresse créée pour l'occasion).
- **Avec ou sans démo : c'est la personne qui choisit**, à l'écran d'accueil
  (« Connecter une source » ou « Explorer la démo », LEKA-451). Le choix fait
  partie de ce qu'on observe. Si elle choisit de connecter une source, elle
  utilise un outil auquel elle a un accès réel (son GitHub, par exemple) —
  sinon, on note qu'elle n'a pas pu, et elle continue avec la démo.
- Son ordinateur et son navigateur habituels, en plein écran. L'animateur est
  à côté ou en visioconférence, l'écran partagé et enregistré.

## 4. La consigne unique

Lue telle quelle, une seule fois, puis plus rien :

> « Voici LEKA, un assistant pour les équipes informatiques. Inscris-toi, puis
> obtiens de LEKA une réponse utile à une question sur un système
> informatique — le tien ou celui de la démo. Dis à voix haute ce que tu
> penses et ce que tu cherches pendant que tu avances. Je ne pourrai pas
> t'aider : fais comme si tu étais seul. Dis-moi « j'ai ma réponse » quand tu
> l'as. »

## 5. Pendant le test

- **Aucune aide.** L'animateur ne répond à aucune question sur LEKA. Seule
  réponse permise : « Fais comme si tu étais seul. »
- L'animateur ne parle que pour relancer la pensée à voix haute
  (« Qu'est-ce que tu cherches ? »), jamais pour orienter.
- Il note tout dans la grille (§ 7), en direct, avec l'heure.
- **Arrêt** : quand la personne dit « j'ai ma réponse », quand elle abandonne,
  ou au bout de **30 minutes**. Un abandon ou un arrêt est un résultat, pas un
  échec du test.

## 6. Ce qu'on mesure

### La « première réponse utile »

C'est la première réponse de LEKA qui remplit **les trois** conditions :

1. elle répond à la question que la personne a posée (pas à une autre) ;
2. elle porte sur des éléments réels — sa source ou la démo —, pas sur des
   généralités ;
3. **la personne dit elle-même** qu'elle lui apprend quelque chose ou lui
   permettrait d'agir.

Une réponse qui ne remplit pas les trois est notée dans la grille ; le
chronomètre continue jusqu'à la suivante.

### Les temps

Chaque étape est datée par LEKA lui-même. Après le test, sur le serveur :

```
docker exec leka-api-1 python -m leka.ops.first_answer <e-mail de la personne>
```

| Étape | Ce qui la date |
|---|---|
| Inscription | le compte créé |
| Confirmation de l'e-mail | l'adresse confirmée |
| Workspace | le premier espace de travail rejoint (hors démo) |
| Source ou démo | la première source ajoutée, ou la démo ouverte — la première des deux |
| Question | la première intention posée |
| Réponse | la première analyse livrée (complète ou partielle) |

La commande donne, pour chacune, l'heure, le temps de l'étape et le temps
depuis l'inscription. **Le temps total retenu** est celui de la réponse que la
personne a jugée utile : si c'est la première réponse livrée, celui de la
commande ; sinon, celui de la réponse utile, relevé dans la grille.

L'animateur garde aussi un chronomètre, en secours, et note l'heure du
« j'ai ma réponse ».

## 7. La grille d'observation

Une ligne par événement, au moment où il arrive :

| Heure | Étape | Écran | Type | Ce qui se passe | Ce que la personne dit |
|---|---|---|---|---|---|
| 10:04:12 | Inscription | /signup | Hésitation | relit le formulaire trois fois avant de valider | « il faut un mot de passe de combien ? » |
| | | | | | |

**Types** :

- **Hésitation** — elle s'arrête plus de 5 secondes sans savoir quoi faire,
  ou revient en arrière.
- **Erreur** — elle fait quelque chose qui ne mène pas où elle voulait
  (mauvais bouton, mauvaise page, saisie refusée).
- **Incompréhension** — elle comprend mal un mot, un écran ou une réponse de
  LEKA, ou le dit.
- **Blocage** — elle ne peut pas continuer seule (sans le test, elle
  appellerait quelqu'un ou abandonnerait).
- **Positif** — ce qui marche et qu'elle remarque : à garder.

## 8. Après le test

Deux questions, pas plus, sitôt l'arrêt :

1. « Qu'est-ce qui a été le plus difficile ? »
2. « La réponse que tu as eue, tu en ferais quoi ? »

## 9. Le compte rendu

À rendre dans LEKA-450, une page par séance puis la synthèse :

1. **La personne** — son profil (sans nom), le chemin choisi (source ou démo).
2. **Les temps** — la sortie de la commande, et le temps total retenu.
3. **Le résultat** — réponse utile obtenue ou non, en combien de temps ;
   abandon, et à quelle étape.
4. **La grille** remplie.
5. **Les corrections**, classées par gravité :
   - **Bloquant** — empêche d'arriver à une réponse utile sans aide ;
   - **Majeur** — y arrive, au prix d'une erreur ou d'une longue hésitation ;
   - **Mineur** — une gêne, une formulation, un détail.
   Chaque correction cite la ligne de la grille et l'écran.
6. **Ce qui marche** — à ne pas casser.

Les corrections bloquantes et majeures deviennent des tickets de suite, créés
par Karim (règle de l'équipe), chacun lié à LEKA-450.

## 10. Le jour du test — liste de contrôle

- [ ] Recette de Karim faite et notée dans le ticket.
- [ ] Environnement vérifié la veille.
- [ ] Accord d'enregistrement signé.
- [ ] Adresse e-mail neuve prête, boîte accessible.
- [ ] Enregistrement de l'écran et de la voix lancé.
- [ ] Grille imprimée ou ouverte, chronomètre prêt.
- [ ] Consigne lue mot pour mot.
- [ ] Commande `leka.ops.first_answer` lancée après le test, sortie copiée.
