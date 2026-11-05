# L'Admin API de LEKA ADMIN (LEKA-544)

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

Règles de connexion :
- **Une seule réponse pour tout échec** : adresse inconnue, mauvais mot de passe, compte désactivé ou verrouillé répondent tous `401 invalid_credentials`, après le même travail. La vraie raison va dans le journal admin.
- **Verrou** : 5 mauvais mots de passe d'affilée verrouillent le compte 15 minutes.
- **Limite de débit** : 5 tentatives par minute par adresse, 20 par réseau.
- **Session** : elle finit après 12 heures quoi qu'il arrive, ou après 2 heures sans appel. Un compte désactivé perd ses sessions à l'instant.
- **Sur Android**, le jeton est gardé dans le stockage sécurisé du téléphone (LEKA-546), jamais dans le code ni dans l'APK.

Les comptes se créent depuis le serveur, jusqu'à ce que LEKA-545 permette au Super Admin de le faire dans LEKA ADMIN :

```bash
python -m leka.admin.cli create prenom@leka-core.com --name "Prénom" --role super_admin
python -m leka.admin.cli list | role <email> <rôle> | disable <email> | enable <email> | password <email>
```

Le mot de passe se tape deux fois, 14 caractères au moins, jamais sur la ligne de commande. Chaque changement va dans le journal admin.

## 2. Rôles et permissions

Une route demande une **permission**, jamais un rôle. Ce que le rôle n'accorde pas est refusé côté serveur (`403 permission_denied`), et le refus est gardé dans le journal admin.

| Permission | Super Admin | Operations | Support | Finance |
| --- | :-: | :-: | :-: | :-: |
| `dashboard:read` tableau de bord | ✓ | ✓ | ✓ | ✓ |
| `organisations:read` organisations | ✓ | ✓ | ✓ | ✓ |
| `organisations:write` suspendre, réactiver | ✓ | ✓ | | |
| `users:read` personnes | ✓ | ✓ | ✓ | ✓ |
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

La matrice est dans `api/leka/admin/access.py`. LEKA-545 la rendra modifiable par le Super Admin.

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
| `GET /admin/overview` | `dashboard:read` | `period` = `today`, `7d`, `30d` (défaut), `90d`, `12m`, `custom` avec `from` et `to` (2 ans au plus) | les chiffres du § 5 et leurs séries |
| `GET /admin/organisations` | `organisations:read` | `q` (nom, slug, id, e-mail d'un propriétaire), `plan`, `status`, `created_from`, `created_to`, `include_demo` ; tri `created_at`, `name` | une ligne par organisation : formule, propriétaire, membres, intentions, dernière activité |
| `GET /admin/organisations/{id}` | `organisations:read` | | la fiche 360° : informations, formule et depuis quand, abonnement Stripe, crédits du mois, compteurs, agents utilisés. **Lecture journalisée** |
| `GET /admin/organisations/{id}/members` | `organisations:read` | | ses membres (rôle, depuis, dernière connexion) et ses invitations en attente |
| `GET /admin/organisations/{id}/credits` | `credits:read` | `since` (début du mois par défaut) | crédits du mois, consommation par agent et par modèle |
| `GET /admin/organisations/{id}/activity` | `activity:read` | `kind` | son journal d'activité |
| `POST /admin/organisations/{id}/suspend` | `organisations:write` | corps `{reason}`, en-tête `Idempotency-Key` | l'opération faite (§ 6) |
| `POST /admin/organisations/{id}/reactivate` | `organisations:write` | idem | idem |
| `POST /admin/organisations/{id}/credits` | `credits:write` | corps `{credits, reason}`, en-tête `Idempotency-Key` | l'opération et les crédits du mois après |
| `GET /admin/users` | `users:read` | `q` (e-mail, nom, id), `organisation_id`, `verified`, `created_from`, `created_to` ; tri `created_at`, `email` | une ligne par personne : organisations et rôles, intentions, statut (§ 5) |
| `GET /admin/users/{id}` | `users:read` | | la fiche : profil déclaré, organisations, exécutions, crédits consommés sur 30 jours, dernières connexions. **Lecture journalisée** |
| `GET /admin/intentions` | `intentions:read` | `organisation_id`, `user_id`, `status` (les 5 de LEKA ADMIN ou les 12 de LEKA), `kind`, `agent`, `created_from`, `created_to` ; tri `created_at` | une ligne par intention : organisation, auteur, titre, statuts, agents, durée, crédits |
| `GET /admin/intentions/{id}` | `intentions:read` | | sa chronologie, ses exécutions et leurs erreurs, analyses, décisions. `content` (texte, résumé, but, compréhension, livrables coupés à 4 000 caractères) seulement avec `intentions:content`, sinon `null`. **Lecture journalisée**, en `admin.viewed_content` quand le contenu est rendu |
| `GET /admin/agents` | `agents:read` | `since`, `until`, `organisation_id`, `agent`, `model` | une ligne par agent : exécutions, organisations, réussites, échecs, taux de réussite, durée moyenne, coût et crédits |
| `GET /admin/credits` | `credits:read` | `q`, `plan` ; tri `created_at`, `name` | les crédits du mois de chaque organisation |
| `GET /admin/subscriptions` | `billing:read` | `plan`, `status`, `interval` ; tri `updated_at`, `created_at` | les abonnements Stripe tels que LEKA les connaît |
| `GET /admin/billing/events` | `billing:read` | `type` (`*` joker), `outcome` (`applied`, `ignored`, `failed`), `organisation_id`, `received_from`, `received_to` ; tri `received_at` | chaque webhook Stripe reçu et ce qui en a été fait : les erreurs de synchronisation se voient ici |
| `GET /admin/sources` | `environments:read` | `organisation_id`, `kind`, `status`, `health`, `in_error` ; tri `created_at`, `name` | les intégrations : statut, santé, dernière erreur, dernière synchronisation. Jamais un secret |
| `GET /admin/activity` | `activity:read` | `kind` (`*` joker), `organisation_id`, `user_id`, `from`, `to` ; tri `at` | le journal d'activité (§ 7) |
| `GET /admin/audit` | `audit:read` | `admin_id`, `action` (`*` joker), `organisation_id`, `outcome`, `from`, `to` ; tri `at` | le journal admin |

**Pas encore de données** (le ticket qui les apporte) : le pays d'une organisation (pas collecté), les notes internes (LEKA-549), le registre des crédits (LEKA-553), les factures, paiements et MRR (LEKA-554), les incidents de la plateforme (LEKA-556).

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

**Statut d'une personne**, fondé sur ce qu'elle a fait, pas sur une simple connexion :

| Statut | Règle, dans l'ordre |
| --- | --- |
| `unverified` | adresse jamais confirmée |
| `new` | inscrite depuis moins de 7 jours |
| `active` | une intention créée, une exécution d'agent ou une source connectée dans les 30 derniers jours |
| `inactive` | sinon |

Une personne invitée sans compte apparaît dans les invitations de l'organisation. Un compte suspendu n'existe pas encore dans LEKA CORE.

**Le tableau de bord** (`GET /admin/overview`), sur la période demandée, hors démonstration :

| Bloc | Chiffre | Définition |
| --- | --- | --- |
| Acquisition | `organisations`, `organisations_new` | toutes ; créées dans la période |
| | `users`, `users_new` | toutes les personnes ; inscrites dans la période |
| | `by_plan` | les organisations par formule actuelle (la dernière attribuée, Free sinon) |
| Activité | `dau`, `wau`, `mau` | personnes vues dans le produit aujourd'hui (UTC), sur 7 jours, sur 30 jours (`user.active`) |
| | `intentions_created`, `_completed`, `_failed` | dans la période |
| Produit | `agent_runs`, `agent_success_rate` | exécutions lancées dans la période ; réussies sur terminées (`null` si aucune) |
| | `agents_used`, `organisations_running_agents` | agents distincts ; organisations qui en ont lancé un |
| | `credits_consumed` | coût LEKA des modèles ÷ prix du crédit ; `null` si aucun coût mesuré |
| Business | `subscriptions_started`, `subscriptions_canceled`, `payments_failed` | événements Stripe reçus dans la période |
| | `paying_organisations` | abonnement Stripe qui garde sa formule maintenant : `active`, `trialing`, `past_due` |
| | `mrr`, `arr` | `null` jusqu'à LEKA-554 : LEKA ne garde pas encore les montants facturés |
| Technique | `sources_in_error` | maintenant : statut `error` ou santé `unhealthy` |
| | `sync_failures`, `jobs_failed` | dans la période |
| Séries | `users_new`, `users_active`, `intentions_created`, `credits_consumed` | par jour jusqu'à 92 jours de période, par mois au-delà |

Revenus récurrents, facturation et encaissements ne sont jamais confondus : aujourd'hui, aucun montant n'est montré.

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

`admin_audit_events` garde tout ce que l'équipe LEKA fait et lit de sensible :
- `admin.signed_in`, `admin.signed_out`, `admin.sign_in_failed` avec sa raison ;
- `admin.refused` ;
- `admin.viewed` et `admin.viewed_content` ;
- `admin.organisation_suspended` et `_reactivated`, `admin.credits_added` ;
- `admin.account_created` et `admin.account_changed`.

La base refuse de modifier une ligne (déclencheur), sauf pour oublier qui elle concernait quand l'admin ou l'organisation est supprimé. Il est indépendant de la rétention des journaux clients. Sa durée de conservation et ses accès sont précisés par LEKA-546.
