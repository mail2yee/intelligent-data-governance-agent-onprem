# GKE demo deployment

**This is not the air-gapped office target** — see the repo root
`HANDOFF.md`'s "Why this repo exists" section. This directory exists
purely so the app can run somewhere with a real public IP, for
demoing/showing people. It's a from-scratch, hand-written port of
`docker-compose.yml` + `docker-compose.camunda.yml` +
`datahub/docker-compose.datahub.yml` to Kubernetes manifests — every
stateful service (MariaDB, DataHub's own MySQL/OpenSearch/Kafka) is a
`StatefulSet` with a `PersistentVolumeClaim`, not just a container with
a bind mount, since that's the actual K8s-native pattern (unlike
`docker-compose.yml`'s comment warning against self-hosting a database
like this in K8s — that warning was about the *shortcut* of a plain
container-with-a-volume, not about self-hosting itself; a proper
StatefulSet+PVC doesn't have that problem).

## What's actually been verified (and what hasn't)

I (Claude) don't have GCP credentials or a real cluster to test
against, so I installed `kind` (a local single-node K8s cluster running
in Docker) on this dev machine and applied every manifest for real -
not just `kubectl apply --dry-run`. That caught four genuine bugs that
schema/syntax validation alone would have missed, all fixed in the
manifests as they stand now:

1. **`bitnami/kubectl:1.30` doesn't exist** (Bitnami restructured their
   tagging, only `latest` and digest tags remain) - switched to
   `rancher/kubectl:v1.32.13`, which has real version tags.
2. **That image also has no shell** (`sh: not found`) - the
   `wait-for-system-update` initContainers were rewritten from a shell
   polling loop to `kubectl wait --for=condition=complete`, which needs
   no shell and is the more correct tool for the job anyway.
3. **Kafka's own listener config referencing the Service name deadlocked
   at startup** - binding `KAFKA_LISTENERS` to the Service name (ported
   directly from compose's `hostname: broker` trick, which only worked
   because the container's own hostname literally was "broker") fails
   with "Unresolved address" in K8s. Fixed: `KAFKA_LISTENERS` binds
   `0.0.0.0`, `KAFKA_ADVERTISED_LISTENERS`/`KAFKA_CONTROLLER_QUORUM_VOTERS`
   use the StatefulSet pod's own stable per-instance DNS name
   (`datahub-kafka-0.datahub-kafka`) - plus `publishNotReadyAddresses: true`
   on the Service, since that per-pod DNS entry doesn't exist until
   the pod is Ready by default, and the broker needs to resolve it
   *before* it can become Ready (self-referential chicken-and-egg,
   confirmed by testing - it crash-loops forever without this).
4. **K8s auto-injects a `$<SERVICE>_PORT` env var for every Service in
   the namespace into every pod** (legacy Docker-links behavior) -
   `DATAHUB_GMS_PORT` (this app's own literal `"8080"`) got silently
   clobbered by K8s's auto-injected `DATAHUB_GMS_PORT=tcp://<ip>:8080`
   for the `datahub-gms` Service of the same name, crashing GMS's
   Spring Boot config binder (expected an int, got a URL). Fixed with
   `enableServiceLinks: false` on every pod in this directory - the
   general recommended practice for exactly this reason, not just a
   one-off patch for GMS specifically.
5. Also applied `publishNotReadyAddresses: true` to the `datahub-gms`
   Service itself, same root cause as Kafka's - GMS calls back into its
   own `KAFKA_SCHEMAREGISTRY_URL` (`http://datahub-gms:8080/...`) as
   the literal last step of its own startup, which needs the Service to
   route to this not-yet-Ready pod. **This one is diagnosed from a
   clean, consistent, 100%-reproducible crash (same stack trace every
   time, ruled out memory pressure as the cause by freeing up the node
   and seeing it recur identically) but I ran out of local machine
   resources (this kind cluster competing with the same laptop's
   already-running local dev Docker Compose stack) before I could
   re-confirm the fix actually resolves it** - the diagnosis matches
   the Kafka case exactly and I'm confident in it, but flagging the gap
   honestly rather than claiming a clean verification that didn't
   finish.

**Not verified even locally** (things `kind` can't tell you, or that I
didn't get to): the `backend`/`frontend` images are amd64-only and
can't actually run on this Mac's arm64 `kind` node (`ImagePullBackOff:
no match for platform in manifest`) - this is expected to work fine on
real GKE nodes (amd64), but wasn't directly confirmed here. The
`LoadBalancer` Service for `frontend` (external IP provisioning is a
real cloud-provider feature `kind` doesn't replicate). Real resource
sizing at scale without a resource-starved single-node test cluster
fighting other processes for memory. **Treat this as a well-tested
first draft, not a fully proven deployment** - the four-and-a-half bugs
above are exactly the kind of thing that would otherwise have first
surfaced while burning real GKE compute time; there could still be
GKE-specific issues (LoadBalancer quota, node image differences, etc.)
neither `kind` nor I could catch.

## Real cost warning

This is not a one-time cost. A GKE cluster sized for this stack (see
node sizing below) runs continuously for as long as it exists — DataHub
alone (Kafka + OpenSearch + MySQL + GMS + frontend + actions) is
genuinely heavy, the same JVM-heavy stack that got OOM-killed multiple
times in local Docker testing (see `HANDOFF.md`). **Delete the cluster
when you're not actively demoing it** (see "Tearing down" below) unless
you're fine with the ongoing bill.

## 1. Prerequisites (you do this part - I can't touch billing/OAuth)

1. Create or pick a GCP project at https://console.cloud.google.com,
   with billing enabled.
2. Install the CLI: `brew install --cask google-cloud-sdk`
3. `gcloud auth login` (opens a browser, your Google account)
4. `gcloud config set project <your-project-id>`
5. Enable the required APIs:
   ```bash
   gcloud services enable container.googleapis.com compute.googleapis.com
   ```

## 2. Create the cluster

Two options - pick one:

**GKE Standard** (you manage node pool sizing, generally cheaper per
resource but more to think about):
```bash
gcloud container clusters create dgo-demo \
  --zone=us-central1-a \
  --num-nodes=3 \
  --machine-type=e2-standard-4 \
  --disk-size=50
```
3x e2-standard-4 (4 vCPU/16GB each = 12 vCPU/48GB total) comfortably
covers this stack's combined resource *requests* (~3.9 vCPU / ~8.5Gi
across every Deployment/StatefulSet below, excluding the one-shot
system-update Job) with room for GKE's own system pods and request/limit
headroom. Adjust `--zone`/machine type to whatever's cheapest in your
region.

**GKE Autopilot** (no node pool decisions, pay per pod resource
request, simpler to reason about, usually similar-to-slightly-higher
cost for a small cluster like this):
```bash
gcloud container clusters create-auto dgo-demo --region=us-central1
```

Either way, get `kubectl` pointed at it:
```bash
gcloud container clusters get-credentials dgo-demo --zone=us-central1-a  # Standard
# or --region=us-central1 for Autopilot
```

## 3. Secrets (you fill these in - don't commit the real files)

```bash
cp k8s/db-secret.env.example k8s/db-secret.env
cp k8s/backend-secret.env.example k8s/backend-secret.env
# edit both - see the comments in each for what actually matters
# (MARIADB_PASSWORD must match between the two files; LLM_BASE_URL
# needs a real internet-reachable endpoint or AI-mode search will only
# ever show the graceful-fallback path)
```

Apply the namespace and RBAC first (secrets need the namespace to
exist), then the secrets themselves:
```bash
kubectl apply -f k8s/00-namespace.yaml
kubectl create secret generic dgo-db-secret -n dgo --from-env-file=k8s/db-secret.env
kubectl create secret generic dgo-backend-secret -n dgo --from-env-file=k8s/backend-secret.env
```

## 4. Deploy everything

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

## 5. Get the public URL

```bash
kubectl get svc -n dgo frontend
```
The `EXTERNAL-IP` column is your public URL once it's no longer
`<pending>` (GCP provisioning a load balancer takes a minute or two).
Open `http://<EXTERNAL-IP>` in a browser.

**Then go back and fix `CORS_ORIGINS`**: edit `k8s/backend-secret.env`
with this real external IP, re-create the secret, and restart backend:
```bash
kubectl delete secret dgo-backend-secret -n dgo
kubectl create secret generic dgo-backend-secret -n dgo --from-env-file=k8s/backend-secret.env
kubectl rollout restart deployment/backend -n dgo
```

## 6. Seed DataHub's catalog

Same script as local dev (`datahub/seed_catalog.py`), just needs GMS
reachable - port-forward it temporarily rather than exposing it
publicly:
```bash
kubectl port-forward -n dgo svc/datahub-gms 18080:8080 &
DATAHUB_API_URL=http://localhost:18080 python3 datahub/seed_catalog.py
kill %1  # stop the port-forward
```

## Tearing down

**Do this when you're done demoing** - see the cost warning above.
```bash
gcloud container clusters delete dgo-demo --zone=us-central1-a  # or --region for Autopilot
```
This deletes everything including the PersistentVolumeClaims' backing
disks - there's no data here worth keeping (it's a demo catalog seeded
from a script, and tickets/approvals created during a demo aren't
meant to persist). If you want to keep the cluster around cheaper
between demos instead of deleting it, scale everything to 0 replicas
(`kubectl scale --replicas=0 -n dgo deployment --all
statefulset --all`) - the persistent disks (and their small ongoing
cost) stick around, but compute cost drops to ~0.

## What's deliberately different from local dev / office mode

- No `--office`-style config-fallback branch here - this always
  self-hosts everything (Camunda, DataHub, MariaDB), since there's no
  "company's real instance" to fall back to from inside GCP.
- DataHub's own UI (`datahub-frontend`, port 9002) is **not** exposed
  externally by default (`ClusterIP`, not `LoadBalancer`) - it's an
  internal debugging tool, not part of the public demo surface. Give it
  a `LoadBalancer` Service (copy `04-frontend.yaml`'s pattern) if you
  want to browse it directly.
- Camunda has no persistent volume (matches `docker-compose.camunda.yml` -
  it never had one either) - its embedded H2 database is lost on pod
  restart. Fine for a demo; revisit with a real external process-engine
  DB if this needs to survive restarts with in-flight tickets intact.
