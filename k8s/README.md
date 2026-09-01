# GKE demo deployment

**This is not the air-gapped office target** — see the repo root
`HANDOFF.md`'s "Why this repo exists" section. This directory exists
purely so the app can run somewhere with a real public URL, restricted
to a specific person, for demoing. It's a from-scratch, hand-written
port of `docker-compose.yml` + `docker-compose.camunda.yml` +
`datahub/docker-compose.datahub.yml` to Kubernetes manifests — every
stateful service (MariaDB, DataHub's own MySQL/OpenSearch/Kafka) is a
`StatefulSet` with a `PersistentVolumeClaim`, not just a container with
a bind mount, since that's the actual K8s-native pattern (unlike
`docker-compose.yml`'s comment warning against self-hosting a database
like this in K8s — that warning was about the *shortcut* of a plain
container-with-a-volume, not about self-hosting itself; a proper
StatefulSet+PVC doesn't have that problem).

**This has been deployed for real** against a live GKE cluster
(`data-governance-agent` project, `dgo-demo` cluster, `asia-east1-a`),
not just validated locally — see "What's actually running" below for
the real, current state and the real bugs hit getting there.

## What's actually running

- **12 app workloads** (mariadb, camunda, backend, frontend,
  `fab-business-db`, DataHub's 7 services) all `1/1 Running`, zero
  restarts, confirmed stable.
- **Public URL**: `https://idg-ai.yeeshen.com`, real Google-managed TLS
  (Certificate Manager, `ACTIVE` status), restricted via **Identity-Aware
  Proxy** to a single Google account (`mail2yee@gmail.com`) - anyone
  else hitting the URL gets Google's own login wall, never reaches the
  app. **Confirmed end-to-end by actually logging in through it**, not
  just checked via `curl` - the full flow (HTTPS → Google login →
  IAP → app) works.
- **LLM**: Anthropic's OpenAI-compatible endpoint
  (`https://api.anthropic.com/v1`, model `claude-sonnet-5`) - this
  cluster has no route back to the office network or a home Ollama
  instance, so a real internet-reachable LLM was required for AI-mode
  search to actually work rather than always hitting the
  graceful-fallback path.
- **2026-09-01: caught up to every backend/app feature landed since the
  initial 2026-08-30 deployment** (multi-turn clarification, real
  NL-to-SQL against business data, personal chat preference memory, KM
  answering) - the demo had been sitting on the 2026-08-30 image the
  whole time (`imagePullPolicy: Always` only repulls on a new pod, it
  doesn't retroactively update already-running ones). Added
  `17-fab-business-db.yaml` (a new Postgres StatefulSet for the
  NL-to-SQL feature - see `backend/app/integrations/business_data.py`)
  and the matching env vars/initContainer in `03-backend.yaml`, rebuilt
  and pushed fresh `backend`/`frontend` images, then `kubectl apply -f
  k8s/` + `kubectl rollout restart deployment/backend deployment/frontend
  -n dgo`. **Proactively avoided a real bug before it could happen**:
  the exact same GCE-Persistent-Disk `lost+found` issue already hit and
  fixed for Kafka (see "GKE-specific bugs" below) also applies to
  Postgres's `initdb` - fixed via `PGDATA=/var/lib/postgresql/data/pgdata`
  (an empty subdirectory of the PVC) before ever deploying, confirmed
  clean on the real disk (seed data loaded correctly on first try, no
  `lost+found`-related failure). Verified live end-to-end against the
  real Claude-backed deployment (not just pod health): a real KM policy
  question answered correctly with a citation and a follow-up; the
  NL-to-SQL registry/approval gates both correctly blocked, then a real
  approved ticket's query returned real aggregated rows from
  `fab-business-db`; and a preference-revealing chat message got
  correctly extracted and persisted (Claude extracted *two* preferences
  from one exchange - topic and reply-language - a genuinely more
  capable extraction than the local Ollama judge model managed in
  `backend/evals/EVAL_LOG.md`'s local testing).
- **2026-09-02: swapped the static IP after a corporate web filter
  miscategorized the original one as gambling.** `dgo-demo-ip`
  (`136.68.20.162`) got blocked by a company proxy under a "gambling"
  category - almost certainly stale reputation inherited from whichever
  GCP customer had this address before Google reclaimed it into the
  shared pool and reassigned it here, not anything about this app or
  domain (a real, known risk with cloud-provider IP churn - third-party
  web-filter categorization databases don't always get updated when an
  IP changes hands). Fixed by reserving a new address
  (`gcloud compute addresses create dgo-demo-ip-2 --global`,
  `34.102.255.78`) and pointing `15-gateway.yaml`'s `Gateway.spec.addresses`
  at its name instead - the Gateway references addresses by name, not
  literal IP, so this was the only manifest change needed; the
  Certificate Manager cert map entry is keyed by hostname
  (`idg-ai.yeeshen.com`), not IP, so it needed no changes at all.
  Verified the new address serves correctly (valid TLS handshake, real
  cert, IAP challenge responds) *before* touching the old one - **note
  for testing this yourself**: `curl`'s `--resolve` trick only forces
  the correct SNI/Host header when the URL itself uses the hostname
  (`https://idg-ai.yeeshen.com --resolve idg-ai.yeeshen.com:443:<ip>`) -
  putting the literal IP directly in the URL sends no SNI at all and
  the TLS handshake fails with `SSL_ERROR_SYSCALL`, which looks
  identical to a real routing failure and cost real debugging time
  here. `dgo-demo-ip` was kept reserved (not released) until DNS was
  confirmed repointed at the new address and the site confirmed working
  end-to-end through the real hostname (both `curl` and an actual
  logged-in browser session) - once confirmed, released via
  `gcloud compute addresses delete dgo-demo-ip --global`.
  `dgo-demo-ip-2` (`34.102.255.78`) is the address actually in use now.

## The real routing story: classic Ingress is abandoned, this uses Gateway API

The original plan was `networking.k8s.io/v1 Ingress` (`ingressClassName:
gce`) + a `networking.gke.io/v1 ManagedCertificate` + a
`cloud.google.com/v1 BackendConfig` for IAP - the traditional GKE HTTP(S)
load balancing stack. **This never worked, on two separate clusters**:
the legacy Ingress-GCE controller never processed the Ingress object at
all - zero sync events, zero NEG ever created, even on a cluster created
fresh with the `HttpLoadBalancing` addon explicitly enabled from
creation. This is a GKE control-plane issue with no CLI-visible
diagnostics (the controller itself runs inside Google's managed control
plane, not as an inspectable pod) - not a manifest bug, confirmed by a
plain L4 `type: LoadBalancer` Service working perfectly on the same
cluster the whole time.

**Fixed by switching to Gateway API** (`gateway.networking.k8s.io/v1
Gateway` + `HTTPRoute`, GKE's own current recommended direction, a
genuinely different controller/codepath from the broken one) - this
worked immediately on the first attempt. The three files this
architecture actually uses:

- **`15-gateway.yaml`** - the `Gateway` (bound to the pre-reserved
  static IP, TLS via Certificate Manager) and the `HTTPRoute` (routes
  `idg-ai.yeeshen.com` to the `frontend` Service).
- **`16-gcp-backend-policy.yaml`** - `networking.gke.io/v1
  GCPBackendPolicy`, the Gateway-API-native way to turn on IAP (replaces
  `BackendConfig`, which is Ingress-only).
- TLS itself is **Certificate Manager** (a separate GCP resource, not
  the `ManagedCertificate` CRD, which only classic Ingress understands)
  - see "Setup" below for the exact `gcloud certificate-manager`
  commands.

`12-managed-cert.yaml`, `13-backendconfig.yaml`, and `14-ingress.yaml`
existed briefly during the abandoned classic-Ingress attempt and have
been deleted from this directory entirely - if you see references to
them anywhere (old commit messages, etc.), they're dead history, not
something to recreate.

**One non-obvious GCPBackendPolicy gotcha**: it wants the OAuth client
ID inline in the policy spec and the referenced Secret to contain
**only** the `client_secret` key - not both `client_id`/`client_secret`
together the way `BackendConfig` wanted. Confirmed via
`kubectl explain gcpbackendpolicy.spec.default.iap` against the live
CRD (not assumed) after hitting `"must have exactly 1 key-value pair in
field Data, found 2"` with a two-key secret.

## 1. Prerequisites (you do this part - I can't touch billing/OAuth)

1. Create or pick a GCP project at https://console.cloud.google.com,
   with billing enabled.
2. Install the CLI: `brew install --cask google-cloud-sdk`
3. `gcloud auth login` (opens a browser, your Google account)
4. `gcloud config set project <your-project-id>`
5. Enable the required APIs:
   ```bash
   gcloud services enable container.googleapis.com compute.googleapis.com \
     iap.googleapis.com cloudresourcemanager.googleapis.com \
     certificatemanager.googleapis.com
   ```
6. **A real domain you control**, with the ability to add an A record.
   IAP requires HTTPS, and a Google-managed cert needs DNS actually
   pointed at the reserved static IP before Google will issue one - see
   step 4 below for the exact order this has to happen in.
7. **gke-gcloud-auth-plugin** - `kubectl` needs this to authenticate
   against GKE:
   ```bash
   gcloud components install gke-gcloud-auth-plugin
   export PATH="$(gcloud info --format='value(installation.sdk_root)')/bin:$PATH"
   # add that export to ~/.zshrc to make it permanent
   ```

## 2. Reserve a static IP

```bash
gcloud compute addresses create dgo-demo-ip --global
gcloud compute addresses describe dgo-demo-ip --global --format="value(address)"
```
Point your domain's A record at this IP now (see step 4) - DNS
propagation can take a few minutes, so start it early. **Use "DNS
only"/unproxied mode if your DNS provider offers a proxy option (e.g.
Cloudflare)** - a proxy would make Google's domain-ownership
verification see the proxy's IP instead of this one, and the managed
certificate will get stuck in `FAILED_NOT_VISIBLE` forever.

## 3. Set up IAP (manual - the automation API for this is deprecated/shut down)

`gcloud iap oauth-brands` is deprecated and the underlying IAP OAuth
Admin API is being shut down by Google (announced shutdown as of early
2026) - this genuinely has to be done by hand in the Console:

1. **OAuth consent screen**: https://console.cloud.google.com/apis/credentials/consent
   - User Type: External. Fill in app name + support/contact email.
     Add your own Google account under **Test users**.
2. **OAuth client**: https://console.cloud.google.com/apis/credentials
   → Create Credentials → OAuth client ID → Web application. Create it
   first with no redirect URI, copy the resulting **Client ID** and
   **Client Secret**, then come back and add this as an Authorized
   redirect URI (substituting your real client ID):
   ```
   https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect
   ```
3. Save the client ID/secret somewhere local and **gitignored**
   (`k8s/.local-secrets/` is already in `.gitignore` for exactly this) -
   you'll need the secret (not the ID) to create a K8s Secret in step 5,
   and the ID goes inline in `16-gcp-backend-policy.yaml`.

## 4. Create the cluster

**The `HttpLoadBalancing` addon and Gateway API must both be enabled** -
without them, nothing here can create a real load balancer:
```bash
gcloud container clusters create dgo-demo \
  --zone=asia-east1-a \
  --num-nodes=2 \
  --machine-type=e2-standard-4 \
  --disk-size=50 \
  --spot \
  --addons=HttpLoadBalancing \
  --gateway-api=standard
```
2x e2-standard-4 (4 vCPU/16GB each = 8 vCPU/32GB total) comfortably
covers this stack's combined resource *requests* (~3.9 vCPU / ~8.5Gi
across every Deployment/StatefulSet, excluding the one-shot
system-update Job). `--spot` cuts compute cost significantly (60-90%)
in exchange for GCP being able to reclaim the VM with short notice -
fine for a demo, not for something that needs to survive unattended.
Adjust `--zone`/machine type/region to whatever's cheapest or closest
to you.

```bash
gcloud container clusters get-credentials dgo-demo --zone=asia-east1-a
```

If you already have a cluster without these addons, `gcloud container
clusters update dgo-demo --zone=... --update-addons=HttpLoadBalancing=ENABLED
--gateway-api=standard` should work in theory - in practice, toggling
addons on an existing cluster is exactly what triggered the broken,
unrecoverable Ingress-GCE controller state described above. If Gateway
API's own health checks (`kubectl get gatewayclass`,
`kubectl describe gateway`) show anything stuck or silent the way
classic Ingress did, don't spend hours debugging it via CLI the way this
session did - just delete and recreate the cluster. It's a demo
cluster; there's no state on it worth preserving.

## 5. Certificate Manager (Gateway API's TLS mechanism - NOT the ManagedCertificate CRD)

```bash
gcloud certificate-manager certificates create dgo-demo-gw-cert \
  --domains=<your-domain>
gcloud certificate-manager maps create dgo-demo-cert-map
gcloud certificate-manager maps entries create dgo-demo-cert-map-entry \
  --map=dgo-demo-cert-map --certificates=dgo-demo-gw-cert \
  --hostname=<your-domain>
```
Then edit `15-gateway.yaml`'s `networking.gke.io/certmap` annotation and
`HTTPRoute`'s `hostnames` to match your actual domain (both currently
say `idg-ai.yeeshen.com`). Provisioning can take up to ~1 hour after DNS
actually resolves to the static IP - check status with:
```bash
gcloud certificate-manager certificates describe dgo-demo-gw-cert --format="value(managed.state)"
```
`ACTIVE` means it's really done; `FAILED_NOT_VISIBLE` almost always
means DNS isn't pointed at the static IP yet (or is going through a
proxy - see step 2).

## 6. Secrets (you fill these in - don't commit the real files)

```bash
cp k8s/db-secret.env.example k8s/db-secret.env
cp k8s/backend-secret.env.example k8s/backend-secret.env
# edit both - MARIADB_PASSWORD must match between the two files.
# LLM_BASE_URL needs a real internet-reachable endpoint (this cluster
# can't reach a home Ollama or the office network) - Anthropic's
# OpenAI-compatible endpoint (https://api.anthropic.com/v1) is
# confirmed working, e.g. LLM_MODEL=claude-sonnet-5.
# CORS_ORIGINS should be https://<your-domain> (not http, not the bare IP).
```

```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl create secret generic dgo-db-secret -n dgo --from-env-file=k8s/db-secret.env
kubectl create secret generic dgo-backend-secret -n dgo --from-env-file=k8s/backend-secret.env
```

**IAP secret - note the single-key requirement** (see the gotcha
above):
```bash
kubectl create secret generic iap-oauth-secret -n dgo \
  --from-literal=client_secret=<your-oauth-client-secret>
```
Then edit `16-gcp-backend-policy.yaml`'s `clientID` field to your real
OAuth client ID (it's fine for this to be inline/committed - client IDs
aren't secret, only the client secret is).

## 7. Deploy everything

```bash
kubectl apply -f k8s/
```
(Numeric filename prefixes are just for human readability when
browsing the directory - `kubectl apply -f k8s/` applies all of them
together regardless of order; K8s itself handles dependency ordering
at runtime via the `initContainers` wait-loops baked into each
manifest, not via apply order.)

Watch it come up:
```bash
kubectl get pods -n dgo -w
```
Expect this rough order: `datahub-mysql`/`datahub-opensearch`/
`datahub-kafka`/`mariadb`/`camunda` become Ready first → `datahub-system-update`
Job runs and completes → `datahub-gms`/`datahub-frontend` start (their
initContainers were blocked on that Job) → `datahub-actions` starts →
`backend` starts (blocked on `mariadb` + `camunda`) → `frontend` starts.
DataHub's own stack alone can take several minutes cold-starting (GMS's
readinessProbe alone allows up to 150s).

Then confirm the Gateway actually programmed:
```bash
kubectl get gateway -n dgo dgo-demo-gateway
# PROGRAMMED should say True, ADDRESS should match your reserved static IP
kubectl describe gcpbackendpolicy -n dgo frontend-iap-policy
# look for "Type: Attached, Status: True" in Conditions
```

## 8. Seed DataHub's catalog

Same script as local dev (`datahub/seed_catalog.py`), just needs GMS
reachable - port-forward it temporarily rather than exposing it
publicly:
```bash
kubectl port-forward -n dgo svc/datahub-gms 18080:8080 &
DATAHUB_API_URL=http://localhost:18080 python3 datahub/seed_catalog.py
kill %1  # stop the port-forward
```

## 9. Authorize who can actually log in via IAP

Enabling IAP alone blocks everyone - you still need to grant specific
Google accounts access to get past the login wall. First find the real
backend service name Gateway API generated (it does NOT use the
`k8s1-...` naming classic Ingress would have - Gateway API's own names
look like `gkegw1-<hash>-<namespace>-<service>-<port>-<hash>`):
```bash
gcloud compute backend-services list
```
Then grant access to that exact name:
```bash
gcloud iap web add-iam-policy-binding \
  --resource-type=backend-services \
  --service=<the gkegw1-... name from the list above> \
  --member=user:<email> \
  --role=roles/iap.httpsResourceAccessor
```
**Two real failure modes hit getting this working, in order**:
1. OAuth login itself failing with `Error 400: redirect_uri_mismatch` -
   this means the Authorized redirect URI saved on the OAuth client
   (step 3 above) doesn't exactly match
   `https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect`
   character-for-character (a stray trailing slash or a forgotten Save
   click are the usual causes) - fix it in the Console and retry.
2. Login succeeds but IAP still shows **"You don't have access"** even
   for an account you already ran `add-iam-policy-binding` for - this
   means the binding was granted against the *wrong* backend service
   name (e.g. a stale one from an earlier classic-Ingress attempt, or a
   guessed `k8s1-...` name). Re-run `gcloud compute backend-services
   list`, confirm which backend service the Gateway/HTTPRoute is
   actually using right now, and re-run the binding against that exact
   name.

## Tearing down

**Do this when you're done demoing** - see the cost warning below.
```bash
gcloud container clusters delete dgo-demo --zone=asia-east1-a
# dgo-demo-ip-2 is the address actually in use as of 2026-09-02 (see
# "What's actually running" above) - the original dgo-demo-ip was
# released the same day after the swap was confirmed working.
gcloud compute addresses delete dgo-demo-ip-2 --global
gcloud certificate-manager maps entries delete dgo-demo-cert-map-entry --map=dgo-demo-cert-map
gcloud certificate-manager maps delete dgo-demo-cert-map
gcloud certificate-manager certificates delete dgo-demo-gw-cert
```
Deleting the cluster removes everything including the PersistentVolumeClaims'
backing disks - there's no data here worth keeping (it's a demo catalog
seeded from a script, and tickets/approvals created during a demo
aren't meant to persist). If you want to keep the cluster around
cheaper between demos instead of deleting it, scale everything to 0
replicas (`kubectl scale --replicas=0 -n dgo deployment --all
statefulset --all`) - the persistent disks (and their small ongoing
cost) stick around, but compute cost drops to ~0. The static IP,
certificate, and OAuth client are cheap/free to leave alone between
demos either way.

## Real cost warning

This is not a one-time cost. A GKE cluster sized for this stack runs
continuously for as long as it exists — DataHub alone (Kafka +
OpenSearch + MySQL + GMS + frontend + actions) is genuinely heavy, the
same JVM-heavy stack that got OOM-killed multiple times in local Docker
testing (see `HANDOFF.md`). **Delete the cluster when you're not
actively demoing it** unless you're fine with the ongoing bill.

## What's deliberately different from local dev / office mode

- No `--office`-style config-fallback branch here - this always
  self-hosts everything (Camunda, DataHub, MariaDB), since there's no
  "company's real instance" to fall back to from inside GCP.
- LLM is a real internet-reachable endpoint (Anthropic), not the local
  Ollama or company gateway assumption the rest of this repo defaults
  to - see `backend-secret.env.example`'s comment.
- DataHub's own UI (`datahub-frontend`, port 9002) is **not** exposed
  externally - it's an internal debugging tool, not part of the public
  demo surface. Use `kubectl port-forward` if you need to browse it.
- Camunda has no persistent volume (matches `docker-compose.camunda.yml` -
  it never had one either) - its embedded H2 database is lost on pod
  restart. Fine for a demo; revisit with a real external process-engine
  DB if this needs to survive restarts with in-flight tickets intact.
- Public access is gated by IAP (Google account allowlist), not a bare
  public IP - this is meant for a specific person to see, not a general
  public demo.

## GKE-specific bugs found deploying this for real (beyond the routing story above)

These only showed up against real GCE Persistent Disks - `kind`'s
local-path provisioner never surfaced them (see the manifest comments
for the fixes actually applied):

- **`datahub-kafka` and `datahub-opensearch` both run as a non-root
  UID** (1000) and can't write to a freshly-mounted real PD, which
  mounts root-owned by default - fixed with `securityContext.fsGroup: 1000`
  on both StatefulSets.
- **GCE Persistent Disks are freshly formatted ext4**, which always
  creates a `lost+found` directory at the volume root - Kafka's
  LogManager scans every entry expecting topic-partition directories
  and fatal-errors on anything else. Fixed by `rm -rf
  /var/lib/kafka/data/lost+found` at the start of the kafka container's
  startup command.
- **The GHCR `backend:latest` image was stale** (built before this
  repo's Postgres→MariaDB migration, missing `asyncmy` entirely,
  `ModuleNotFoundError` on startup) - rebuilt and re-pushed via `docker
  compose build backend && docker compose push backend` once this was
  caught; a reminder to actually rebuild+push after dependency changes
  before assuming a `:latest` GHCR tag is current.
- **The same `lost+found`-on-a-fresh-PD issue above also applies to
  Postgres's `initdb`** (2026-09-01, `17-fab-business-db.yaml`) - it
  refuses to initialize into a non-empty data directory, and a bare
  `lost+found` from ext4 formatting is enough to trip that check. Unlike
  the Kafka case, this one was **fixed proactively before ever
  deploying** (recognized the pattern from the bullet above, not
  rediscovered by trial and error) via `PGDATA=/var/lib/postgresql/data/pgdata`
  - the official image supports pointing `PGDATA` at an empty
  subdirectory of the mounted volume natively, no entrypoint script
  changes needed. Confirmed clean on the first real deploy: seed data
  loaded correctly, no failure.
