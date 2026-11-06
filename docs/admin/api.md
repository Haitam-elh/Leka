# L'Admin API de LEKA ADMIN (LEKA-544, LEKA-545, LEKA-546, LEKA-551, LEKA-552)

Le contrat entre LEKA CORE et LEKA ADMIN : ce que l'application Android envoie et reçoit aujourd'hui, et ce que la version web recevra demain, à l'identique. Les routes sont sous `/api/v1/admin`. Le schéma OpenAPI de LEKA CORE (`/api/v1/openapi.json`, étiquette `admin`) en est la source exacte ; ce document dit le sens.

Le code : `api/leka/admin/` (règles et lectures), `api/leka/api/admin.py` (routes). La décision d'architecture : [ADR 016](../adr/016-leka-admin.md).

## 1. Qui peut appeler

**L'équipe LEKA seulement, jamais un client.** Les comptes admin sont dans `admin_accounts`, à part des `users` des clients : être client de LEKA, même propriétaire d'une organisation, n'ouvre aucune route admin. Un cookie de session client est ignoré.

| Étape | Route | Ce qui se passe |
| --- | --- | --- |
| Se connecter | `POST /admin/auth/sign-in` `{email, password}` | Renvoie `token`, `expires_at`, `idle_minutes` et l'admin avec ses permissions. Le jeton n'est montré qu'une fois et gardé haché |
| Appeler | toute autre route | En-tête `Authorization: Bearer <token>` |
| Savoir qui on est | `GET /admin/me` | L'admin, son rôle, la liste de ses permissions |
| Se déconnecter | `POST /admin/auth/sign-out` | La session est révoquée (204) |
| Mot de passe oublié | `POST /admin/auth/forgot-password` `{email}` | Un code par e-mail, valable 15 minutes, si l'adresse est celle d'un admin actif. Toujours `202`, quelle que soit l'adresse |
| Choisir son mot de passe avec le code | `POST /admin/auth/reset-password` `{email, code, password}` | Pour le premier mot de passe d'un admin invité, ou après un oubli. Toutes ses sessions sont fermées (204) |
| Changer son mot de passe | `POST /admin/auth/change-password` `{current_password, password}` | Connecté ; ses autres sessions sont fermées |
| Renouveler sa session | `POST /admin/auth/renew` | Un nouveau jeton, l'ancien prend fin ; la session garde sa fin (LEKA-546) |
| Voir ses appareils connectés | `GET /admin/auth/sessions` | Ses sessions ouvertes : depuis quand, dernier appel, fin, appareil, réseau, et celle qui demande (`current`) |
| Fermer une de ses sessions | `DELETE /admin/auth/sessions/{id}` | Un autre de ses appareils, ou celui-ci (204) ; `404` si ce n'est pas une session ouverte à soi |

Règles de connexion :
- **Une seule réponse pour tout échec** : adresse inconnue, mauvais mot de passe, compte désactivé ou verrouillé répondent tous `401 invalid_credentials`, après le même travail. La vraie raison va dans le journal admin.
- **Verrou** : 5 mauvais mots de passe d'affilée verrouillent le compte 15 minutes.
- **Limite de débit** : 5 tentatives par minute par adresse, 20 par réseau.
- **Session** : elle finit après 12 heures quoi qu'il arrive, ou après 2 heures sans appel. Un compte désactivé perd ses sessions à l'instant.
- **Sur Android**, le jeton est chiffré par une clé du Keystore du téléphone, qui ne quitte jamais sa puce (LEKA-546) : jamais dans le code, l'APK, le stockage du navigateur intégré ni une sauvegarde.

**Le cycle d'une session** (LEKA-546) :
- **Renouveler** donne un nouveau jeton à l'appareil et met fin à l'ancien. La session garde la fin qu'elle avait : renouveler ne la fait jamais durer plus que la journée de travail pour laquelle elle a été ouverte. L'application renouvelle à son ouverture et quand elle revient au premier plan.
- **L'ancien jeton reste valable 30 secondes**, pour les appels partis avec lui ; il ne se renouvelle pas une seconde fois (`409`).
- **Présenté après ces 30 secondes**, c'est une copie, ou un appareil qui a perdu le nouveau : toutes les sessions de cet appareil (sa « famille », de la connexion à la fin) prennent fin, et le journal le dit (`admin.session_reused`). Les autres appareils de l'admin ne sont pas touchés.
- **Une session prend fin** et garde pourquoi (`ended_reason`) : déconnexion (`signed_out`), renouvellement (`renewed`), fermée depuis un autre de ses appareils (`ended_by_self`), par un Super Admin (`ended_by_admin`), mot de passe choisi ou changé (`password`), compte désactivé (`disabled`), jeton réutilisé (`reused`). Sinon elle expire : 12 heures, ou 2 heures sans appel.
- **Contre les essais répétés** : la limite de débit et le verrou ci-dessus pour la connexion ; 5 essais par code, 3 demandes de code par adresse en 15 minutes, 20 essais par réseau et par minute pour les codes.

**Les codes envoyés par e-mail** : 8 caractères (`ABCD-EFGH`), sans caractères ambigus, gardés hachés. Un code est à usage unique : il vaut 72 heures pour une invitation, 15 minutes pour un oubli, et il est brûlé après 5 essais faux. Un nouveau code remplace le précédent. Un code plutôt qu'un lien, parce que l'application est sur un téléphone. Le mot de passe fait 14 caractères au moins.

**L'équipe se gère depuis LEKA ADMIN** (LEKA-545), par un Super Admin : inviter, changer un rôle, désactiver, fermer des sessions (§ 4). La commande serveur reste disponible pour le tout premier compte et en secours :

```bash
python -m leka.admin.cli create prenom@leka-core.com --name "Prénom" --role super_admin
python -m leka.admin.cli list | role <email> <rôle> | disable <email> | enable <email> | password <email>
```

Avec la commande, le mot de passe se tape deux fois et jamais sur la ligne de commande. Chaque changement, d'où qu'il vienne, va dans le journal admin.

## 2. Rôles et permissions

Une route demande une **permission**, jamais un rôle. Ce que le rôle n'accorde pas est refusé côté serveur (`403 permission_denied`), et le refus est gardé dans le journal admin.

| Permission | Super Admin | Operations | Support | Finance |
| --- | :-: | :-: | :-: | :-: |
| `dashboard:read` tableau de bord | ✓ | ✓ | ✓ | ✓ |
| `organisations:read` organisations | ✓ | ✓ | ✓ | ✓ |
| `organisations:write` suspendre, réactiver ; changer son nom, son pays, sa taille (LEKA-549) | ✓ | ✓ | | |
| `organisations:notes` écrire une note interne (LEKA-549) | ✓ | ✓ | ✓ | ✓ |
| `users:read` personnes | ✓ | ✓ | ✓ | ✓ |
| `users:notes` écrire une note interne sur une personne (LEKA-550) | ✓ | ✓ | ✓ | ✓ |
| `intentions:read` intentions (métadonnées, titre) | ✓ | ✓ | ✓ | |
| `intentions:content` ce que le client a écrit, les livrables | ✓ | | ✓ | |
| `agents:read` agents et performance | ✓ | ✓ | ✓ | ✓ |
| `credits:read` crédits | ✓ | ✓ | ✓ | ✓ |
| `credits:write` ajouter des crédits | ✓ | | | ✓ |
| `billing:read` abonnements, événements Stripe | ✓ | | | ✓ |
| `environments:read` intégrations | ✓ | ✓ | ✓ | |
| `activity:read` journal d'activité | ✓ | ✓ | ✓ | ✓ |
| `audit:read` journal admin | ✓ | | | |
| `admins:manage` les admins (LEKA-545) | ✓ | | | |

C'est la matrice **de départ** (`api/leka/admin/access.py`, `ROLE_PERMISSIONS`). Depuis LEKA-545, le Super Admin modifie ce que chaque rôle peut faire (`PUT /admin/roles/{role}/permissions`), et le changement s'applique à la requête suivante de chaque admin, sans reconnexion. Il y a trois limites que personne ne lève :
- **le rôle Super Admin peut tout**, toujours ;
- **`admins:manage` et `audit:read` n'appartiennent qu'au Super Admin** : un rôle qui pourrait gérer les admins se donnerait lui-même tous les droits ;
- **personne ne change son propre rôle ni son propre accès**, et l'équipe garde toujours au moins un Super Admin actif.

Chaque permission a un **module** et un **niveau d'action** (`GET /admin/roles`) :
- `read` (lecture) ;
- `write` (écriture, aucune pour l'instant) ;
- `sensitive` (opération sensible) : ce qu'un client a écrit, l'accès d'une organisation, les crédits, le journal admin, les admins eux-mêmes.

## 3. Conventions

- **Listes** : `{"data": [...], "next_cursor": "..." | null}`. Paramètres `cursor` (opaque, signé), `limit` (50 par défaut, 200 au plus), `sort` (liste blanche par route, sinon `400 invalid_sort`), `order` (`asc` ou `desc`).
- **Un objet seul** : renvoyé tel quel, sans enveloppe.
- **Erreurs** : la forme unique de LEKA CORE, `{"error": {"code", "message", "details", "request_id"}}`. Brancher sur `code`.
- **Corrélation** : chaque réponse porte `X-Request-ID` ; il est gardé dans le journal admin, dans les journaux du serveur et, quand la source le garde, dans le journal d'activité.
- **Inconnu ≠ zéro** : un chiffre que LEKA n'a pas vaut `null`, jamais `0` (un coût sans tarif, le revenu avant LEKA-554, une durée encore en cours).
- **Démonstration** : les organisations de démonstration (LEKA-449) sont exclues des listes (sauf `include_demo=true`) et de tous les chiffres.
- **Dates** : ISO 8601 en UTC.

## 4. Les routes

| Méthode et chemin | Permission | Filtres et tri | Rend |
| --- | --- | --- | --- |
| `GET /admin/overview` | `dashboard:read` (les montants : `billing:read`) | `period` = `today`, `7d`, `30d` (défaut), `90d`, `12m`, `custom` avec `from` et `to` (2 ans au plus) | les chiffres du § 5 et leurs séries ([indicateurs.md](indicateurs.md)) |
| `GET /admin/organisations` | `organisations:read` | `q` (nom, slug, id, e-mail d'un propriétaire), `plan`, `status`, `created_from`, `created_to`, `country` (code ISO à deux lettres), `size` (celle que garde LEKA, sinon celle déclarée), `activity` (`active` : quelque chose dans les 30 derniers jours, `inactive` : avant seulement, `never` : jamais), `include_demo` ; tri `created_at`, `name` | une ligne par organisation : formule, propriétaire, pays, taille et taille déclarée, membres, intentions, dernière activité |
| `GET /admin/organisations/{id}` | `organisations:read` | | la fiche 360° : informations, formule et depuis quand, abonnement Stripe, crédits du mois, compteurs (dont analyses terminées et échouées, alertes ouvertes), agents utilisés. **Lecture journalisée** |
| `GET /admin/organisations/{id}/members` | `organisations:read` | | ses membres (rôle, depuis, dernière connexion) et ses invitations en attente |
| `GET /admin/organisations/{id}/credits` | `credits:read` | `since` (début du mois par défaut) | crédits du mois, consommation par agent et par modèle |
| `GET /admin/organisations/{id}/activity` | `activity:read` | `kind` | son journal d'activité |
| `POST /admin/organisations/{id}/suspend` | `organisations:write` | corps `{reason}`, en-tête `Idempotency-Key` | l'opération faite (§ 6) |
| `POST /admin/organisations/{id}/reactivate` | `organisations:write` | idem | idem |
| `POST /admin/organisations/{id}/credits` | `credits:write` | corps `{credits, reason}`, en-tête `Idempotency-Key` | l'opération et les crédits du mois après |
| `PATCH /admin/organisations/{id}` | `organisations:write` | corps `{name?, country?, size?, reason}` (un champ au moins), en-tête `Idempotency-Key` | l'opération et ce qui a changé, avant et après (LEKA-549) |
| `GET /admin/organisations/{id}/notes` | `organisations:read` | | ses notes internes, la plus récente d'abord : qui, quand, quoi |
| `POST /admin/organisations/{id}/notes` | `organisations:notes` | corps `{body}` (4 000 caractères au plus) | la note écrite. Jamais montrée au client ; le journal admin en garde la longueur, jamais le texte |
| `GET /admin/organisations/{id}/history` | `organisations:read` | | ce que l'équipe LEKA lui a fait : suspendue, réactivée, modifiée, crédits ajoutés, note écrite ; jamais ce qu'elle a lu |
| `GET /admin/organisations/{id}/incidents` | `environments:read` | `status` (`open`, `resolved`, `closed`) | les alertes sur son environnement (LEKA-442), la plus récente d'abord |
| `GET /admin/users` | `users:read` | `q` (e-mail, nom, id), `organisation_id` ou `organisation` (nom ou slug), `role` (`owner`, `admin`, `member` : dans cette organisation si elle est donnée), `verified`, `created_from`, `created_to`, `status` (§ 5), `active_from`, `active_to`, `never_active` (sa dernière intention, exécution ou source) ; tri `created_at`, `email` | une ligne par personne : organisations, leur état et ses rôles, intentions, statut, dernière activité, jours vus et actions sur 30 jours, niveau d'activité (§ 5) |
| `GET /admin/users/{id}` | `users:read` | | la fiche : profil déclaré, organisations, dans chacune son rôle et ce qu'il lui permet (le calcul de LEKA à chaque requête, rôle propre compris), exécutions, analyses terminées, agents utilisés, crédits consommés sur 30 jours, dernières connexions. **Lecture journalisée** |
| `GET /admin/users/{id}/notes`, `POST` | `users:read`, `users:notes` | corps `{body}` | ses notes internes (LEKA-550), jamais montrées à la personne |
| `GET /admin/invitations` | `users:read` | `q` (e-mail), `organisation_id`, `include_expired` | les personnes invitées pas encore entrées : organisation, rôle, envoi, expiration, si l'adresse a déjà un compte LEKA |
| `GET /admin/intentions` | `intentions:read` | `q` (son identifiant, ou des mots de son titre), `organisation_id` ou `organisation` (nom ou slug), `user_id` ou `user` (l'adresse ou le nom de qui l'a demandée), `status` (les 5 de LEKA ADMIN ou les 12 de LEKA), `kind`, `agent` (la clé d'un agent), `created_from`, `created_to` ; tri `created_at` | une ligne par intention : organisation, auteur, titre, type, statuts, agents, durée, crédits. `description` (son résumé, sinon le début de la demande, coupé à 200 caractères) seulement avec `intentions:content`, sinon `null` : **chaque page qui en rend est journalisée** en `admin.viewed_content`, avec les intentions lues |
| `GET /admin/intentions/{id}` | `intentions:read` | | la fiche d'une intention, étape par étape (§ 5) : sa chronologie, ses analyses, le choix de ses agents, ses exécutions et leurs étapes, ses décisions, plans et vérifications, ses erreurs, sa consommation. `content` (§ 5) seulement avec `intentions:content`, sinon `null`. **Lecture journalisée**, en `admin.viewed_content` quand le contenu est rendu. **Lecture seule** : aucune route du module n'agit sur l'environnement d'un client |
| `GET /admin/agents` | `agents:read` | `period` (`today`, `7d`, `30d`, `90d`, `12m`, ou `custom` avec `from` et `to` : chaque agent à côté de la période d'avant, aussi longue), ou `since` et `until` ; `organisation_id` ou `organisation` (nom ou slug), `user_id` (les exécutions qu'une personne a demandées), `agent`, `model`, `status` (d'une exécution), `lifecycle` (son état dans le registre), `unused` (les agents du registre qui n'ont pas tourné aussi) ; classement `sort` (`runs`, `organisations`, `success_rate`, `cost`, `duration`, `revenue`, `last_run`) et `order`, un chiffre inconnu toujours en dernier | une ligne par agent (§ 5) : nom, catégorie, version et état dans le registre, exécutions, organisations, réussites, échecs, taux de réussite, durée moyenne, appels, jetons, coût aux tarifs des fournisseurs et son état (`measured`, `partial`, `unavailable`), crédits, revenu quand il est vendu seul, achats seuls et en bundle, dernière exécution, `previous` |
| `GET /admin/agents/{key}` | `agents:read` | `period` (30 jours par défaut, `from`, `to`), `organisation_id` ou `organisation`, `model`, `status` | un agent sur une période : ses chiffres et ceux de la période d'avant, par jour (par mois au-delà de 92 jours), par modèle, par version, ses 20 organisations les plus utilisatrices, ses 20 échecs les plus fréquents, sa description, son mode, son risque, comment il est vendu (palier, prix seul, bundles, formule qui l'inclut) ; `404` pour une clé que LEKA ne connaît pas |
| `GET /admin/credits` | `credits:read` | `q`, `plan` ; tri `created_at`, `name` | les crédits du mois de chaque organisation |
| `GET /admin/subscriptions` | `billing:read` | `plan`, `status`, `interval` ; tri `updated_at`, `created_at` | les abonnements Stripe tels que LEKA les connaît |
| `GET /admin/billing/events` | `billing:read` | `type` (`*` joker), `outcome` (`applied`, `ignored`, `failed`), `organisation_id`, `received_from`, `received_to` ; tri `received_at` | chaque webhook Stripe reçu et ce qui en a été fait : les erreurs de synchronisation se voient ici |
| `GET /admin/sources` | `environments:read` | `organisation_id`, `kind`, `status`, `health`, `in_error` ; tri `created_at`, `name` | les intégrations : statut, santé, dernière erreur, dernière synchronisation. Jamais un secret |
| `GET /admin/activity` | `activity:read` | `kind` (`*` joker), `organisation_id`, `user_id`, `from`, `to` ; tri `at` | le journal d'activité (§ 7) |
| `GET /admin/admins` | `admins:manage` | | l'équipe : invités, actifs, désactivés, leurs sessions ouvertes |
| `POST /admin/admins` | `admins:manage` | corps `{email, name, role}` | l'admin invité (201) ; un e-mail lui porte son code |
| `PATCH /admin/admins/{id}` | `admins:manage` | corps `{name?, role?, status?}` (`active`, `disabled`) | l'admin changé. Le désactiver ferme ses sessions. Jamais son propre rôle ou accès, jamais le dernier Super Admin actif |
| `POST /admin/admins/{id}/invitation` | `admins:manage` | | un nouveau code à un admin encore invité |
| `POST /admin/admins/{id}/sign-out` | `admins:manage` | | toutes ses sessions fermées : `{sessions_ended}` |
| `GET /admin/roles` | connecté | | les 4 rôles, ce que chacun accorde, et chaque permission avec son module et son niveau |
| `PUT /admin/roles/{role}/permissions` | `admins:manage` | corps `{permissions}` (la liste entière) | le rôle changé ; refusé pour `super_admin` et pour ce qui n'appartient qu'au Super Admin |
| `GET /admin/audit` | `audit:read` | `admin_id`, `action` (`*` joker), `organisation_id`, `outcome`, `from`, `to` ; tri `at` | le journal admin (§ 8). **Lecture journalisée**, avec les filtres |

**Pas encore de données** (le ticket qui les apporte) : le registre des crédits (LEKA-553), l'historique des factures et des abonnements (LEKA-554), l'historique des incidents de la plateforme (LEKA-556).

**Le pays et la taille d'une organisation** (LEKA-549) : ce que l'équipe LEKA en garde (`country`, `size`), vide tant que personne ne les a donnés, jamais déduits de la région ou de la langue d'une personne. La taille que son premier propriétaire a déclarée à l'inscription est rendue à part (`size_declared`) : c'est la sienne, pas une donnée de l'organisation. Le filtre `size` lit la taille gardée, sinon la déclarée.

## 5. Les définitions

**Statuts d'une intention** (LEKA a 12 statuts, LEKA ADMIN en montre 5) :

| LEKA ADMIN | Statuts de LEKA |
| --- | --- |
| en attente (`pending`) | `submitted`, `needs_clarification`, `awaiting_decision` |
| en cours (`running`) | `analysing`, `approved`, `scheduled`, `executing`, `verifying` |
| terminée (`completed`) | `completed` |
| échouée (`failed`) | `failed` |
| annulée (`cancelled`) | `cancelled`, `rejected` |

La durée d'une intention va de sa création à son dernier changement de statut, quand ce statut est final ; `null` sinon.

**La fiche d'une intention** (LEKA-551, `api/leka/admin/intentions.py`). Chaque partie est lue là où LEKA la garde, jamais recopiée. Deux niveaux :

| Partie | Ce que tout rôle avec `intentions:read` voit | Ce que seul `intentions:content` voit (`content`) |
| --- | --- | --- |
| Demande initiale | le titre, le type, qui l'a demandée, quand | le texte, le résumé, le but, les fichiers joints (leurs noms) |
| Analyse et compréhension | chaque analyse : déclencheur, statut, état du contexte, durée, erreur ; les capacités choisies ou non et pourquoi (un code) ; ce que chacune a fait ; le risque et la confiance du résultat, le nombre de constats et de recommandations | la compréhension, et de chaque analyse : la réponse, le résumé, les constats, les causes, les recommandations, les incertitudes, ce qui manquait |
| Agents sollicités | chaque choix du routeur (`capability_routings`) : son issue, les agents retenus, les candidats et leur score, les exclus | |
| Étapes d'exécution | chaque exécution d'agent : statut, modèle, qui l'a lancée, durées, erreur, appels, jetons, crédits ; ses 200 premières étapes : leur type, l'outil, son issue, sa durée, le code d'un échec, le modèle et les jetons | jamais les arguments d'un outil, ce qu'il a lu ou ce que l'agent a écrit |
| Résultats et recommandations | | les livrables (coupés à 4 000 caractères), les résultats des analyses |
| Actions proposées | chaque décision : statut, risque, approbations demandées, votes (qui, quand, quoi) ; chaque action proposée : son type, réversible ou non, le nombre de cibles ; chaque plan et ses étapes ; chaque vérification | les cibles nommées et l'environnement de chaque action |
| Erreurs rencontrées | les erreurs techniques, la plus récente d'abord : d'une analyse et de ses capacités, d'une exécution et de ses étapes, d'un plan et de ses actions, et les refus des modèles, regroupés (le même refus cent fois est une ligne, avec son nombre) | |
| Durée et consommation IA | la durée ; depuis le registre de consommation (`usage_records`) : appels, appels échoués, nouvelles tentatives, jetons, coût aux tarifs de LEKA, crédits, modèles, et le détail par travail (chaque agent, chaque appel de LEKA) ; `null` quand rien n'est mesuré, jamais 0 | |
| Chronologie | du plus ancien au plus récent, les 1 000 derniers moments : ses changements de statut, ses analyses, le choix de ses agents, chaque mouvement de ses exécutions (mise en file, début, reprise, échec d'une étape, fin) avec l'identifiant de l'exécution, ses décisions et leurs votes, ses plans et leurs vérifications ; l'erreur technique de chaque moment | le motif qu'une personne a pu écrire (un vote, une annulation) |

Un moment de la chronologie dit sa catégorie (`intention`, `analysis`, `routing`, `run`, `decision`, `action`, `outcome`), son type, l'exécution à laquelle il appartient (`ref` : `run:<id>`, `analysis:<id>`, `routing:<id>`, `decision:<id>`, `plan:<id>`), l'agent concerné, le statut d'avant et d'après, qui (une personne ou LEKA) et l'erreur.

**Le module ne fait rien** : ni relancer, ni annuler, ni approuver. Aucune action dans l'environnement d'un client ne part de LEKA ADMIN ; `tests/test_admin_intentions.py` vérifie que le module n'a que des lectures.

**Les agents** (LEKA-552, `api/leka/admin/agents.py`). Chaque agent est identifié par sa clé, et lu là où LEKA le garde :

- **la liste des agents** : le registre (`agents/registry.yaml` et le `SKILL.md` de chacun). Avec `unused`, un agent qui n'a jamais tourné est listé avec 0 exécution. Un agent retiré du registre reste listé tant qu'il a des exécutions, sans nom ni état ;
- **ce qu'ils ont fait** : `agent_runs`, une ligne par exécution. Le taux de réussite se calcule sur les exécutions terminées (réussies et échouées) ; `null` quand aucune n'est terminée ;
- **ce que leurs exécutions ont consommé et coûté** : le registre de consommation (`usage_records`), une ligne par exécution, au tarif des fournisseurs en vigueur (`model_rates`). Le coût dit son état :

| `cost_status` | Ce que ça veut dire | `cost_usd` |
| --- | --- | --- |
| `measured` | chaque exécution est chiffrée (ou n'a appelé aucun modèle) | leur somme, 0 si aucun appel |
| `partial` | certaines exécutions ne sont pas chiffrées (`unpriced_runs`) : un appel sans tarif connu, ou une exécution pas encore comptée | la somme de celles qui le sont |
| `unavailable` | aucune n'est chiffrée | `null`, jamais 0 |
| `none` | aucune exécution | `null` |

- **les crédits** : ce que ses exécutions ont pris aux crédits IA des clients, au coût de LEKA (les appels payés par le modèle propre d'un client n'en prennent pas) ;
- **le revenu** (`revenue_eur`) : seulement quand il est traçable, c'est-à-dire pour un agent acheté seul (`agent_entitlements`, achat actif). C'est le revenu mensuel récurrent de ces achats, tel que Stripe l'a dit (LEKA-548), coupons déduits, hors TVA. Il vaut `null` si l'agent n'est pas acheté seul, ou si l'un de ses achats n'a pas de prix connu en euros. Le revenu d'un bundle n'est jamais réparti entre ses agents : `bundle_purchases` compte seulement les bundles achetés qui le contiennent. Le revenu se lit à l'instant présent ; seul le filtre d'organisation s'y applique ;
- **la comparaison** : avec une période (`period`), chaque agent porte les mêmes chiffres sur la période d'avant, aussi longue (`previous`).

Les agents de la liste indicative du ticket qui n'existent pas dans LEKA (Lead, Growth, Product, Research, Finance) ne sont pas inventés : le module montre les agents réels.

**Statut d'une personne**, fondé sur ce qu'elle a fait, pas sur une simple connexion :

| Statut | Règle, dans l'ordre |
| --- | --- |
| `suspended` | membre d'au moins une organisation, et aucune des siennes n'est active (toutes suspendues ou en suppression) |
| `unverified` | adresse jamais confirmée |
| `new` | inscrite depuis moins de 7 jours |
| `active` | une intention créée, une exécution d'agent ou une source connectée dans les 30 derniers jours |
| `inactive` | sinon |

**Invitée** : une personne invitée sans compte n'est pas encore une personne de LEKA ; elle est dans `GET /admin/invitations` tant qu'elle n'a pas accepté (une invitation expirée n'y est que sur demande). LEKA CORE n'a pas de suspension propre à un compte : une personne est suspendue par ses organisations.

**Niveau d'activité** (LEKA-550), sur les 30 derniers jours, à partir de deux chiffres rendus à côté de lui : les **jours vus** (une session utilisée ce jour-là, `user.active`, une fois par jour) et les **actions** (intentions créées, exécutions d'agents, sources connectées). Une connexion seule n'est ni un jour vu ni une action.

| Niveau | Règle |
| --- | --- |
| `high` | 20 actions ou plus, ou 12 jours vus ou plus |
| `medium` | 5 actions ou plus, ou 4 jours vus ou plus |
| `low` | au moins une action, ou au moins un jour vu |
| `none` | rien |

**Le tableau de bord** (`GET /admin/overview`), sur la période demandée, hors démonstration : chaque indicateur, sa règle de calcul et ce qu'il dit quand il ne sait pas sont dans [indicateurs.md](indicateurs.md) (LEKA-548). En bref :

| Bloc | Ce qu'il dit |
| --- | --- |
| `acquisition` | organisations et personnes, toutes et nouvelles ; par formule, Free et payantes |
| `activity` | DAU, WAU, MAU ; organisations actives ; intentions lancées, terminées, échouées, leur taux de réussite ; analyses terminées, échouées |
| `product` | exécutions d'agents, leur taux de réussite, l'adoption, les cinq agents les plus lancés ; crédits consommés |
| `business` | MRR et ARR maintenant (hors taxes), l'encaissé de la période (taxes comprises) et le remboursé, jamais confondus ; abonnements, churn, paiements échoués |
| `costs` | ce que les modèles de LEKA ont coûté à LEKA dans la période |
| `technical` | incidents qui sonnent maintenant ; intégrations en erreur ; synchronisations et tâches échouées |
| `intelligence` | activation, Time to First Value, conversion Free vers payant des organisations créées dans la période ; rétention mensuelle par mois d'inscription |
| `recent` | les derniers événements : inscriptions, organisations, abonnements, paiements échoués, intentions |
| `series` | un point par jour (par mois au-delà de 92 jours) : organisations et personnes au total, inscriptions, actifs, intentions, crédits, MRR |

Les montants (`mrr`, `arr`, `collected`, `collected_tax`, `refunded`, `costs.ai_usd`, la série `mrr`) ne sont rendus qu'à un rôle qui lit la facturation (`billing:read`) ; sinon ils valent `null` et `amounts_granted` vaut `false`.

## 6. Les opérations sensibles

Suspendre, réactiver, ajouter des crédits : chacune appelle la règle du module qui la possède (`WorkspaceService.suspend` et `reactivate`, `add_pack`) et ne la réécrit pas.

- **Motif obligatoire** (`reason`, 3 à 300 caractères).
- **`Idempotency-Key` obligatoire** (8 à 100 caractères ; un UUID convient). La même requête renvoyée rend la même réponse avec `"replayed": true` et ne refait rien. La même clé avec une autre requête répond `409 conflict`. Les clés sont gardées 7 jours.
- **Gardée deux fois** : dans le journal d'audit de l'organisation, en « fait par LEKA » et sans le motif interne ; dans le journal admin, avec l'admin, le motif, la route, l'identifiant de requête et le préfixe d'adresse.
- **Une organisation dont le client a demandé la suppression est laissée telle quelle** (`409`) : la réactiver annulerait sa demande.

## 7. Le journal d'activité et les événements instrumentés

`activity_events` répond au besoin d'historisation de LEKA-544 sans toucher aux modules qui écrivent les données. Toutes les 5 minutes, une tâche (`admin-activity`) lit dans chaque table ce qui s'est passé depuis son dernier passage, et écrit **un fait une seule fois** grâce à sa clé de dédoublonnage. Relire ne crée jamais de doublon. Le premier passage lit tout l'historique existant.

| Événement du ticket | Type dans le journal | Lu dans |
| --- | --- | --- |
| inscription | `user.signed_up` | `users` |
| connexion | `user.signed_in` ; présence du jour `user.active` | `sessions` (avant leur purge) |
| création d'organisation | `workspace.created` ; `member.joined` | `workspaces`, `memberships` |
| abonnements | `subscription.started`, `.changed`, `.canceled` | `stripe_events` |
| paiements | `payment.succeeded`, `payment.failed`, `refund.issued` | `stripe_events` |
| intentions | `intention.created`, `.completed`, `.failed`, `.cancelled` | `intentions`, `intention_events` |
| exécutions d'agents | `agent_run.succeeded`, `agent_run.failed` (agent, modèle, durée) | `agent_runs` |
| consommation de crédits | `credits.consumed` (crédits, statut du coût), mis à jour si l'exécution est mesurée à nouveau | `usage_records` |
| intégrations | `source.connected`, `sync.failed` | `sources`, `sync_runs` |

**Métadonnées minimales et non sensibles** : le type, l'organisation, la personne, le moment, la ligne d'origine (`ref`), l'identifiant de requête quand la source le garde, et quelques chiffres. Jamais ce qu'une personne a écrit, ni une adresse IP, ni un navigateur. Le journal est gardé 25 mois. Quand une personne ou une organisation est supprimée, ses faits restent sans elle (`SET NULL`).

## 8. Le journal admin

`admin_audit_events` garde tout ce que l'équipe LEKA fait et lit de sensible à travers LEKA ADMIN. Il est à part du journal des clients et de sa rétention.

**Ce qu'une ligne dit** (LEKA-546) :

| Champ | Ce qu'il dit |
| --- | --- |
| `admin_id`, `admin_email` | l'acteur : l'admin, ou l'adresse tapée quand aucun compte ne correspond (connexion refusée) ; rien pour la tâche de nuit |
| `action` | ce qui a été fait, l'une des actions ci-dessous et aucune autre : une action que le code n'a pas déclarée est refusée |
| `target_type`, `target_id` | l'objet : une organisation, une personne, une intention, un admin, une session, un rôle |
| `for_workspace_id` | l'organisation concernée, quand il y en a une |
| `at` | l'horodatage |
| `outcome` | le résultat : `succeeded`, `refused` ou `failed` |
| `route`, `request_id` | la requête : la méthode et le chemin, et son identifiant, le même que dans les logs |
| `session_id` | la session de l'admin, donc l'appareil |
| `ip_prefix` | le réseau d'où c'est venu, jamais l'adresse entière (/24 en IPv4, /48 en IPv6) |
| `detail` | un petit contexte utile : le motif, avant et après, les filtres d'une lecture, la raison d'un refus. Jamais les données lues |

**Les actions** (`api/leka/admin/audit.py`, `ACTIONS`) :

| Domaine | Actions |
| --- | --- |
| Connexion et sessions | `admin.signed_in`, `admin.sign_in_failed` (avec sa raison), `admin.signed_out`, `admin.session_renewed`, `admin.session_ended`, `admin.session_reused`, `admin.signed_out_everywhere` |
| Mots de passe et codes | `admin.password_reset_asked`, `admin.code_refused`, `admin.password_set`, `admin.password_changed`, `admin.password_change_refused` |
| Lectures | `admin.refused` (un rôle qui n'accorde pas), `admin.viewed` (une organisation, une personne, une intention), `admin.viewed_content` (ce que le client a écrit, les livrables ; pour une page d'intentions avec leur description, les intentions lues), `admin.viewed_trail` (ce journal) |
| Clients, crédits | `admin.organisation_suspended`, `admin.organisation_reactivated`, `admin.credits_added`, `admin.organisation_updated` (LEKA-549 : avec ce qui a changé, avant et après), chacune avec son motif ; `admin.note_added` (une note interne : sa longueur, jamais son texte) |
| L'équipe, les rôles, les permissions | `admin.account_created`, `admin.invited`, `admin.invitation_sent`, `admin.account_changed` (nom, rôle, accès : avant et après), `admin.role_changed` (les permissions d'un rôle : avant et après) |
| Le journal lui-même | `admin.trail_expired` (ce que la tâche de nuit a supprimé), `admin.trail_unprotected` (sa protection trouvée absente) |

Les abonnements ne changent aujourd'hui que par Stripe, côté client : ils sont dans le journal d'activité (§ 7). Quand LEKA ADMIN pourra les changer (LEKA-554), et quand il exportera (LEKA-557), chaque opération ajoutera son action ici, dans `ACTIONS` et dans ce tableau. `tests/test_admin_security.py` refuse une action enregistrée par le code qui manque à l'un ou à l'autre.

**Protégé contre la modification** :
- **Aucune route** n'écrit dans ce journal autrement qu'en ajoutant une ligne, ni ne le modifie ni ne le supprime.
- **La base refuse** de réécrire une ligne, de la supprimer et de vider la table (déclencheurs). Deux exceptions seulement : oublier qui une ligne concernait quand l'admin ou l'organisation est supprimé ; la tâche de nuit qui supprime ce qui a dépassé la conservation, et jamais une ligne de moins de six mois, quoi que dise le réglage.
- **Chaque nuit**, la tâche vérifie que ces déclencheurs sont là et actifs. S'il en manque un, elle le dit en erreur dans les logs et dans le journal (`admin.trail_unprotected`), et ne supprime rien.
- **Limite connue** : quelqu'un qui a les accès du propriétaire de la base sur le serveur peut retirer un déclencheur. C'est un accès au serveur, pas à LEKA ADMIN ; la vérification de chaque nuit le rend visible. Séparer le rôle de base de l'API de celui des migrations est un sujet de l'audit de sécurité (LEKA-558).

**Accès** : seul un Super Admin le lit (`audit:read`, qu'aucun autre rôle ne peut recevoir), depuis LEKA ADMIN ou l'API, et chaque lecture est elle-même gardée (`admin.viewed_trail`, avec les filtres). Personne ne le modifie.

**Conservation** :

| Quoi | Gardé | Puis |
| --- | --- | --- |
| Le journal admin | 1 an (`LEKA_ADMIN_AUDIT_RETENTION_DAYS`, de 180 jours à 7 ans) | supprimé par la tâche `admin-retention` (chaque nuit à 04:25 UTC), qui le dit dans le journal |
| Les sessions terminées | 30 jours après leur fin | supprimées ; le journal garde quelle session a fait quoi |
| Les codes utilisés ou expirés | 7 jours | supprimés |
| Le journal d'activité, les clés d'idempotence | 25 mois, 7 jours | § 6 et 7 |
