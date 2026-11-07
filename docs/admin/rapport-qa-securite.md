# Rapport QA et sécurité de LEKA ADMIN (LEKA-558)

Établi le 7 novembre 2026, sur LEKA CORE `feature/LEKA-558-qa-security` (posé sur LEKA-557) et LEKA ADMIN `feature/LEKA-558-qa-security`. Il couvre LEKA ADMIN de bout en bout : l'Admin API de LEKA CORE, l'application Android et ce qui les relie.

## Verdict

**LEKA ADMIN peut être livré.**
- Aucun défaut bloquant de sécurité ou d'isolation n'est ouvert. Les balayages de sécurité ajoutés par ce ticket (chaque route pour chaque rôle, chaque réponse lue pour y chercher un secret, chaque fiche lue pour y chercher une autre organisation) n'ont trouvé aucune fuite.
- Deux anomalies importantes ont été trouvées et corrigées :
  - côté client, une page qui tombait en erreur 500 ;
  - côté admin, une liste qui faisait une requête par ligne.
- Il reste des points mineurs, listés plus bas, aucun bloquant.

| | Résultat |
| --- | --- |
| Tests de l'API (LEKA CORE) | 4 662 réussis, 0 échec, dont 9 nouveaux tests de balayage (`api/tests/test_admin_qa.py`) |
| Tests de l'application (LEKA ADMIN) | 256 réussis (vitest) |
| Parcours de bout en bout (navigateur) | 17 réussis, stables sur 51 exécutions répétées |
| Parcours Android (émulateur, Android 16) | 22 étapes réussies sur 22 |
| Secrets dans l'APK | aucun (`npm run check:secrets`, APK de debug du 7 novembre) |
| Anomalies trouvées | 2 importantes (corrigées), 1 mineure (corrigée), 1 mineure ouverte |

## 1. Tests fonctionnels

Chaque module est testé à trois niveaux :
- l'Admin API : ce que LEKA CORE rend, ses filtres, ses refus ;
- l'écran : ce qu'il montre de ces réponses ;
- le parcours : dans un vrai navigateur, et sur Android pour les parcours critiques.

| Module | API (LEKA CORE) | Écrans (LEKA ADMIN) | Parcours |
| --- | --- | --- | --- |
| Authentification | `test_admin_access`, `test_admin_team`, `test_admin_security` | `session.test`, `ports.test` | navigateur : connexion, refus, session fermée ailleurs, déconnexion ; Android : connexion, mot de passe refusé, reprise, déconnexion |
| Navigation | toutes les routes balayées | `navigation.test` | navigateur : chaque onglet, chaque module, chaque fiche, un rôle limité ; Android : chaque module, le bouton retour |
| Tableau de bord | `test_admin_figures`, `test_admin_api` | `dashboard.test` | navigateur et Android |
| Organisations | `test_admin_organisations`, cohérence liste et fiche | `clients.test`, `clients/record.test` | navigateur et Android |
| Utilisateurs | `test_admin_users`, cohérence liste et fiche | `users.test`, `users/person.test` | navigateur et Android |
| Intentions | `test_admin_intentions` | `intentions.test`, `intentions/record.test` | navigateur et Android |
| Agents | `test_admin_agents` | `agents.test`, `agents/record.test` | navigateur et Android |
| Crédits | `test_admin_credits`, `test_credit_ledger`, cohérence liste, fiche et page client | `credits.test`, `credits/ledger.test` | navigateur et Android |
| Stripe, facturation | `test_admin_billing`, `test_billing_history`, `test_billing_stripe` | `billing/billing.test` | navigateur et Android |
| Environnements | `test_admin_environments` | `environments/environment.test` | navigateur et Android |
| Monitoring | `test_admin_incidents` | `monitoring/monitoring.test` | navigateur et Android |
| Recherche et exports | `test_admin_search_exports` | `search.test`, `shell/export.test`, `exports.test` | navigateur : une recherche, un export téléchargé et relu |

**Les données affichées sont cohérentes**. Un test le vérifie (`test_what_a_list_says_its_record_says_and_the_customer_sees`) : une même organisation, lue dans sa liste, dans sa fiche et par la page Facturation du client, dit la même formule, les mêmes membres, les mêmes intentions et les mêmes crédits. Les indicateurs du tableau de bord ont leurs propres tests de calcul (`docs/admin/indicateurs.md`).

## 2. Tests techniques

| Niveau | Ce qui le couvre |
| --- | --- |
| Unitaires | vitest dans LEKA ADMIN (256), pytest dans LEKA CORE |
| Intégration de l'API | pytest contre PostgreSQL et Redis réels, en quatre parties en parallèle |
| Contrats de l'API | Les types de LEKA ADMIN sont générés depuis l'OpenAPI de LEKA CORE (`npm run gen:api`). Chaque réponse est validée par un schéma zod avant d'être affichée. Les réponses servies aux tests de bout en bout sont des réponses réelles de LEKA CORE, enregistrées, et un test les tient aux schémas de l'appli (`tests/e2e-fixtures.test.ts`). Côté LEKA CORE, deux contrats ne portent jamais le même nom (`test_no_two_contracts_share_a_name`), et chaque route admin est documentée (`test_every_route_is_documented`) |
| Bout en bout | Playwright, Chromium au format d'un téléphone : 17 parcours (`e2e/*.spec.ts`), joués par la CI de LEKA ADMIN à chaque pull request |
| Non-régression | Les suites entières à chaque pull request, des deux côtés. Les balayages de ce ticket couvrent d'eux-mêmes une route ajoutée demain |
| Performance | voir § 4 |
| Erreurs et chargement | Navigateur : une liste lente montre son chargement ; une erreur 500 montre l'identifiant de la requête, et « Réessayer » relit ; le réseau coupé est dit (« LEKA CORE ne répond pas »), puis la liste revient. Android : mode avion, puis retour du réseau |

## 3. Audit de sécurité

| Exigence | Ce qui a été vérifié | Preuve |
| --- | --- | --- |
| Endpoints et RBAC | Les 78 routes de l'Admin API demandent chacune une permission, sauf les 11 qui sont propres à l'admin (se connecter, ses sessions, qui il est, les rôles, la recherche, dont chaque partie demande sa propre permission). Chaque rôle (Opérations, Support, Finance) est refusé (`403`) **exactement** sur ce qu'il n'a pas : ni plus, ni moins | `test_every_route_asks_a_permission_but_the_admins_own`, `test_each_role_is_refused_exactly_what_it_does_not_grant` |
| Accès non autorisés | Sans jeton, avec un faux jeton ou un autre schéma, chaque route admin répond `401`. Une session client, même propriétaire, n'ouvre aucune route admin. Chaque refus de rôle est inscrit au journal admin, avec la permission manquante | `test_every_admin_route_but_the_public_three_wants_an_admin_token`, `test_a_customer_owner_session_opens_no_admin_route`, balayage RBAC |
| Isolation multi-tenant | Entre clients : chaque route lisible appelée par un client ne montre rien d'un autre, et la base refuse une ligne croisée (`test_tenant_isolation`). Dans LEKA ADMIN, chaque fiche d'une organisation, d'une personne ou d'une intention ne dit rien d'une autre organisation. De l'équipe vers le client : une note interne, un incident ou l'adresse d'un admin n'apparaissent dans aucune route client | `test_no_route_leaks_another_workspace`, `test_what_is_read_about_an_organisation_says_nothing_of_another`, `test_what_leka_s_team_keeps_never_reaches_a_customer` |
| Données sensibles | Chaque route GET et chaque export est lu par chaque rôle. On y cherche les empreintes des mots de passe, les jetons et empreintes de session, les réglages d'une source et un jeton glissé dans son erreur : aucune réponse n'en contient (le jeton est masqué). Ce qu'un client a écrit n'apparaît que pour un rôle qui a `intentions:content`. Un export n'a jamais de mot de passe, de session, d'adresse IP, de date de connexion, de lien de paiement Stripe ni de texte client | `test_no_answer_says_a_secret_nor_what_a_customer_wrote_to_whom_may_not`, `test_an_export_carries_no_secret_nor_connection` |
| Secrets dans l'APK | `npm run check:secrets` lit chaque fichier de l'APK construit (code compilé et ressources, en UTF-8 et en UTF-16) : rien trouvé. L'APK ne demande que la permission `INTERNET`. Le débogage de la WebView n'est ouvert qu'aux builds de debug | `tests/no-secrets.test.ts`, `tests/android-security.test.ts`, parcours Android |
| Sessions | Jeton gardé haché côté serveur, chiffré par le Keystore sur le téléphone. Renouvellement avec un délai de grâce de 30 secondes ; un jeton réutilisé après ce délai ferme toutes les sessions de l'appareil. Verrou après 5 mauvais mots de passe, limite de débit. Un admin désactivé perd ses sessions. Changer son mot de passe ferme les autres sessions | `test_admin_security`, `test_admin_access`, `test_admin_team` ; Android : reprise après fermeture forcée sans reconnexion, et rien de gardé après déconnexion |
| Actions privilégiées | Suspendre, réactiver, modifier une organisation, ajouter ou ajuster des crédits : une clé d'idempotence (envoyée deux fois, fait une fois), un motif, une ligne au journal. Personne ne change son propre rôle ni son accès, et il reste toujours un Super Admin actif | `test_admin_organisations`, `test_admin_credits`, `test_admin_team` |
| Journal admin | Il est en ajout seul : des déclencheurs refusent toute réécriture, suppression ou vidage, et sont vérifiés chaque nuit. Chaque action enregistrée est dans le catalogue et dans la documentation. Lire le journal est soi-même journalisé, comme chaque refus et chaque export | `test_admin_security`, balayage RBAC, `test_an_export_wants_two_permissions_and_is_kept` |

## 4. Performance

**Pas de requête par ligne.** Chaque liste paginée de l'Admin API (26) est lue avec une page d'une ligne, puis de trois. Le nombre de requêtes à la base doit rester le même : c'est `test_a_page_is_read_in_the_same_queries_whatever_its_size`. Il est vérifié à chaque CI, avec un budget de 2 secondes par page.

Ce test a trouvé que la liste des crédits par organisation (`GET /admin/credits`) faisait 5 requêtes par organisation : 8 requêtes pour une ligne, 18 pour trois, et environ 250 pour une page de 50. Corrigé : les crédits d'une page sont lus en une fois, avec le même calcul (`credits_now_many`). Un test vérifie que les chiffres sont identiques à ceux lus organisation par organisation.

**Temps de réponse**, mesurés contre un LEKA CORE local sur une base de démonstration (médiane de 5 appels) :
- le tableau de bord, 39 ms ;
- la recherche globale, 24 ms ;
- la fiche d'une intention, 19 ms ;
- la fiche d'une organisation, 17 ms ;
- toutes les autres lectures des écrans, entre 6 et 12 ms.

Ces chiffres valent pour une petite base. En production, la base (RDS de petite taille) est plus lente. C'est la garde du nombre constant de requêtes qui protège la montée en charge.

**Sur Android** (émulateur, Android 16) :
- démarrage à froid jusqu'à l'écran de connexion, environ 1 seconde ;
- une liste relue sur un réseau dégradé (latence GPRS, débit GSM), 5,7 secondes ;
- le même écran sur un réseau normal, moins de 0,6 seconde.

## 5. Tests Android

Ils sont joués par `e2e/android-qa.ts` (dépôt LEKA ADMIN) sur l'APK de debug réel, installé sur l'émulateur, contre un LEKA CORE local. Le script pilote la WebView de l'application avec l'outil Android de Playwright, et le téléphone avec `adb`. Chaque étape est chronométrée, avec une capture d'écran.

| Étape | Résultat |
| --- | --- |
| Installation propre (désinstallée, réinstallée) | réussie ; une seule permission demandée : `INTERNET` |
| Lancement à froid jusqu'à la connexion | réussi, 1,0 s |
| Mot de passe faux | refusé, et dit (« Adresse ou mot de passe incorrect. ») |
| Connexion | le tableau de bord |
| Onglets Clients, Utilisateurs, Activité | chacun avec ses lignes |
| Une fiche, puis le bouton retour du téléphone | retour à la liste |
| Intentions, Agents, IA Credits, Facturation & Finance, Environnements, Monitoring, Audit Logs | chacun avec ses lignes ou ses chiffres |
| Fermée de force puis rouverte | toujours connecté, sans rien retaper (session relue dans le Keystore et renouvelée) |
| Réseau dégradé (latence GPRS, débit GSM) | la liste se relit, en 5,7 s |
| Aucun réseau (mode avion) | l'échec est dit (« LEKA CORE ne répond pas. Vérifiez la connexion du téléphone. ») ; « Réessayer » relit une fois le réseau revenu |
| Petit téléphone (720 × 1280, 320 dpi) | rien ne dépasse de l'écran |
| Tablette (1600 × 2560) | rien ne dépasse de l'écran |
| Écran tourné (paysage) | le tableau de bord, lisible |
| Déconnexion, puis réouverture | l'écran de connexion : rien n'est gardé sur le téléphone |

**Langue** : l'application parle la langue du téléphone. Un émulateur en anglais l'affiche en anglais, ce qui est attendu. Le parcours règle sa langue en français (préférence de langue par application d'Android 13 et plus).

## 6. Anomalies

**Trouvées et corrigées**

| | Gravité | Anomalie | Correction |
| --- | --- | --- | --- |
| A1 | Importante (côté client) | Si la dernière erreur d'une source était gardée dans un ancien format (des mots seuls, ou un diagnostic sans un de ses champs), trois lectures tombaient en erreur 500 : la liste des sources d'un client (`GET /sources`), l'état d'une source et l'écran « Mon environnement ». Toute la page Sources du client était alors perdue. Le côté admin lisait déjà cet ancien format depuis LEKA-555 ; le côté client, non. Trouvé par le balayage de l'équipe vers le client | L'erreur est dite comme un diagnostic avec ce qu'elle a, son code « inconnu » s'il manque, nettoyée des secrets (`leka.connectors.kept`). Tests : `test_a_source_error_kept_in_an_older_shape_is_still_said`, et le balayage des routes client |
| A2 | Importante (montée en charge) | `GET /admin/credits` faisait 5 requêtes par organisation | Les crédits d'une page lus en une fois, mêmes chiffres (§ 4) |
| A3 | Mineure | Une constante HTTP 422 obsolète dans la route des incidents (LEKA-556) produisait un avertissement | Remplacée (LEKA-557) |

**Ouvertes, non bloquantes**

| | Gravité | Point | Suite proposée |
| --- | --- | --- | --- |
| O1 | Mineure | Sur le tableau de bord, le détail d'une alerte de la plateforme est en anglais (par exemple « no job finished in the last 7 days »), même quand l'application est en français : c'est la phrase du moniteur d'exploitation de LEKA CORE, aussi utilisée dans les e-mails d'alerte. Le titre de l'alerte, lui, est traduit | Rendre ce détail structuré (un code et ses chiffres) dans LEKA CORE, et le dire dans la langue de l'appli |
| O2 | À vérifier en production | Savoir si des sources de production ont encore une erreur dans l'ancien format (A1 est corrigé quoi qu'il en soit) | La requête en lecture seule, ci-dessous |
| O3 | Information | La build de release (signée) n'est pas encore produite | LEKA-559 : y rejouer `check:secrets` et le parcours Android |
| O4 | Information | Le parcours Android n'est pas dans la CI (pas d'émulateur sur les machines de GitHub) | Le jouer avant chaque livraison (`node e2e/android-qa.ts`) |
| O5 | Information | Les réponses servies aux tests de bout en bout sont enregistrées : elles vieillissent quand l'Admin API change | Les réenregistrer (`node e2e/record-fixtures.ts`) ; `tests/e2e-fixtures.test.ts` échoue si elles ne passent plus les schémas de l'appli |

**La requête de O2**, en lecture seule, à lancer depuis ton ordinateur (la base est sur RDS : on passe par le conteneur de l'API) :

```
ssh -i ~/.ssh/leka-admin.pem ubuntu@3.78.172.119 'sudo docker exec -i leka-api-1 python -' <<'EOF'
import asyncio
from sqlalchemy import text
from leka.db import session_factory, system_scope
async def main():
    with system_scope():
        async with session_factory() as s:
            print((await s.execute(text("select jsonb_typeof(last_error), count(*) from sources where last_error is not null group by 1"))).all())
asyncio.run(main())
EOF
```

Une ligne `string` signifie qu'il y a des sources concernées par A1. Le correctif les lit déjà ; rien d'autre n'est à faire.

## 7. Rejouer ces tests

| Quoi | Commande |
| --- | --- |
| L'API, dont les balayages de ce ticket | `pytest tests/test_admin_qa.py` (et la suite entière), depuis `api/` |
| L'application | `npm test`, `npm run typecheck`, `npm run lint` |
| Les parcours de bout en bout | `npm run e2e` (Playwright démarre l'application lui-même) |
| Les réponses enregistrées | avec un LEKA CORE local et l'appli sur le port 5181 : `LEKA_ADMIN_EMAIL=… LEKA_ADMIN_PASSWORD=… node e2e/record-fixtures.ts` |
| Le parcours Android | un émulateur démarré, l'APK de debug construit (`npm run android:apk`), un LEKA CORE local : `LEKA_ADMIN_EMAIL=… LEKA_ADMIN_PASSWORD=… node e2e/android-qa.ts` |
| Les secrets dans l'APK | `npm run check:secrets`, après `npm run android:apk` |
