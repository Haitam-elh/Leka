# Deployment — how LEKA ships, and how to undo it

> Watching it run — metrics, health, alerts, what to do for each, backups
> that are proven to restore, recovery targets: [operations.md](operations.md)
> (LEKA-408).

One environment online: **production**, at `https://leka-core.com` (the
site and the web app, one address — see [below](#leka-corecom-the-site-and-the-application-as-one))
and `https://api.leka-core.com` (the API). There is no staging: what
protects production is what runs before it — CI and the browser suite on
every pull request, and `deploy.sh`, which puts the previous release back
when a new one does not come up.

For losing data rather than losing a deployment, see
[`runbook.md`](runbook.md). For what every `LEKA_*` variable means, see
[`configuration.md`](configuration.md). For why the shape below and not a
managed platform, see [`adr/014-hosting.md`](adr/014-hosting.md).

---

## What is running, and where

| | |
|---|---|
| **Instance** | one EC2, `eu-central-1`, x86_64, Docker Compose |
| **Containers** | `caddy` → `web` and `api`, plus `worker`, `scheduler`, `redis`, and `migrate` which runs once |
| **Names** | `leka-core.com` → `web` (the site and the application), `api.leka-core.com` → `api`; `app.` and `www.` redirect to `leka-core.com`; Caddy holds every certificate |
| **Database** | Amazon RDS for PostgreSQL, `eu-central-1` — **not** on the instance, not reachable from the internet |
| **Object storage** | Amazon S3, `eu-central-1` |
| **Email** | the OVH mailbox `support@leka-core.com`, over SMTP (`ssl0.ovh.net:465`) |
| **Images** | `ghcr.io/<owner>/leka/api:<sha>` and `…/web:<sha>` — one commit, two images, never `latest` |
| **Errors** | Sentry, EU region, scrubbed before they leave — from the API **and** from jobs |
| **Files on the box** | `/opt/leka/` — `deploy.sh`, the compose file, the Caddyfile, and `production.env` |

`production.env` exists **only on the instance**. It is the one file that
holds real credentials, it is in `deploy/.gitignore`, and
`deploy/production.env.example` is its documentation.

**The web app's API address is baked in when its image is built.** Next.js
writes `NEXT_PUBLIC_API_URL` into the JavaScript it sends to browsers, so it
comes from the repository variable `PROD_API_URL` at build time, not from
`production.env`. Changing the API's name means rebuilding the web image.

The worker and the scheduler are two processes of the API image:
`python -m leka.platform.worker` runs jobs, `python -m leka.platform.scheduler`
puts the ten-second tick and the sweeps on the queue. **Without the
scheduler the worker waits for ever** — the tick is what turns `events` into
`job_runs`. Both configure logging and Sentry before they run anything, which
plain `rq worker` and `rq cron` do not.

---

## Deploying

Nothing to do. A merge to `main` runs CI; if CI is green, CD builds the two
images, pushes them and runs [`deploy/deploy.sh`](../deploy/deploy.sh) on the box.

`deploy.sh` is the whole procedure, and it is the same file whether CD runs it
or a person does:

1. **make room**: every image no container uses goes — what runs stays, it
   is what a failed deployment falls back to — then, with less than 2 GB
   free, stop there ([below](#when-the-disk-is-full));
2. **pull** both images — if either fails, nothing has been touched;
3. **switch**: write the registry and the release into `production.env`,
   `up -d`;
4. **verify**: the API answers `/api/v1/health` from inside its own
   container, the web app answers `/login`, and the worker and the scheduler
   are still the same processes five seconds later — not restarting in a
   loop;
5. if any of that fails within ninety seconds, **switch back** to the
   previous release and verify that too; if it succeeded, the previous
   release's images go — rolling back to it pulls them again.

| Exit | Meaning |
|---|---|
| `0` | deployed and healthy |
| `1` | **not** deployed; the previous release is running |
| `2` | nothing healthy is running — the box needs a person |

To deploy a specific commit — or to roll back after the fact — run the **CD**
workflow manually from the Actions tab with `release` set to a commit sha,
short or full. An image that already exists is deployed as it is, never
rebuilt: what goes out is byte for byte what went out the first time.

### By hand, on the box

For when GitHub is down, or the SSH key is being rotated:

```bash
ssh <user>@<production-host>
cd /opt/leka

grep -E '^LEKA_(REGISTRY|RELEASE)=' production.env   # what is running now

docker login ghcr.io -u <github-user>                # a PAT with read:packages
bash deploy.sh ghcr.io/<owner>/leka <sha>
```

### Where CI and CD run

Every job says `runs-on: ${{ vars.CI_RUNS_ON || 'ubuntu-latest' }}`. With
the repository variable `CI_RUNS_ON` unset, GitHub's runners. With
`CI_RUNS_ON = leka`, **the self-hosted runner**. GitHub counts Actions
minutes on the repository owner's account, everyone's pushes included, and
past the month's allowance it runs nothing; the self-hosted runner costs no
minutes.

**What it is:** a Linux VM on a developer's Mac. It is the Colima profile
`leka-x86`: Ubuntu 24.04, arm64, with Rosetta for the amd64-only images
(SQL Server), 4 CPUs, 6 GB, 40 GB. The runner is in `~/actions-runner`, as a
systemd service, named `leka-mac` with the label `leka`. CD builds the
production images for `linux/amd64` wherever it runs.

**Its limits:**
- It runs one job at a time.
- It runs only while the Mac is awake and the VM is up: `colima start leka-x86`
  after a reboot. A job waits in *Queued* otherwise, and GitHub drops it
  after 24 hours.
- Nothing else in that VM may use the CI's ports (5432, 1433, 1521, 9000…)
  while a job runs.

**Setting it up again**: a token from the repository's *Settings → Actions →
Runners → New self-hosted runner*, then:

```bash
colima start leka-x86 --arch aarch64 --vm-type vz --vz-rosetta --cpu 4 --memory 6 --disk 40
colima ssh -p leka-x86
# in the VM: download and unpack the runner as that page says, into ~/actions-runner, then
./config.sh --url https://github.com/<owner>/<repo> --token <token> --name leka-mac --labels leka --unattended
sudo ./svc.sh install && sudo ./svc.sh start
```

Two settings, without which the suite fails there and nowhere else:

1. **Python where its builds expect it.** `actions/setup-python`'s builds
   find `libpython` under `/opt/hostedtoolcache`. Installed anywhere else, a
   Python started with a clean environment cannot load it: the production
   checks in `tests/test_api_contract.py` start one.

   ```bash
   sudo mkdir -p /opt/hostedtoolcache && sudo chown "$USER" /opt/hostedtoolcache
   printf 'AGENT_TOOLSDIRECTORY=/opt/hostedtoolcache\nRUNNER_TOOL_CACHE=/opt/hostedtoolcache\n' >> ~/actions-runner/.env
   sudo ./svc.sh stop && sudo ./svc.sh start
   ```

2. **One clock.** Two things set the VM's clock: Colima's guest agent, from
   the Mac, and NTP, from the internet. They disagree by about 110 ms, so the
   clock moves back every 10 to 20 seconds. That fails any test comparing two
   instants, for example a sync run that "finished before it started". Turn
   NTP off; the Mac's clock is the one kept:

   ```bash
   sudo timedatectl set-ntp false
   ```

---

## Rolling back

The same command with the previous sha. `deploy.sh` does it on its own when a
deployment does not come up; by hand:

```bash
bash deploy.sh ghcr.io/<owner>/leka <previous sha>
```

**Rehearsed, not assumed.** The exact `deploy.sh` and compose file were run
against a local registry with four releases:

| Scenario | Result |
|---|---|
| first deployment, nothing to go back to | `0`, healthy |
| a release carrying a migration | `0`, schema migrated |
| a release whose migration fails | `1`, back on the previous release, the env file says so |
| migration applied, then the API does not start | `1`, back on the previous release **with the newer schema in place** |
| an image that does not exist | `1`, nothing touched |
| going back two releases, by hand | `0`, healthy |

The fourth line is the one that used to fail. See below.

### The schema is not rolled back

Rolling the image back does **not** roll the database back, and that is
deliberate — an automatic `alembic downgrade` during an incident is how a
bad deployment becomes a lost afternoon.

So after a rollback the database is usually **ahead** of the image. The
`migrate` container runs `python -m leka.db.migrate`, which recognises that
and leaves the schema alone with a `schema_ahead_of_release` warning. It used
to run `alembic upgrade head`, which fails on a revision it has never heard
of — and since the API waits for `migrate`, every rollback after a release
that carried a migration failed there, leaving the broken release running.

Almost every rollback needs nothing more: a migration that only adds things
leaves the previous version working. Go further only when the old code
genuinely cannot run against the new schema — a dropped or renamed column.
Then:

1. **Take an RDS snapshot** (`runbook.md`, "Before anything risky"). It is
   the only undo a downgrade has.
2. **Downgrade with the NEWER image**, before switching back. Only the image
   that wrote a migration knows how to undo it; the older one has never
   heard of it and fails exactly as `alembic upgrade head` did.

   ```bash
   docker compose -f docker-compose.production.yml --env-file production.env \
     run --rm migrate alembic downgrade <revision the previous release expects>
   ```

3. Then roll the image back with `deploy.sh`.

The downgrade path is exercised in CI on every pull request
(`alembic downgrade base` then `upgrade head`), so step 2 is tested rather
than hoped for. It was not, before: the downgrade of
`20260920_0930_workspace_lifecycle.py` had never run and did not work.

---

## When the disk is full

The symptom: CD fails at *Deploy, verify, and roll back*, on a pull —
`no space left on device`, or `deploy.sh`'s own `MB free on the disk, 2048
MB needed`. Nothing was changed: the previous release is still running.

**Why it happened once (CD #77, 2026-09-29).** `deploy.sh` removed old
images only after a successful deployment, and only once they were a week
old. Docker's containerd image store keeps each image twice, packed and
unpacked; a week of daily merges filled the 20 GB disk, and a pull died
half-way. It now makes room BEFORE each pull, keeping only what runs.

If it happens again — something other than images is filling the disk:

```bash
ssh -i ~/.ssh/leka-admin.pem ubuntu@<elastic ip>
df -h /                          # how full
docker system df                 # images, containers, volumes, build cache
sudo du -xh --max-depth=2 /var | sort -h | tail -15    # who, outside Docker
docker image prune -af           # what no container uses; what runs stays
```

Container logs are capped (10 MB × 3 per container, in the compose file);
`journalctl --vacuum-size=200M` trims the system journal. Then re-run the
failed CD job — **Re-run jobs** on its page — or `deploy.sh` by hand.

Growing the disk, when that is the answer: EC2 → *Volumes* → the
instance's volume → *Modify volume* → size; then on the box
`sudo growpart /dev/nvme0n1 1 && sudo resize2fs /dev/nvme0n1p1`. No
restart.

---

## When the worker stops consuming

The symptom: intentions are accepted and nothing happens. `events` rows stay
`pending`, or `job_runs` rows stay `queued`.

In the commands below, `dc` stands for
`docker compose -f docker-compose.production.yml --env-file production.env`.

**1. Are the worker and the scheduler alive?**

```bash
dc ps worker scheduler
dc logs --tail=100 worker
dc logs --tail=20 scheduler     # "Enqueued job run_maintenance_tick" every 10 s
```

A process in a restart loop is usually a bad `production.env`: it starts, fails
to reach Redis or Postgres, and dies. The logs say which. A scheduler that is
not running is the quiet version of this: nothing fails, nothing is
dispatched.

**2. Is Redis alive, and does it hold the jobs?**

```bash
dc exec redis redis-cli ping
dc exec redis redis-cli llen leka:high leka leka:low
```

Long queues with a live worker means jobs are failing and being retried; go to
step 4. Empty queues with `pending` events means dispatch is not running; go
to step 3.

**3. Is anything dispatching?** The tick the scheduler enqueues runs
`leka.background.tasks.run_maintenance_tick`, which dispatches events into
job runs; the worker logs `event_dispatch_completed` each time. The queries
that answer "is the loop alive" are in [`background.md`](background.md) —
that file is the dashboard, by decision, and this is what that decision
means in practice.

**4. What is actually failing?** Look in Sentry first: an exception inside a
job lands there with its release and two tags, `job` and `run_id`.
`job_runs.last_error` holds the same thing without the stack.

**5. Restart it.** Safe at any moment. A job interrupted halfway is retried,
and LEKA-334's leases mean only one worker can win it:

```bash
dc restart worker
```

**6. Drain a poisoned queue.** When one job kills the worker on every retry
and blocks everything behind it, that job is not worth the outage. Empty the
queue in Redis and re-dispatch from `events`, which is the durable record:

```bash
dc exec redis redis-cli del leka:high leka leka:low
```

---

## When the whole box is unreachable

Everything on the instance is disposable. Nothing on it is a source of truth:
the database is RDS's, the files are S3's, the images are GHCR's, and the
only thing that is not reproducible from Git is `production.env`.

So the recovery is the first-time setup below, with `production.env` written
from the password manager, then `bash deploy.sh` with the last good sha. Ten
minutes, and the first nine are AWS booting a machine. The new instance must
join the security group RDS accepts, or the API cannot reach the database.

**Keep a copy of `production.env` in the team password manager.** It is the
one thing that makes the paragraph above true.

---

## Turning production on

**The CD workflow does nothing until you say so.** It is guarded by a
repository variable, `PRODUCTION_ENABLED`, which does not exist until the
box is ready — so the pipeline can be merged and sit in the repository
costing nothing, running nothing and deploying nothing. A workflow that
fails on every merge because it has nowhere to go teaches people to ignore a
red tick, and that is the one habit CI does not survive.

Everything below happens in a console, by a person. The order matters: the
account before anything is created on it, DNS before Caddy asks for
certificates, the database before the first deployment.

### 1. The AWS account: on the credits, upgraded before they run out

**Decided 2026-09-25:** production starts on the free plan's credits, and
the account moves to the paid plan when they are nearly spent.

**Nearly, not after.** On the free plan the account does not start billing
when the credits run out — it **closes**, and AWS deletes what is on it
ninety days later ([`runbook.md`](runbook.md#the-aws-account-convert-it-before-production)).
So:

- Once a month: Billing and Cost Management → **Credits**, read the
  remaining balance. Below about **$50** — one month of this setup — do the
  upgrade (three clicks, same section of the runbook). Same before the
  first paying customer, whichever comes first.
- The **budget alarm** measures what the credits pay for: Billing and Cost
  Management → Budgets → the existing budget → Edit → raise it to **$50 a
  month**, and in *Advanced options* make sure **Credits** is not counted,
  or it reads zero while the credits drain.

Everything below: region **Europe (Frankfurt) `eu-central-1`**, top right of
every console. A resource created in another region is invisible from this
one.

### 2. The instance, first — RDS attaches itself to it

EC2 → **Launch instance**:

| Setting | Value | Why |
|---|---|---|
| Name | `leka-production` | |
| Image | **Ubuntu Server 24.04 LTS**, 64-bit **(x86)** | the images CD builds are amd64 |
| Type | **`t3.small`** (2 GiB) | `t3.micro`'s 1 GiB cannot hold the API, worker, scheduler, web app, Redis and Caddy |
| Key pair | Create → `leka-admin`, ED25519, `.pem` — into the password manager | YOUR way in. Not the key GitHub uses |
| Security group | Create → allow **SSH** from *Anywhere*, **HTTPS** and **HTTP** from the internet | SSH takes keys only; GitHub's runners have no fixed address. HTTP is for Let's Encrypt and the redirect |
| Storage | **20 GiB gp3** | the release running and the one being pulled — `deploy.sh` makes room before each pull |

Then EC2 → Elastic IPs → **Allocate** → **Associate** with `leka-production`.
That address is the one DNS points at; it survives a stop and start. It is
billed (about $0.005 an hour, like every public IPv4 address on AWS).

On the box, once:

```bash
ssh -i leka-admin.pem ubuntu@<elastic ip>
curl -fsSL https://get.docker.com | sudo sh        # Docker Engine + Compose plugin
sudo usermod -aG docker ubuntu
sudo mkdir -p /opt/leka && sudo chown ubuntu:ubuntu /opt/leka
exit                                                # reconnect so the group applies
```

The key GitHub Actions deploys with — on YOUR laptop, never on the box:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/leka-deploy -N "" -C "github-actions-deploy"
ssh -i leka-admin.pem ubuntu@<elastic ip> 'cat >> ~/.ssh/authorized_keys' < ~/.ssh/leka-deploy.pub
```

The PRIVATE half (`~/.ssh/leka-deploy`, no `.pub`) becomes the GitHub
secret `PROD_SSH_KEY` in step 7. Nowhere else.

### 3. The database: RDS

RDS → **Create database** → *Standard create*:

| Setting | Value | Why |
|---|---|---|
| Engine | PostgreSQL, version **16** | what CI tests against |
| Template | **Free tier** if offered, otherwise Dev/Test — single instance | available on the free plan for `db.t4g.micro` |
| Identifier | `leka` | the name the runbook's commands use |
| Master user | `leka`; password **self-managed**, generated, into the password manager | it goes in `production.env` and nowhere else |
| Instance | `db.t4g.micro` | smallest that runs it; resize later without data loss |
| Storage | gp3, 20 GB, **encryption on** | encryption can only be chosen at creation |
| Connectivity | **Connect to an EC2 compute resource** → `leka-production` | the console creates the two security groups that let this box, and only it, reach 5432; public access stays **No** |
| Additional configuration → Initial database | `leka` | |
| Backups | **on, 7 days** — or the most the free plan allows, raised after the upgrade | the point-in-time window; see the runbook |
| Deletion protection | **on** | a deleted instance takes its automated backups with it |

The endpoint is on the instance's page, *Connectivity & security*. The
schema is created by the first deployment (`migrate`), from nothing: there
is no data to carry over from Neon, which only ever held seeded data.

### 4. Object storage: a production bucket and a key that opens only it

S3 → **Create bucket**: `leka-payloads-prod-<a few random letters>` (names
are global), `eu-central-1`, **Block all public access: on** (the default),
default encryption. Not the validation bucket: that one held test data.

IAM → Users → **Create user** `leka-production-s3`, no console access →
Permissions → *Create inline policy* → JSON, with the bucket's name:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::<bucket>" },
    { "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"],
      "Resource": "arn:aws:s3:::<bucket>/*" }
  ]
}
```

Then the user → Security credentials → **Create access key** (*Other*). The
two values go into `production.env` in step 5, and the password manager.

### 5. `production.env`, on the box

```bash
scp -i leka-admin.pem deploy/production.env.example ubuntu@<elastic ip>:/opt/leka/production.env
ssh -i leka-admin.pem ubuntu@<elastic ip>
chmod 600 /opt/leka/production.env
python3 -c "import secrets; print(secrets.token_urlsafe(64))"                    # LEKA_SECRET_KEY
python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"  # one Fernet key
nano /opt/leka/production.env
```

Fill in: `LEKA_DATABASE_URL` (password and endpoint from step 3, ending
`?ssl=require`), `LEKA_SECRET_KEY`, `LEKA_ENCRYPTION_KEYS=["<the Fernet
key>"]`, the S3 bucket and key from step 4, `LEKA_SMTP_PASSWORD` (the OVH
mailbox's), and `LEKA_SENTRY_DSN` if there is one. Leave `LEKA_REGISTRY` and
`LEKA_RELEASE` empty: `deploy.sh` writes them.

**Then copy the whole file into the password manager.** It is the one thing
on the box that Git cannot rebuild.

### 6. DNS, at OVH

In the zone of `leka-core.com`, two A records pointing at the Elastic IP:
`app` and `api` — and, since the move [below](#leka-corecom-the-site-and-the-application-as-one),
`leka-core.com` itself and `www`. Wait until `dig +short app.leka-core.com` answers it.
Caddy then obtains both certificates on its first start. The email records
(SPF, DKIM, DMARC) are in the same zone; see
[`runbook.md`](runbook.md#email-the-dns-records-that-get-it-delivered).

### 7. GitHub, once

Repository secrets, in an environment called `production`
(Settings → Environments → production):

| Secret | What it is |
|---|---|
| `PROD_HOST` | the Elastic IP |
| `PROD_USER` | `ubuntu` |
| `PROD_SSH_KEY` | the private deploy key from step 2 — for this alone, not anyone's personal key |

Repository variables (Settings → Secrets and variables → Actions →
Variables) — not secrets, the browser sees the first one anyway:

| Variable | Value |
|---|---|
| `PROD_API_URL` | `https://api.leka-core.com` — baked into the web build |
| `PRODUCTION_ENABLED` | `true` — **last**, once everything above is in place |

`GITHUB_TOKEN` is provided by Actions: it pushes the images, and the box
pulls with it during the deployment. Nothing to create.

Remove `PRODUCTION_ENABLED`, or set it to anything else, and deployment
stops again — which is also how you pause it during an incident without
reverting anything.

### 8. The first deployment

Run the **CD** workflow by hand (Actions → CD → Run workflow). Then, from a
laptop:

```bash
curl -fsS https://api.leka-core.com/api/v1/health
curl -fsSI https://leka-core.com/login | head -1
```

and create an account through the page, as a user would: the email must
arrive, and its link must open `https://leka-core.com/verify/…`.

---

## leka-core.com: the site and the application, as one

Karim's site — the pages that were on OVH's shared hosting — and the
application are one site since this change. `web` serves both:

| Address | What answers |
|---|---|
| `/`, `/connecteurs.html`, `/demo.html`… | the site: static files in `web/public/`, untouched by the build |
| `/login`, `/register`, `/overview`, `/sources`… | the application |
| `/login.html` | a permanent redirect to `/login` — the site's sign-in could not sign anyone in |
| `/index.html` | a permanent redirect to `/` |
| `app.leka-core.com/…`, `www.leka-core.com/…` | a permanent redirect to `leka-core.com/…`, path kept |

The API keeps its own name. `leka-core.com` and `api.leka-core.com` are the
same site to a browser, so the session cookie does not change (ADR 009).

### Moving to it — in this order

Each step works on its own; the order is what keeps the site up.

1. **Merge.** CD deploys as usual. Nothing moves yet: `app.leka-core.com`
   still serves everything, and its `/` now shows the site.
2. **DNS, by whoever holds the OVH account** — OVH Manager → Web Cloud →
   Noms de domaine → `leka-core.com` → Zone DNS:
   - the **A** record of `leka-core.com` itself (sous-domaine vide): change
     its target from OVH's hosting to the Elastic IP, `3.78.172.119`;
   - **delete** any **AAAA** record of `leka-core.com` and of `www`: OVH
     adds one for its hosting, and a visitor on IPv6 would still reach the
     old site;
   - `www`: a **CNAME** to `leka-core.com.` (or an A to the Elastic IP);
   - leave `app`, `api`, **MX**, and the **TXT** records (SPF, DKIM, DMARC)
     exactly as they are — the mailbox `support@leka-core.com` depends on
     them.
3. **Wait** until `dig +short leka-core.com` and `dig +short www.leka-core.com`
   both answer `3.78.172.119`, and `dig +short AAAA leka-core.com` answers
   nothing.
4. **On the box**, in `/opt/leka/production.env`:

   ```bash
   LEKA_APP_DOMAIN=leka-core.com
   LEKA_APP_ALIASES=www.leka-core.com, app.leka-core.com
   LEKA_WEB_URL=https://leka-core.com
   LEKA_CORS_ORIGINS=["https://leka-core.com"]
   ```

   then deploy the release already running, so every container reads it —
   Caddy is recreated with the new names and asks for their certificates:

   ```bash
   cd /opt/leka
   bash deploy.sh "$(grep ^LEKA_REGISTRY= production.env | cut -d= -f2)" \
                  "$(grep ^LEKA_RELEASE= production.env | cut -d= -f2)"
   ```

5. **Check**, from a laptop:

   ```bash
   curl -fsSI https://leka-core.com/ | head -1                  # 200
   curl -sI https://app.leka-core.com/overview | grep -i ^location   # https://leka-core.com/overview
   curl -sI https://leka-core.com/login.html | grep -i ^location     # /login
   ```

   and register from the site's "Se connecter": the confirmation email's
   link must open `https://leka-core.com/verify/…`.

Undo: put the four lines back as they were and deploy again; the DNS change
is the only step OVH's side has to reverse.

### Changing the site

The site is `web/public/` — `index.html`, the other pages (`a-propos.html`,
`faq.html`, `connecteurs.html`…), `style.css`, `script.js`, `i18n.js` and
`site-i18n.js`, the video `LEKA.mp4` and its poster, `robots.txt`,
`sitemap.xml`. It is changed through a pull request like any file, no
longer by FTP: whatever is uploaded to the old hosting is no longer what
anyone sees. Two things to know before editing it:

- **It shares the application's origin.** A script on any of its pages runs
  with the same rights as the application's own. Nothing on the site may
  put text from the address, a form or a third party into the page as HTML;
  its scripts today only ever insert their own translations.
- **Names the application uses are taken**: no file in `web/public/` named
  like one of its routes (`login`, `register`, `overview`…), and no link to
  `login.html` expected to show a page.

**When Karim hands over a new version** (as the `leka-site` folder of
2026-10-10), its files replace those in `web/public/`, and three things are
made again — `e2e/site.spec.ts` fails if one is missed:

1. **« Se connecter » links to `/login`**, not `./login.html`: a browser may
   still hold the old hosting's placeholder page under that address.
2. **On a phone, « Se connecter » stays**: the site's `style.css` folds it
   away with the demo button; only the demo button folds — it is the one
   way into the platform from the site.
3. **No `login.html`**: its address redirects to the application's sign-in.
4. **The pricing page** (LEKA-431): `tarifs.html`, `tarifs.css` and
   `tarifs.js` are LEKA's own and stay; each page's header and footer link
   to it (« Tarifs », `nav.tarifs`), the home page's bar too; `i18n.js`
   keeps its `nav.tarifs` and `pricing.*` translations; `demo.html` keeps
   its `enterprise` request type. `e2e/pricing.spec.ts` fails if one is
   missed.
5. **Languages** ([languages.md](languages.md)): `i18n.js` keeps its
   catalogue-driven menu (the site's languages, then the 140), `?lang=`,
   the fallback to English, the `leka-lang` cookie and `leka-lang-now`, and
   the « not translated » notice; `site-i18n.js` falls back to English for
   a language it has no words for; `sitemap.xml` keeps each page's
   alternates by language. `e2e/languages.spec.ts` and `e2e/site.spec.ts`
   fail if one is missed.

And `web/components/auth/site-header.tsx`, the header above the sign-in
screens, follows the site's: the same logo and the same four anchors on
the home page (`#environnement`, `#intention`, `#video`, `#controle` since
2026-10-10).

---

## Payments: Stripe (LEKA-431)

The keys go in `production.env`, and nowhere else:
`LEKA_STRIPE_SECRET_KEY` and `LEKA_STRIPE_WEBHOOK_SECRET` — test keys
(`sk_test_…`) until live payments are opened. After a deployment that
changes `api/leka/billing/catalogue.yaml`, and once per Stripe account:

```bash
dc exec api python -m leka.billing.cli stripe-sync
```

It creates the products, prices, the launch coupon and the customer portal's
settings that are missing, and prints them. The webhook endpoint, its events
and the test-to-live steps: [pricing.md](pricing.md) § 7.

## Agent and skill suggestions (LEKA-501)

What customers send from « Demander une compétence », on the Agents page, is
kept in `capability_suggestions` — never an intention, nothing run on it.
LEKA's team reads it on the box, newest first, one JSON line each (who,
which workspace, the problem, the use case):

```bash
dc exec api python -m leka.capabilities.suggestions list --status received
dc exec api python -m leka.capabilities.suggestions set-status <id> reviewing   # planned, declined, done
```

The workspace sees where each of its suggestions stands. A declined or done
one may be suggested again; one still open may not, and a person sends at
most five a day.

## What is deliberately not here

- **No staging.** One environment. A change is tested by CI and the browser
  suite before it merges, and rolled back by `deploy.sh` if it does not come
  up — but nothing is tried online before users see it.
- **One instance.** Deploying restarts the API and the web app; requests in
  flight are dropped. Two instances and a balancer are the answer when that
  starts to matter — see `adr/014-hosting.md`.
- **No metrics, no alerting.** Sentry catches exceptions. Nothing watches
  queue depth or answers "is it slow". `background.md` already stated that
  assumption; this makes it a deployed fact.
