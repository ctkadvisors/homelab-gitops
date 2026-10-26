# services/

Sidecar microservices that support the v0-clone pipeline and the homelab. Each is independently deployable; most land in the `ai-services` namespace via `../k8s-kustomized/base/ai-services/`.

Read root `../CLAUDE.md` for GitOps rules.

## The 5 services

### `codegen-service/` — active

Next.js project generator. Uses **OpenRouter** (not LocalAI — Jetsons were too slow for codegen). Accessed by `platform-api` via `CODEGEN_URL`.

- TS/Node 18, Express. Entry: `src/index.ts`.
- Endpoints: `POST /generate`, `POST /generate/:model`, `GET /models`, `GET /health`.
- Commands: `npm run dev` (tsx watch), `npm run build` (tsc), `npm test` (jest).
- Deploy: `k8s-kustomized/base/ai-services/codegen-service.yaml`, 1 replica, `nodeSelector: node-type=compute-worker` (elitemini2), port 3001.
- NetworkPolicy restricts ingress to the `platform` namespace; egress is open (external OpenRouter calls).
- Env: `OPENROUTER_API_KEY` (platform-api secret), free-tier models by default (Kimi K2, Llama 3.2 3B, Phi-3 Mini). Paid: Claude 3.5, GPT-4o-mini.

### `doc-ingester/` — active (personal RAG)

Indexes iMessage and Gmail into Qdrant for semantic search over personal documents.

- TS/Node 18, Express. Entry: `src/index.ts`.
- Endpoints: `GET /health`, `POST /api/ingest/imessage`, `GET /api/search?q=...`, `GET /api/status`.
- Commands: `npm run dev`, `npm run build` (uses `tsc + tsc-alias` — **both required** so `@/` path aliases resolve at runtime), `npm test`.
- Deploy: `k8s-kustomized/base/ai-services/doc-ingester.yaml`, port 3002, pins to control-plane.
- Deps: Qdrant (`personal_docs` collection, 768d cosine), PostgreSQL (`doc_ingester` db/user/pw `doc_ingester_secret`), **LocalAI** embeddings via `nomic-embed-text`.
- Gmail: code present but `GMAIL_ENABLED=false` in the cluster manifest. To enable, set `GMAIL_ENABLED=true` + credentials via sealed-secret.
- iMessage: synced from a Mac via `../scripts/imessage-sync.py` (state at `~/.doc-ingester-imessage-state.json`). Requires macOS **Full Disk Access** on Terminal. As of last sync, 135 messages indexed.
- Build: `../scripts/build-doc-ingester.sh`.
- Access from Mac: `kubectl port-forward -n ai-services svc/doc-ingester 30002:3002`.

### `model-manager/` — active (GPU sidecar)

DaemonSet on each Jetson. Manages GGUF model downloads + lifecycle alongside LocalAI.

- Node 20, Express. Entry: `server.js` (no TS).
- Endpoints: `GET /health`, `GET /models` (curated list + HuggingFace fallback), `POST /models/download/:modelId`, status polling.
- Deploy: `k8s-kustomized/base/ai-services/model-manager.yaml` — **DaemonSet**, nodeSelector `nvidia.com/gpu: "true"`, headless Service for per-pod access.
- Curated models: TinyLlama, Phi-2, Mistral, CodeLlama, Llama 3.2, Qwen 2.5, DeepSeek Coder.
- Reads `/models/` mount, health-checks LocalAI at :8080.

### `chris-tts/` — active but not in Kustomize

Text-to-speech on Jetson2 using Qwen3-TTS with a cloned voice. WhatsApp-optimized (OGG Opus).

- Python / FastAPI / PyTorch (float16). Entry: `main.py`.
- Endpoints: `POST /synthesize`, `GET /health`, `GET /`.
- Runs on jetson2, port 8000 (NodePort 31800). Dockerfile extends `qwen-tts:jetson` base image. Uses ~7.4 GB GPU memory.
- **No manifest in `k8s-kustomized/`** — deployed historically. If you rebuild, check what actually runs in-cluster (`kubectl -n ai-services get pods | grep tts`) and consider moving to Kustomize rather than adding new imperative state.

### `ai-dev-container/` — legacy / inactive

Ephemeral Node 20 dev environment for AI to generate projects in. Superseded by `codegen-service`.

- No package scripts of note; built via `./build.sh` (buildx multi-platform).
- No k8s manifests. Last commit ~9 months ago.
- Scripts inside: `init-project.sh`, `run-dev.sh`, `commit-changes.sh`.
- **Don't build on this** — either remove or clearly repurpose before extending.

## Shared patterns

- **Registry**: All Node services push to `git.example.com/homelab/<image>:<tag>`. Build with `--platform linux/amd64 --provenance=false --sbom=false` (Gitea registry rejects attestations).
- **Pull auth**: `gitea-registry-secret` (imagePullSecret).
- **Health checks**: all services expose `/health` and have liveness/readiness probes.
- **TS stack**: `codegen-service` and `doc-ingester` share a near-identical setup (ES2020, CommonJS, strict mode, path aliases). Use one as a template for new services.
- **Helmet + CORS + Morgan** stack in every Node service.
- **Non-root user**, readOnlyRootFilesystem, dropAllCapabilities in the k8s SecurityContext.

## When to add vs. extend

Prefer extending `codegen-service` or `doc-ingester` over spinning a new service. Each new service adds: a Dockerfile, a build script, a Kustomize manifest, a namespace entry, registry auth, monitoring — and none of it is free. If you add one, add its CLAUDE.md alongside the source.
