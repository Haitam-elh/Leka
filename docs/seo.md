# SEO — leka-core.com (LEKA-432)

What the public site does for search engines, what is decided and what is
not, and how it is followed. No ranking is promised: progress is read in
Google Search Console, against the baseline below, over time.

## 1. The domain — to confirm

- **Today**: the site and the application are at `https://leka-core.com`
  (docs/deployment.md); `app.` and `www.` redirect to it permanently, path
  kept (deploy/Caddyfile). Every canonical, alternate, sitemap and
  structured-data URL says `https://leka-core.com`.
- **Open**: LEKA-432 names `https://lekacore.io/` as the intended official
  domain. Until Karim confirms it is registered, controlled and meant to be
  the canonical one, nothing moves: two canonical sites would compete.
- **If the move is decided**: lekacore.io in DNS and Caddy (`LEKA_APP_DOMAIN`),
  leka-core.com in `LEKA_APP_ALIASES` (one 301, path kept — no chain), every
  `https://leka-core.com` in `web/public/*.html`, `robots.txt`, `sitemap.xml`
  replaced, a new Search Console property and the change of address tool used.

## 2. What is in place

**Indexing**
- `web/public/robots.txt`: the public site open; the application's routes
  (`/overview`, `/intentions`, `/environment`…) disallowed.
- Every page of the application says `noindex, nofollow` (`web/app/layout.tsx`)
  — one reached through a link is never listed.
- `merci.html` (after a demo request) says `noindex` and is not in the sitemap.

**The sitemap** — `web/public/sitemap.xml`: each public page (home,
documentation, connectors, changelog, about, FAQ, pricing, demo) and its
address in each of the site's seven languages (`?lang=fr…pt`), each with its
alternates; the French address without `?lang` is `x-default`.

**Each public page's head**
- a canonical URL — the page's own; on a `?lang=` address, set to that address
  by `i18n.js`, as its hreflang alternates say;
- hreflang alternates for the seven languages and `x-default`;
- a unique title and description, one `<h1>`;
- Open Graph and Twitter card tags (title, description, URL, `LEKA-poster.jpg`).

**Brand signals** — the home page's title names the brand and the product
and says what it is: « LEKA Core, l'intelligence de votre environnement
technologique | LEKA »; its description, the same in a sentence. Its
structured data (JSON-LD): `Organization` (LEKA, its logo) and `WebSite`
(LEKA, also called LEKA Core). No `SoftwareApplication` or `Product`
schema, no reviews or ratings: nothing the page cannot back.

## 3. Baseline — 16/10/2026

Lighthouse 12.2, home page, mobile, production:

| Performance | Accessibility | Best practices | SEO |
|---|---|---|---|
| 78 | 95 | 100 | 100 |

| LCP | FCP | CLS | TBT | Speed index | Weight |
|---|---|---|---|---|---|
| 3.1 s | 3.1 s | 0 | 0 ms | 12.5 s | 288 KiB |

Tracked, to fix on the site's pages:
- **Speed index 12.5 s**: the content appears late — its entrance animations
  hold it back. Showing the first screen at once, animating only below it,
  is the fix to try first.
- **Accessibility**: a colour contrast too low and a heading level skipped on
  the home page.
- The video (`LEKA.mp4`, 8.8 MB) loads only its metadata until played: kept.

Search Console figures (impressions, clicks, CTR, position, indexed pages
for « LEKA », « LEKA Core », « LEKA AI ») start once the property is
verified (§ 4): they become the baseline then.

## 4. Search Console — to do by the domain's owner

1. Add the **Domain** property `leka-core.com` (or lekacore.io, § 1) in
   Google Search Console; verify it with the TXT record Google gives, at the
   DNS provider.
2. Submit `https://leka-core.com/sitemap.xml`.
3. Inspect `https://leka-core.com/`, request indexing.
4. Add Bilal (and whoever follows SEO) as users.

Analytics with conversions (demo requested, sign-up) is not installed: it
needs a consent banner and a decision on the tool (privacy-friendly first).

## 5. Content and keywords — roadmap

Built on what LEKA really does, from what the site already says; demand and
difficulty to be measured in Search Console once verified, then re-ranked.

| Priority | Query intent | Page |
|---|---|---|
| 1 | « LEKA », « LEKA Core », « LEKA AI » — the brand | Home (done), About |
| 2 | understanding one's IT environment, dependencies, impact of a change | Home, a page per use case |
| 3 | AI agents for IT teams: code review, incident investigation, architecture, security | Agents and bundles — a public page per bundle |
| 4 | connecting GitHub, Jira, Confluence, Datadog, AWS… to an AI | Connectors (exists), a short page per major connector |
| 5 | pricing of an AI assistant for IT | Pricing (exists) |

Rules: one intent per page; nothing invented — no customer, figure or
capability LEKA does not have; translated pages reviewed before they are
listed.

**Authority**: an official company profile (LinkedIn, GitHub organisation,
relevant directories) with the same name and the canonical domain; once they
exist, their URLs go in the `Organization`'s `sameAs`. No bought links.

## 6. Monitoring — every month

- [ ] Search Console: coverage errors, pages excluded, Core Web Vitals.
- [ ] Positions and clicks for « LEKA », « LEKA Core », « LEKA AI » and the
      priority queries, by country and language, against the baseline.
- [ ] Lighthouse on the home page (same command, mobile): no score down.
- [ ] A new public page: in the sitemap with its alternates, its head as § 2.
- [ ] Brand results: what else answers « LEKA », and whether the official
      site comes first.

Lighthouse, as run for the baseline:

```
CHROME_PATH=<a Chrome> npx lighthouse@12.2.1 https://leka-core.com/ \
  --only-categories=performance,seo,accessibility,best-practices --form-factor=mobile
```
