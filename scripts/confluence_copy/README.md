# Copier un espace Confluence dans un autre

Un outil en ligne de commande qui recopie un espace Confluence — l'arborescence
des pages, leurs titres, leur contenu, leurs pièces jointes — dans un autre
Confluence. Il tourne sur votre ordinateur : il ne lit que le Confluence
source, n'écrit que dans le Confluence cible, et ne contacte rien d'autre.

Un seul fichier, `confluence_copy.py`, et **Python 3.9 ou plus**, sans rien
d'autre à installer.


## Sous Windows, en un clic (le plus simple)

Pour la personne qui copie, rien à installer, aucune ligne de commande :

1. Celui qui reçoit la copie prépare le zip, une fois :

       python3 build_windows.py --target-url https://votre-site.atlassian.net \
           --target-email vous@exemple.com --ask-token

   `Copie-Confluence-Windows.zip` arrive sur le Bureau : Python y est inclus
   (la version officielle « embarquable », sans installation ni droits
   administrateur), avec l'outil, `Copier-Confluence.bat`, un `LISEZ-MOI.txt`
   et le Confluence cible déjà renseigné.

2. La personne qui copie : clic droit → « Extraire tout », puis double-clic
   sur `Copier-Confluence`. L'assistant lui demande seulement l'adresse de son
   Confluence, son e-mail et son token (saisie masquée), liste ses espaces, et
   copie ceux choisis — pages, arborescence, pièces jointes (PDF, Excel,
   images…, 100 Mo au plus chacune).

Sans commande (`python confluence_copy.py`), c'est ce même assistant.

## 1. Vérifier Python (2 minutes)

```bash
python3 --version        # macOS, Linux
py --version             # Windows
```

Sans Python 3.9 ou plus : [python.org/downloads](https://www.python.org/downloads/)
(sous Windows, cochez « Add python.exe to PATH »).

## 2. Les identifiants (3 minutes)

Copiez `.env.example` en `.env`, dans ce dossier, et remplissez-le :

| Variable | Ce qu'elle contient |
| --- | --- |
| `SOURCE_URL` | L'adresse du Confluence lu : `https://<site>.atlassian.net`, ou celle de votre Confluence Data Center |
| `SOURCE_EMAIL` | Cloud : le mail du compte. Data Center : laissez vide |
| `SOURCE_TOKEN` | Cloud : un token API. Data Center : un jeton d'accès personnel |
| `TARGET_URL` | L'adresse du Confluence où écrire : `https://<site>.atlassian.net` |
| `TARGET_EMAIL` | Le mail du compte de ce Confluence |
| `TARGET_TOKEN` | Un token API de ce compte |

- **Token API Confluence Cloud** : [id.atlassian.com](https://id.atlassian.com)
  → Sécurité → Créer et gérer les tokens d'API → Créer.
- **Jeton d'accès personnel Data Center** : votre avatar → Profil → Jetons
  d'accès personnels → Créer.

Le compte source n'a besoin que de **lire** l'espace. Le fichier `.env` ne
quitte jamais votre ordinateur ; ne le transmettez pas.

## 3. Voir ce qui sera copié, sans rien écrire

```bash
python3 confluence_copy.py copy --space ARCHI --dry-run
```

`ARCHI` est la clé de l'espace : elle figure dans son adresse
(`…/spaces/ARCHI/…`). Pour une page et ses enfants seulement, ajoutez
`--root-page 123456` (l'identifiant dans l'adresse de la page :
`…/pages/123456/…`).

Le résultat : l'arbre des pages, leur nombre, la profondeur de
l'arborescence et le nombre de pièces jointes.

## 4. Copier

```bash
python3 confluence_copy.py copy --space ARCHI
```

Les pages sont créées dans l'espace de même clé côté cible — créé s'il n'existe
pas ; `--target-space AUTRE` en choisit un autre. Les parents avant les
enfants, chaque page sous la même page parente que dans la source ; les liens
d'une page vers une autre page copiée mènent à sa copie ; les pièces jointes
suivent leur page (jusqu'à 50 Mo chacune).

À la fin :

```
Pages créées        : 42
Pages mises à jour  : 0
Pages ignorées      : 0 (déjà identiques)
Pages en erreur     : 0
Pièces jointes      : 17 copiées
```

et le détail dans `rapport-copie.json`.

**Relancer ne crée aucun doublon** : une page déjà copiée — même espace, même
titre — est mise à jour si elle a changé, ignorée sinon. Une copie
interrompue se reprend en relançant la même commande.

## Sans accès direct au Confluence cible : exporter, puis importer

Quand l'ordinateur qui lit la source ne doit pas recevoir les identifiants de
la cible :

```bash
# Sur l'ordinateur qui lit la source (seuls SOURCE_* sont nécessaires) :
python3 confluence_copy.py export --space ARCHI --out ./export-archi
# → zippez le dossier export-archi et transmettez-le.

# Puis, là où sont les identifiants de la cible (seuls TARGET_* sont nécessaires) :
python3 confluence_copy.py import --from ./export-archi --dry-run
python3 confluence_copy.py import --from ./export-archi
```

L'export contient `arborescence.txt` (l'arbre lisible), `space.json`, et un
dossier par page : son contenu, ses métadonnées, ses pièces jointes.

## Importer des fichiers Markdown ou HTML

`import` accepte aussi un dossier de fichiers `.md` ou `.html` : chaque fichier
est une page, chaque sous-dossier la page parente de ce qu'il contient (le
fichier qui porte son nom, sinon une page vide à son nom). Un export HTML de
Confluence s'importe ainsi : seul le contenu de chaque page est repris, sans
le fil d'Ariane ni le pied de page.

```bash
python3 confluence_copy.py import --from ./mes-pages --target-space ARCHI --space-name "Architecture"
```

## En cas d'erreur

| Message | Que faire |
| --- | --- |
| `SOURCE_URL et SOURCE_TOKEN sont à renseigner` | Le fichier `.env` manque, ou n'est pas dans ce dossier |
| `Accès refusé (401)` | Le mail ou le token est faux |
| `Accès refusé (403)` | Le compte n'a pas le droit de lire l'espace, ou d'écrire dans la cible |
| `L'espace … est introuvable` | La clé d'espace est fausse, ou le compte ne le voit pas |
| `… n'a pas pu être créé` | Créez l'espace cible à la main avec cette clé, puis relancez |

Le token n'apparaît jamais dans un message ni dans le rapport.
