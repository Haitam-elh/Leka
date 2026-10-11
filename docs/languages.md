# Languages

LEKA is offered in 140 languages, chosen by product priority. This page says
what "offered" means for each one, how LEKA picks a language for someone,
and how to add a language or a translation.

The list is not a ranking of the world's languages. Each language is said
with a standard tag (BCP 47), so browsers, operating systems and language
models read it the same way.

## 1. Three different things, never confused

| | What it means | Where it is said |
|---|---|---|
| **Offered** | The language can be chosen. LEKA keeps the choice, formats dates and numbers for it, and writes its answers in it. | All 140 |
| **Translated** | LEKA's own words (screens, site, e-mails) exist in it. `reviewed`: approved by someone who speaks it. `translated`: not approved yet. `partial`: some words only, the rest falls back. | `ui` in the catalogue, per surface |
| **AI-written** | How well language models generally write it today: `strong`, `good` or `limited`. This is LEKA's estimate across providers. It is not a promise, and it is revised as models change. | `ai` in the catalogue |

Today:

| Surface | Reviewed | Partial | Everything else |
|---|---|---|---|
| The application (`app`) | French, English | — | Shown in the next language of its chain (§ 3) |
| The site leka-core.com (`site`) | French, English | German, Spanish, Italian, Dutch, Portuguese | Shown in English, with a notice saying so |
| E-mails (`emails`) | French, English | — | Written in the next language of the chain |

**A language is never presented as translated when it is not.**
- The picker says, for each language, whether the interface is translated, and if not, which language it shows meanwhile.
- The site says it in a notice.
- Tests hold the catalogue to the dictionaries, both ways: `lib/i18n/coverage.test.ts` and `tests/test_auth_emails.py`.
- `npm run i18n:report` prints, language by language, how many of the interface's words are translated.

## 2. The catalogue: one file

`api/leka/core/languages.yaml` is the only list. For each language it gives:
- the tag;
- its name in English (the ticket's list, word for word);
- its own name in its own script;
- its script and direction;
- a `parent` where the fallback is not simply the base language (Dari falls back to Persian, Cantonese to Traditional Chinese);
- the `ai` estimate and the `ui` statuses.

It also holds:
- **aliases**, for what browsers and older systems say: `zh-TW` is Traditional Chinese, `fa-AF` is Dari, `iw` is Hebrew, `no` is Norwegian Bokmål;
- the **regions** a person may choose.

The API checks the file when it reads it (`leka/core/languages.py`). It refuses:
- a language listed twice;
- a tag that is not canonical;
- a region inside a language tag;
- a direction that does not match the script;
- an unknown parent or alias;
- a default language that is not reviewed everywhere.

The web reads the same file as `web/public/languages.json`. A test checks that the two copies are equal. After an edit, run this in `api/`:

```
python -m leka.core.languages > ../web/public/languages.json
```

**A language and a region are two settings.**
- The language decides the words.
- The region decides dates, numbers and amounts: `pt` with `BR` formats as `pt-BR`, `fr` with `CA` as `fr-CA`.
- A region never chooses a language, and no country is refused.

## 3. When a translation is missing

Each language has a chain, and LEKA uses the first language in it that is translated. The chain is:
1. the language;
2. its parents;
3. its base language (`pt-BR` → `pt`);
4. the workspace's language;
5. English.

Examples:
- Dari in a French workspace: `prs → fa → fr → en`. The screens are in French, and LEKA answers in Dari.
- Japanese with no workspace yet: `ja → en`.

A partial translation falls back key by key, never to an empty string. In development, the missing keys are printed in the console. The QA report counts them.

## 4. Which language someone gets

The first of these that names a language LEKA offers:

1. **A choice made just now in this tab**: on the site's menu, the sign-in's language button, or the application's picker. It is kept on the device and handed to the account at sign-in.
2. **The account's language**, once signed in. It is the same on every device.
3. **A choice made on this device before**: the first-party cookie `leka-lang`, also in `localStorage`.
4. **The browser's languages**, most wanted first (`Accept-Language`, `navigator.languages`).
5. **The country the request came from**, as a hint only. It is read from a header that a CDN in front of LEKA adds (`cf-ipcountry`, `cloudfront-viewer-country`, `x-vercel-ip-country`). Its most likely language comes from CLDR.
6. **English.**

**About the country:**
- A browser that names a language always wins over the country: someone in France whose browser is in English reads English.
- Production has no CDN today, so there is no country signal. Step 5 is skipped.
- No location is ever asked of the browser, and no service is called.

**The first paint is already in the right language.**
- The server reads the cookie, `Accept-Language` and the country header (`lib/i18n/server.ts`).
- The browser then adds what only it knows: the choice made in this tab and its storage.
- No language flashes, no redirect is made, and nothing waits on a location.

**After signing in:**
- The account's language applies.
- A choice made just before signing in replaces it, and is saved to the account.
- An account with no language yet (created before languages, or by invitation) sees, once, the language found from the browser, with « Garder » and « Changer ».

**Registering** keeps the language the form was shown in. The confirmation e-mail is written in it.

## 5. Where the language is chosen

- **The site**: the footer's menu. The translated languages come first, then the others, each in its own name. `?lang=xx` on any page is a choice, and `sitemap.xml` gives every page in each language as an alternate, for search engines.
- **The sign-in, registration and recovery pages**: the language button in the header.
- **The application**:
  - the account menu, « Langue »;
  - Paramètres, « Langue et région »: the person's language and region;
  - the workspace's language, for an owner or an administrator.

The picker lists the 140 languages. A search matches:
- a language's own name;
- its English name;
- its name in the interface's language;
- its tag.

Accents and case do not matter: « francais » finds Français, « Turkce » finds Türkçe.

## 6. Right to left

Arabic, Egyptian Arabic, Hebrew, Yiddish, Persian, Dari, Pashto, Urdu, Uyghur, Kurdish (Sorani), Sindhi and Kashmiri are written right to left.

- The layout uses logical properties: `ms-`/`me-`, `ps-`/`pe-`, `start-`/`end-`, `text-start`, `border-s`. Directional arrows mirror, and the drawer opens from the right.
- The page's `dir` follows the language the screens are actually written in. Until a right-to-left translation exists, the screens are in a left-to-right language.
- What people and models write is laid out paragraph by paragraph in its own direction (`unicode-bidi: plaintext`). An answer in Arabic reads right to left inside a French screen, and so does what someone types.

**Testing it before any translation exists: the QA pseudo-languages.**
- `?qa-language=ar-XB` on any page mirrors the whole application, with English words drawn right to left.
- `?qa-language=en-XA` makes every word accented and about 40 % longer. A label that will not fit in German or Finnish shows now, and a word not taken from the dictionaries stands out.
- `?qa-language=` turns them off.
- They are never in the picker and never saved.

## 7. Scripts, plurals, dates and numbers

- **Fonts**: Geist draws Latin. Every other script falls to the system's own sans-serif faces, named by family in `globals.css`.
- **Plurals**: `plural()` (`lib/i18n/format.ts`) uses the browser's `Intl.PluralRules`, so each language follows its own rules: French, English, Polish, Arabic.
- **Dates, numbers, currencies and time zones**: always written through `Intl` with `format` from `useLocale()` (the screens' language in the person's region), never with a hard-coded locale.

## 8. E-mails and AI answers

**E-mails** are written in:
1. the recipient's language;
2. otherwise, the language of the page they used;
3. otherwise, their workspace's language;

following the chain to a language e-mails are translated into. Their `Content-Language` header says which. This covers verification, password reset, invitation, AI credit warnings and decision escalations.

**AI answers:**
- A language model is told to write in the person's language, whatever language the question, the context or the sources are in. Names, ids, quotations and code stay as they are.
- A request that explicitly asks for another language is followed.
- An agent's own instructions win when they require a language (the architecture deck's template is in French).
- What LEKA writes for a whole workspace, such as entity descriptions, is written in the workspace's language.
- None of this depends on a provider or a model.

## 9. Adding a language or a translation

**A language:**
1. Add an entry to `languages.yaml`.
2. Regenerate `web/public/languages.json`.
3. The tests say what is missing.

**A translation of the application:**
1. Add it to `PARTIAL` in `web/lib/i18n/dictionaries.ts`, key by key. Whatever is left out falls back.
2. Set `ui.app: partial` in the catalogue.
3. Once every key is there, move it into `DICTIONARIES` and set `translated`.
4. Set `reviewed` only after someone who speaks the language has approved it.

**A translation of the e-mails:**
1. Add the language to `WORDS` in `leka/identity/messages.py`, and to the words of `metering/credits.py` and `intentions/oversight.py`.
2. Set `ui.emails` in the catalogue.

**A translation of the site:** add the language to `public/i18n.js` and `public/site-i18n.js`, then set `ui.site`.

## 10. Privacy

| What | Where it is kept | What it contains |
|---|---|---|
| The `leka-lang` cookie | First-party | The tag of a language chosen, nothing else |
| `leka-lang-now` | The tab's session storage | The same, until the account takes it |
| The account's and the workspace's languages | The database | The chosen tags |

- The country, when a CDN provides one, is read from the request for the first paint and never stored.
- No precise location is ever asked for.
