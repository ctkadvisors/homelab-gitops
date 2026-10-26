# Hermes Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a governed personal agent (Hermes) to the K3s cluster, backed by bare-metal Nemotron-3-Nano-4B inference on jetson1, with NetworkPolicy + ResourceQuota as the foundational governance convention.

**Architecture:** jetson1 leaves K3s and becomes a dedicated systemd-managed Ollama host (`10.0.0.73:11434`). Cluster reaches it via a headless Service + manual Endpoints in `ai-services`. Hermes deploys as a standard K3s Deployment with PVC, SealedSecret, NetworkPolicy, and ResourceQuota. LocalAI collapses to a single replica on jetson2.

**Tech Stack:** Hermes Agent (Python, v0.10+), Ollama (bare-metal), Nemotron-3-Nano-4B Q4_K_M, K3s + Kustomize + ArgoCD, SealedSecrets, NVIDIA Jetson Orin Nano 8GB (JetPack 6.x).

**Spec:** `docs/superpowers/specs/2026-04-18-hermes-agent-design.md`

---

## Risky action gates

These tasks include destructive operations. **Halt for user approval** before running:

- Task 2: `kubectl delete node jetson1` (cluster membership change)
- Task 3: apt purge on jetson1, removes Docker/K3s/NVIDIA runtime
- Task 4: `sudo reboot` on jetson1
- Task 13: Patches LocalAI — user-visible embedding disruption ~30s during rollout

Every other task is additive and safe to execute without confirmation.

---

## Task 1: Audit jetson1 (read-only)

**Files:**
- Create: `/tmp/jetson1-audit-2026-04-18.txt` (local, temporary — discarded after review)

- [ ] **Step 1: Verify SSH connectivity**

Run:
```bash
ssh jetson1 'hostname && uptime && uname -a'
```
Expected: prints `jetson1`, uptime, kernel info. Exit 0.

- [ ] **Step 2: Capture full audit output**

Run:
```bash
ssh jetson1 'bash -s' <<'EOF' | tee /tmp/jetson1-audit-2026-04-18.txt
echo "=== systemd running units ==="
systemctl list-units --state=running --no-pager
echo "=== installed packages (docker/k3s/nvidia/ollama) ==="
dpkg -l | grep -iE 'docker|nvidia-docker|containerd|k3s|localai|ollama' || echo "none"
echo "=== disk ==="
df -h /
du -sh /var/lib/* /opt/* /root/* 2>/dev/null | sort -h | tail -30
echo "=== docker state ==="
docker ps -a 2>&1 | head -20
docker images 2>&1 | head -20
echo "=== cron + timers ==="
crontab -l 2>&1
systemctl list-timers --no-pager
echo "=== GPU / JetPack ==="
cat /etc/nv_tegra_release 2>&1
nvidia-smi 2>&1 | head -10 || echo "nvidia-smi missing"
echo "=== ports listening ==="
ss -tlnp 2>&1 | head -20
EOF
```
Expected: file written, review before proceeding.

- [ ] **Step 3: Review the audit output, flag anything unexpected**

Read `/tmp/jetson1-audit-2026-04-18.txt`. Look for surprises: unknown services, large unexplained data in `/opt` or `/root`, user data that would be lost, active deployments we forgot about.

If anything unexpected: stop and reconcile with the user before proceeding.

- [ ] **Step 4: Commit nothing (audit is read-only)**

No commit. The audit file lives at `/tmp/` only.

---

## Task 2: Drain jetson1 from K3s cluster

**Files:**
- No files changed. Cluster-state operation only.

- [ ] **Step 1: Verify node presence**

Run:
```bash
export KUBECONFIG=./kubeconfig
kubectl get node jetson1 -o wide
```
Expected: jetson1 appears with its IP and Ready status.

- [ ] **Step 2: Cordon**

Run:
```bash
kubectl cordon jetson1
```
Expected: `node/jetson1 cordoned`.

- [ ] **Step 3: Drain (user approval required — workloads migrate)**

Run:
```bash
kubectl drain jetson1 --ignore-daemonsets --delete-emptydir-data
```
Expected: pods evicted, node drained. LocalAI pod on jetson1 terminates; replacement will fail-schedule until Task 13 patches the replica count. Acceptable — jetson2 continues serving embeddings.

- [ ] **Step 4: Delete node record**

Run:
```bash
kubectl delete node jetson1
```
Expected: `node "jetson1" deleted`.

- [ ] **Step 5: Verify**

Run:
```bash
kubectl get nodes
```
Expected: jetson1 absent from the list.

- [ ] **Step 6: Commit nothing (cluster state change only)**

No repo changes yet. Ansible role + network config update happen later.

---

## Task 3: Purge K3s, Docker, NVIDIA container runtime from jetson1

**Files:**
- No files changed in repo. jetson1 host changes only.

- [ ] **Step 1: Stop k3s-agent**

Run:
```bash
ssh jetson1 'sudo systemctl stop k3s-agent && sudo systemctl disable k3s-agent'
```
Expected: no output on success.

- [ ] **Step 2: Uninstall k3s-agent**

Run:
```bash
ssh jetson1 'sudo /usr/local/bin/k3s-agent-uninstall.sh 2>&1 || echo "uninstall script missing — continuing"'
```
Expected: script removes k3s binary, systemd unit, `/var/lib/rancher`. If script is missing, we clean up manually in the next step.

- [ ] **Step 3: Manual cleanup of k3s/kubelet remnants**

Run:
```bash
ssh jetson1 'sudo rm -rf /var/lib/rancher /etc/rancher /var/lib/kubelet /var/lib/cni /etc/cni /opt/cni'
```
Expected: directories removed silently.

- [ ] **Step 4: Purge Docker + NVIDIA container runtime**

Run:
```bash
ssh jetson1 'sudo apt purge -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin docker.io \
  nvidia-docker2 nvidia-container-toolkit nvidia-container-runtime \
  2>&1 | tail -5'
```
Expected: packages purged. Some may not be installed — acceptable.

- [ ] **Step 5: Remove docker state**

Run:
```bash
ssh jetson1 'sudo rm -rf /var/lib/docker /var/lib/containerd /etc/docker'
```

- [ ] **Step 6: LocalAI leftovers**

Run:
```bash
ssh jetson1 'sudo rm -rf /opt/localai /var/lib/localai /root/.localai 2>/dev/null; true'
```

- [ ] **Step 7: Apt housekeeping**

Run:
```bash
ssh jetson1 'sudo apt autoremove --purge -y && sudo apt clean'
```
Expected: unused packages removed, apt cache cleared.

- [ ] **Step 8: Verify disk reclaimed**

Run:
```bash
ssh jetson1 'df -h /'
```
Expected: noticeable free space compared to Task 1 audit.

- [ ] **Step 9: Commit nothing (host state change only)**

---

## Task 4: Refresh L4T / JetPack in place

**Files:**
- No repo changes. jetson1 host changes only.

- [ ] **Step 1: Update apt metadata**

Run:
```bash
ssh jetson1 'sudo apt update 2>&1 | tail -5'
```
Expected: package lists refreshed, no errors.

- [ ] **Step 2: Full upgrade**

Run:
```bash
ssh jetson1 'sudo DEBIAN_FRONTEND=noninteractive apt full-upgrade -y 2>&1 | tail -20'
```
Expected: upgrades complete. Takes 5-20 min depending on how stale.

- [ ] **Step 3: Reinstall JetPack metapackage**

Run:
```bash
ssh jetson1 'sudo apt install --reinstall -y nvidia-jetpack 2>&1 | tail -10'
```
Expected: nvidia-jetpack and dependencies reinstalled. Pulls latest matching JetPack point release.

- [ ] **Step 4: Capture JetPack version post-upgrade**

Run:
```bash
ssh jetson1 'cat /etc/nv_tegra_release'
```
Expected: prints something like `# R36 (release), REVISION: X.Y, ...`. Note the R36 line for the implementation log.

- [ ] **Step 5: Reboot (user approval required)**

Run:
```bash
ssh jetson1 'sudo reboot'
```
Expected: SSH disconnects. Wait ~60s.

- [ ] **Step 6: Verify jetson1 is back**

Run:
```bash
until ssh -o ConnectTimeout=5 jetson1 'uptime' 2>/dev/null; do sleep 5; done
```
Expected: uptime under 2 minutes once connection succeeds.

- [ ] **Step 7: Verify GPU stack intact**

Run:
```bash
ssh jetson1 'nvidia-smi || echo "nvidia-smi missing on Jetson (expected — use tegrastats)" && tegrastats --interval 1000 2>&1 | head -2'
```
Expected: `tegrastats` produces one line of GPU/CPU/RAM stats. That confirms L4T loaded correctly.

---

## Task 5: Install Ollama on jetson1 and pull Nemotron

**Files:**
- No repo changes. jetson1 host changes only.

- [ ] **Step 1: Install Ollama**

Run:
```bash
ssh jetson1 'curl -fsSL https://ollama.com/install.sh | sh 2>&1 | tail -20'
```
Expected: installer prints `>>> Installing ollama to /usr/local/bin`, creates `ollama` user + systemd unit, detects GPU or falls back to CPU.

- [ ] **Step 2: Configure Ollama to bind 0.0.0.0**

Run:
```bash
ssh jetson1 'sudo mkdir -p /etc/systemd/system/ollama.service.d && \
  sudo tee /etc/systemd/system/ollama.service.d/override.conf >/dev/null <<EOF
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF'
ssh jetson1 'sudo systemctl daemon-reload && sudo systemctl restart ollama'
```
Expected: no output on success.

- [ ] **Step 3: Verify Ollama is listening externally**

Run:
```bash
curl -s --max-time 5 http://10.0.0.73:11434/api/tags
```
Expected: JSON `{"models":[]}` or similar. Empty model list is expected before the pull.

- [ ] **Step 4: Verify GPU detection**

Run:
```bash
ssh jetson1 'journalctl -u ollama --no-pager -n 50 | grep -iE "cuda|gpu|compute"'
```
Expected: lines like `CUDA device detected`, `compute capability X.Y`. If output is empty or shows "CPU only", **jump to the fallback path below** (Step 7).

- [ ] **Step 5: Pull Nemotron-3-Nano-4B**

Run:
```bash
ssh jetson1 'ollama pull nemotron3:4b-q4_k_m 2>&1 | tail -5'
```
Expected: progress bar, final "success". Model lands in `/usr/share/ollama/.ollama/models/`.

**If the tag isn't found:** fall back to Unsloth GGUF via Modelfile:
```bash
ssh jetson1 'cat > /tmp/Modelfile <<EOF
FROM unsloth/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M
EOF
ollama create nemotron3:4b-q4_k_m -f /tmp/Modelfile'
```

- [ ] **Step 6: End-to-end inference smoke test**

Run:
```bash
curl -s http://10.0.0.73:11434/api/generate -d '{
  "model": "nemotron3:4b-q4_k_m",
  "prompt": "reply with the word pong",
  "stream": false
}' | python3 -c "import sys,json; d=json.load(sys.stdin); print('response:', d.get('response','')); print('eval_count:', d.get('eval_count')); print('eval_duration_ms:', round(d.get('eval_duration',0)/1e6))"
```
Expected: `response: pong` (or a sensible short response), `eval_count > 0`, sub-second generation time.

- [ ] **Step 7: Fallback — only if GPU detection failed at Step 4**

Install docker + NVIDIA container toolkit, run jetson-containers llama_cpp:
```bash
ssh jetson1 'sudo systemctl stop ollama && sudo systemctl disable ollama'
ssh jetson1 'sudo apt install -y docker.io nvidia-container-toolkit'
ssh jetson1 'sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker'
ssh jetson1 'sudo docker run -d --name nemotron --runtime nvidia --network host --restart unless-stopped \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  ghcr.io/nvidia-ai-iot/llama_cpp:latest-jetson-orin \
  llama-server -hf unsloth/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M --host 0.0.0.0 --port 11434'
```
Verify: `curl -s http://10.0.0.73:11434/v1/models` returns OpenAI-compat JSON.

In this case, **Hermes ConfigMap later uses `openai-compat` provider at the same endpoint**.

- [ ] **Step 8: Commit nothing yet**

Ansible role captures the install (next task).

---

## Task 6: Harden jetson1

**Files:**
- No repo changes. jetson1 host changes only.

- [ ] **Step 1: ufw rules**

Run:
```bash
ssh jetson1 'sudo ufw --force reset && \
  sudo ufw default deny incoming && \
  sudo ufw default allow outgoing && \
  sudo ufw allow from 10.0.0.0/24 to any port 22 proto tcp && \
  sudo ufw allow from 10.0.0.0/24 to any port 11434 proto tcp && \
  sudo ufw allow from 10.0.0.0/24 to any port 9100 proto tcp && \
  sudo ufw --force enable && \
  sudo ufw status'
```
Expected: status `Status: active` with the three allow rules.

- [ ] **Step 2: SSH password auth off**

Run:
```bash
ssh jetson1 'sudo sed -i "s/^#*PasswordAuthentication.*/PasswordAuthentication no/" /etc/ssh/sshd_config && \
  sudo sed -i "s/^#*PermitRootLogin.*/PermitRootLogin no/" /etc/ssh/sshd_config && \
  sudo systemctl restart ssh'
```
Expected: no output. Verify subsequent SSH with your key still works — which it will, since you're on an existing session.

- [ ] **Step 3: unattended-upgrades**

Run:
```bash
ssh jetson1 'sudo apt install -y unattended-upgrades && \
  sudo dpkg-reconfigure -f noninteractive unattended-upgrades'
```
Expected: package installed, defaults configured.

- [ ] **Step 4: Install prometheus-node-exporter**

Run:
```bash
ssh jetson1 'sudo apt install -y prometheus-node-exporter && \
  sudo systemctl enable --now prometheus-node-exporter'
ssh jetson1 'curl -s http://localhost:9100/metrics | head -5'
```
Expected: Prometheus metrics output (`# HELP ...`, `# TYPE ...`).

- [ ] **Step 5: Verify node-exporter reachable from elitemini**

Run:
```bash
ssh elitemini 'curl -s --max-time 3 http://10.0.0.73:9100/metrics | head -3'
```
Expected: metrics output.

- [ ] **Step 6: Commit nothing yet**

---

## Task 7: Create Ansible role for jetson1 (reproducibility)

**Files:**
- Create: `ansible/roles/nemotron-host/tasks/main.yml`
- Create: `ansible/roles/nemotron-host/handlers/main.yml`
- Create: `ansible/roles/nemotron-host/templates/ollama-override.conf.j2`
- Modify: `ansible/inventory/hosts.yml` — jetson1 moves from `k3s_workers` to new `nemotron_hosts` group

- [ ] **Step 1: Create the role scaffolding**

Run:
```bash
mkdir -p ansible/roles/nemotron-host/{tasks,handlers,templates}
```

- [ ] **Step 2: Write `ansible/roles/nemotron-host/tasks/main.yml`**

```yaml
---
# Dedicated Ollama + Nemotron host. Not a K3s node.
# Applied to jetson1 via ansible/playbooks/nemotron-host.yml.

- name: Install prereqs
  become: true
  ansible.builtin.apt:
    name:
      - curl
      - ufw
      - unattended-upgrades
      - prometheus-node-exporter
    state: present
    update_cache: true

- name: Check if ollama is already installed
  ansible.builtin.stat:
    path: /usr/local/bin/ollama
  register: ollama_bin

- name: Install Ollama
  become: true
  ansible.builtin.shell: |
    curl -fsSL https://ollama.com/install.sh | sh
  when: not ollama_bin.stat.exists
  changed_when: true

- name: Configure Ollama to bind 0.0.0.0
  become: true
  ansible.builtin.template:
    src: ollama-override.conf.j2
    dest: /etc/systemd/system/ollama.service.d/override.conf
    owner: root
    group: root
    mode: '0644'
  notify: restart ollama

- name: Enable and start Ollama
  become: true
  ansible.builtin.systemd:
    name: ollama
    enabled: true
    state: started
    daemon_reload: true

- name: ufw default deny incoming
  become: true
  community.general.ufw:
    direction: incoming
    policy: deny

- name: ufw default allow outgoing
  become: true
  community.general.ufw:
    direction: outgoing
    policy: allow

- name: ufw allow SSH from LAN
  become: true
  community.general.ufw:
    rule: allow
    from_ip: 10.0.0.0/24
    to_port: '22'
    proto: tcp

- name: ufw allow Ollama from LAN
  become: true
  community.general.ufw:
    rule: allow
    from_ip: 10.0.0.0/24
    to_port: '11434'
    proto: tcp

- name: ufw allow node-exporter from LAN
  become: true
  community.general.ufw:
    rule: allow
    from_ip: 10.0.0.0/24
    to_port: '9100'
    proto: tcp

- name: ufw enable
  become: true
  community.general.ufw:
    state: enabled

- name: SSH password auth off
  become: true
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    regexp: '^#?PasswordAuthentication'
    line: 'PasswordAuthentication no'
  notify: restart ssh

- name: SSH root login off
  become: true
  ansible.builtin.lineinfile:
    path: /etc/ssh/sshd_config
    regexp: '^#?PermitRootLogin'
    line: 'PermitRootLogin no'
  notify: restart ssh

- name: Ensure node-exporter is running
  become: true
  ansible.builtin.systemd:
    name: prometheus-node-exporter
    enabled: true
    state: started
```

- [ ] **Step 3: Write `ansible/roles/nemotron-host/handlers/main.yml`**

```yaml
---
- name: restart ollama
  become: true
  ansible.builtin.systemd:
    name: ollama
    state: restarted
    daemon_reload: true

- name: restart ssh
  become: true
  ansible.builtin.systemd:
    name: ssh
    state: restarted
```

- [ ] **Step 4: Write `ansible/roles/nemotron-host/templates/ollama-override.conf.j2`**

```
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
```

- [ ] **Step 5: Create playbook `ansible/playbooks/nemotron-host.yml`**

```yaml
---
- name: Configure dedicated Nemotron inference hosts
  hosts: nemotron_hosts
  become: false
  gather_facts: true
  roles:
    - nemotron-host
```

- [ ] **Step 6: Update `ansible/inventory/hosts.yml`**

Move jetson1 from the `k3s_workers` group to a new `nemotron_hosts` group. Exact edit depends on current structure — read the file first and make the minimal change:

Run:
```bash
cat ansible/inventory/hosts.yml | head -30
```

Apply: find the block containing `jetson1` and move it under a new `nemotron_hosts:` group. If `jetson1` appears in multiple groups, remove from `k3s_workers` and any `gpu_workers` group too.

- [ ] **Step 7: Dry-run the playbook**

Run:
```bash
cd ansible
ansible-playbook -i inventory/hosts.yml playbooks/nemotron-host.yml --check --diff
```
Expected: `ok=N changed=0` (because we already applied everything manually in Tasks 5-6). If anything shows `changed`, investigate whether the manual state matches the role's expectation.

- [ ] **Step 8: Commit**

```bash
git add ansible/roles/nemotron-host ansible/playbooks/nemotron-host.yml ansible/inventory/hosts.yml
git commit -m "ansible: add nemotron-host role for jetson1

Captures the bare-metal Ollama + Nemotron-3-Nano-4B setup so jetson1
is reproducible. jetson1 moves from k3s_workers to nemotron_hosts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Create ollama-nemotron Service + Endpoints (in-cluster routing)

**Files:**
- Create: `k8s-kustomized/base/ai-services/ollama-nemotron.yaml`
- Modify: `k8s-kustomized/base/ai-services/kustomization.yaml`

- [ ] **Step 1: Write `k8s-kustomized/base/ai-services/ollama-nemotron.yaml`**

```yaml
---
# Out-of-cluster Ollama endpoint on jetson1 (10.0.0.73:11434).
# No Deployment/Pod — just a Service + manually-managed Endpoints.
apiVersion: v1
kind: Service
metadata:
  name: ollama-nemotron
  namespace: ai-services
  labels:
    app: ollama-nemotron
    app.kubernetes.io/component: inference
spec:
  type: ClusterIP
  ports:
    - name: http
      port: 11434
      protocol: TCP
      targetPort: 11434
---
apiVersion: v1
kind: Endpoints
metadata:
  name: ollama-nemotron
  namespace: ai-services
  labels:
    app: ollama-nemotron
subsets:
  - addresses:
      - ip: 10.0.0.73
    ports:
      - name: http
        port: 11434
        protocol: TCP
```

- [ ] **Step 2: Add to `k8s-kustomized/base/ai-services/kustomization.yaml`**

Read the file first:
```bash
cat k8s-kustomized/base/ai-services/kustomization.yaml
```

Find the `resources:` list and append `- ollama-nemotron.yaml` in alphabetical order.

- [ ] **Step 3: Validate render**

Run:
```bash
kubectl kustomize k8s-kustomized/base/ai-services | grep -A 5 "name: ollama-nemotron"
```
Expected: both Service and Endpoints present in the rendered output.

- [ ] **Step 4: Apply for local validation (not a commit)**

Run:
```bash
kubectl apply -k k8s-kustomized/base/ai-services
```
Expected: `service/ollama-nemotron created` and `endpoints/ollama-nemotron created`.

- [ ] **Step 5: Verify in-cluster DNS resolution**

Run:
```bash
kubectl run --rm -it --restart=Never --image=curlimages/curl:latest dns-test -n ai-services -- \
  curl -s --max-time 5 http://ollama-nemotron.ai-services.svc.cluster.local:11434/api/tags
```
Expected: JSON with the Nemotron model listed.

- [ ] **Step 6: Commit**

```bash
git add k8s-kustomized/base/ai-services/ollama-nemotron.yaml \
        k8s-kustomized/base/ai-services/kustomization.yaml
git commit -m "k8s: add ollama-nemotron Service pointing at jetson1

Service + Endpoints route ai-services traffic to the bare-metal
Ollama on 10.0.0.73:11434. No pod in cluster — jetson1 owns
the inference process via systemd.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: Create Hermes SealedSecret

**Files:**
- Create: `k8s-kustomized/base/ai-services/hermes-secrets.yaml`

**Prerequisites:**
- You need a Telegram bot token. Create the bot via `@BotFather` on Telegram, save the token.
- `kubeseal` CLI installed locally. If not: `brew install kubeseal`.
- Sealed-Secrets controller public cert. Fetch: `kubeseal --fetch-cert --controller-namespace=sealed-secrets > /tmp/sealed-secrets.pem`.

- [ ] **Step 1: Create the raw Secret (will NOT be committed)**

Run (substitute your actual token):
```bash
cat > /tmp/hermes-secret-raw.yaml <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: hermes-secrets
  namespace: ai-services
type: Opaque
stringData:
  TELEGRAM_BOT_TOKEN: "REPLACE_WITH_REAL_TOKEN"
  # OPENROUTER_API_KEY intentionally omitted. Add here only if you explicitly
  # want the agent to have cloud-LLM egress. Keep this commented out by default.
EOF
```

**Edit `/tmp/hermes-secret-raw.yaml` and replace the placeholder with your real token before sealing.**

- [ ] **Step 2: Seal it**

Run:
```bash
kubeseal --cert /tmp/sealed-secrets.pem --format yaml \
  < /tmp/hermes-secret-raw.yaml \
  > k8s-kustomized/base/ai-services/hermes-secrets.yaml
```
Expected: output file contains `kind: SealedSecret`, encrypted data.

- [ ] **Step 3: Verify the sealed file has no plaintext tokens**

Run:
```bash
grep -i "token\|key" k8s-kustomized/base/ai-services/hermes-secrets.yaml
```
Expected: only field *names* (`TELEGRAM_BOT_TOKEN`, etc.), no raw values.

- [ ] **Step 4: Shred the raw file**

Run:
```bash
shred -u /tmp/hermes-secret-raw.yaml
```

- [ ] **Step 5: Add to kustomization**

Modify `k8s-kustomized/base/ai-services/kustomization.yaml` — append `- hermes-secrets.yaml` under `resources:`.

- [ ] **Step 6: Validate render + apply**

Run:
```bash
kubectl kustomize k8s-kustomized/base/ai-services | grep -A 3 "kind: SealedSecret"
kubectl apply -k k8s-kustomized/base/ai-services
```
Expected: render shows the SealedSecret; apply creates it; Sealed-Secrets controller unseals into a regular Secret within ~5s.

- [ ] **Step 7: Verify unseal**

Run:
```bash
kubectl get secret hermes-secrets -n ai-services -o jsonpath='{.data.TELEGRAM_BOT_TOKEN}' | base64 -d | head -c 20
echo
```
Expected: first 20 chars of your token (format `1234567890:AAH...`). Confirms the controller unsealed correctly.

- [ ] **Step 8: Commit**

```bash
git add k8s-kustomized/base/ai-services/hermes-secrets.yaml \
        k8s-kustomized/base/ai-services/kustomization.yaml
git commit -m "k8s: add Hermes SealedSecret (Telegram bot token)

OpenRouter key intentionally omitted from the secret — Hermes only
has local Ollama egress until a cloud key is explicitly added.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 10: Hermes ConfigMap + PVC

**Files:**
- Create: `k8s-kustomized/base/ai-services/hermes-agent.yaml` (scaffolded with ConfigMap + PVC first; Deployment added in Task 11)

- [ ] **Step 1: Write the initial `hermes-agent.yaml` — ConfigMap + PVC only**

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: hermes-config
  namespace: ai-services
  labels:
    app: hermes-agent
data:
  HERMES_HOME: "/opt/data"
  HERMES_MODEL_PROVIDER: "ollama"
  HERMES_MODEL_ENDPOINT: "http://ollama-nemotron.ai-services.svc.cluster.local:11434"
  HERMES_MODEL: "nemotron3:4b-q4_k_m"
  HERMES_MEMORY_BACKEND: "fts5"
  # doc-ingester bridge — wired as HTTP custom tool in Task 15.
  DOC_INGESTER_URL: "http://doc-ingester.ai-services.svc.cluster.local:3002"
---
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: hermes-data
  namespace: ai-services
  labels:
    app: hermes-agent
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: local-path
```

- [ ] **Step 2: Add to kustomization**

Modify `k8s-kustomized/base/ai-services/kustomization.yaml` — append `- hermes-agent.yaml`.

- [ ] **Step 3: Validate render**

Run:
```bash
kubectl kustomize k8s-kustomized/base/ai-services | grep -E "name: hermes-(config|data)"
```
Expected: both resources present.

- [ ] **Step 4: Apply**

Run:
```bash
kubectl apply -k k8s-kustomized/base/ai-services
```
Expected: `configmap/hermes-config created`, `persistentvolumeclaim/hermes-data created`.

- [ ] **Step 5: Verify PVC bound**

Run:
```bash
kubectl get pvc hermes-data -n ai-services
```
Expected: STATUS `Bound` within ~10s (local-path provisioner). If Pending, investigate storage class.

- [ ] **Step 6: Commit**

```bash
git add k8s-kustomized/base/ai-services/hermes-agent.yaml \
        k8s-kustomized/base/ai-services/kustomization.yaml
git commit -m "k8s: Hermes ConfigMap + PVC

10Gi local-path PVC for Hermes FTS5 memory and skills DB.
ConfigMap points Hermes at in-cluster Ollama service.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 11: Hermes Deployment + Service

**Files:**
- Modify: `k8s-kustomized/base/ai-services/hermes-agent.yaml` — append Deployment + Service

- [ ] **Step 1: Append Deployment + Service to `hermes-agent.yaml`**

Append after the existing PVC block (keep a `---` separator):

```yaml
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hermes-agent
  namespace: ai-services
  labels:
    app: hermes-agent
    app.kubernetes.io/component: agent
spec:
  replicas: 1
  strategy:
    type: Recreate   # RWO PVC — can't run two pods at once
  selector:
    matchLabels:
      app: hermes-agent
  template:
    metadata:
      labels:
        app: hermes-agent
    spec:
      securityContext:
        runAsUser: 10000
        runAsGroup: 10000
        fsGroup: 10000
      containers:
        - name: hermes
          image: ghcr.io/nousresearch/hermes-agent:latest
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8080
              protocol: TCP
          envFrom:
            - configMapRef:
                name: hermes-config
            - secretRef:
                name: hermes-secrets
          volumeMounts:
            - name: data
              mountPath: /opt/data
          resources:
            requests:
              cpu: "500m"
              memory: "2Gi"
            limits:
              cpu: "2000m"
              memory: "4Gi"
          readinessProbe:
            tcpSocket:
              port: 8080
            initialDelaySeconds: 30
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: 8080
            initialDelaySeconds: 60
            periodSeconds: 30
      volumes:
        - name: data
          persistentVolumeClaim:
            claimName: hermes-data
---
apiVersion: v1
kind: Service
metadata:
  name: hermes-agent
  namespace: ai-services
  labels:
    app: hermes-agent
spec:
  type: ClusterIP
  selector:
    app: hermes-agent
  ports:
    - name: http
      port: 8080
      protocol: TCP
      targetPort: 8080
```

- [ ] **Step 2: Validate render**

Run:
```bash
kubectl kustomize k8s-kustomized/base/ai-services | grep -A 2 "kind: Deployment" | grep hermes
```

- [ ] **Step 3: Apply**

Run:
```bash
kubectl apply -k k8s-kustomized/base/ai-services
```
Expected: `deployment.apps/hermes-agent created`, `service/hermes-agent created`.

- [ ] **Step 4: Watch pod come up (image pull may take a few min)**

Run:
```bash
kubectl get pods -n ai-services -l app=hermes-agent -w
```
Expected within ~3-5 min: `STATUS: Running`, `READY: 1/1`. Press Ctrl-C when ready.

- [ ] **Step 5: Check logs for model connection**

Run:
```bash
kubectl logs -n ai-services deploy/hermes-agent --tail=50
```
Expected: Hermes starts up, reaches the configured model endpoint. Look for reference to `ollama-nemotron` and a successful model handshake. If you see repeated connection errors to Ollama, verify Task 8's Service is healthy.

- [ ] **Step 6: Commit**

```bash
git add k8s-kustomized/base/ai-services/hermes-agent.yaml
git commit -m "k8s: Hermes Deployment + Service

Single-replica Recreate strategy (RWO PVC). UID 10000 per Dockerfile.
Resource limits 2 CPU / 4Gi — paperclip-style killswitch at pod level.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 12: NetworkPolicy + ResourceQuota (governance layer)

**Files:**
- Modify: `k8s-kustomized/base/ai-services/hermes-agent.yaml` — append NetworkPolicy (ResourceQuota intentionally NOT namespace-wide; pod-level limits from Task 11 already provide the killswitch)

- [ ] **Step 1: Append NetworkPolicy to `hermes-agent.yaml`**

Append after the Service block:

```yaml
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: hermes-agent-egress
  namespace: ai-services
  labels:
    app: hermes-agent
spec:
  podSelector:
    matchLabels:
      app: hermes-agent
  policyTypes:
    - Egress
  egress:
    # DNS
    - to:
        - namespaceSelector: {}
          podSelector:
            matchLabels:
              k8s-app: kube-dns
      ports:
        - protocol: UDP
          port: 53
        - protocol: TCP
          port: 53
    # In-namespace: Ollama Service + doc-ingester
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: ai-services
      ports:
        - protocol: TCP
          port: 11434
        - protocol: TCP
          port: 3002
    # Out-of-cluster Ollama on jetson1
    - to:
        - ipBlock:
            cidr: 10.0.0.73/32
      ports:
        - protocol: TCP
          port: 11434
    # Telegram API
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except:
              - 10.0.0.0/8
              - 172.16.0.0/12
              - 192.168.0.0/16
      ports:
        - protocol: TCP
          port: 443
```

(Last rule: allow HTTPS egress to public internet but block private ranges, keeping the agent from poking at internal infra it shouldn't reach. Telegram + HF + any public message gateways the user enables flow through 443. Swap to a tighter CIDR list if you want to explicitly allowlist `api.telegram.org` / `huggingface.co` IPs.)

- [ ] **Step 2: Apply**

Run:
```bash
kubectl apply -k k8s-kustomized/base/ai-services
```
Expected: `networkpolicy.networking.k8s.io/hermes-agent-egress created`.

- [ ] **Step 3: Verify policy enforces**

Run:
```bash
# Should succeed — in-cluster Ollama
kubectl exec -n ai-services deploy/hermes-agent -- \
  curl -s --max-time 5 http://ollama-nemotron.ai-services.svc.cluster.local:11434/api/tags

# Should fail — unrelated internal IP (simulated policy bypass attempt)
kubectl exec -n ai-services deploy/hermes-agent -- \
  curl -s --max-time 3 http://10.0.0.200:80 2>&1 | head -5 || echo "blocked (expected)"

# Should succeed — api.telegram.org on 443
kubectl exec -n ai-services deploy/hermes-agent -- \
  curl -s --max-time 5 -I https://api.telegram.org/ | head -1
```
Expected: first succeeds with JSON; second times out (`blocked (expected)`); third returns an HTTP header.

- [ ] **Step 4: Commit**

```bash
git add k8s-kustomized/base/ai-services/hermes-agent.yaml
git commit -m "k8s: NetworkPolicy for Hermes egress allowlist

Agent can reach: in-cluster DNS, ai-services namespace, jetson1
Ollama (10.0.0.73), public HTTPS (Telegram/HF). Cannot reach
other private subnets or non-443 external ports.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 13: Patch LocalAI to jetson2-only

**Files:**
- Modify: `k8s-kustomized/base/ai-services/localai.yaml` OR `k8s-kustomized/overlays/production/kustomization.yaml`

- [ ] **Step 1: Inspect current LocalAI config**

Run:
```bash
grep -nE "replicas|nodeSelector|hostname" k8s-kustomized/base/ai-services/localai.yaml
```
Decide whether to edit the base or add an overlay patch. Prefer base if LocalAI already targets one specific deployment (not two).

- [ ] **Step 2: Ensure replicas=1 and nodeSelector pins to jetson2**

Open `k8s-kustomized/base/ai-services/localai.yaml`. In the Deployment spec:

```yaml
spec:
  replicas: 1     # was likely 2 — now single replica
  # ...
  template:
    spec:
      nodeSelector:
        kubernetes.io/hostname: jetson2
```

If your base already has `nodeSelector: node-type: gpu-worker`, replace that key with the hostname selector above (jetson1 is leaving, jetson2 is the only GPU worker).

- [ ] **Step 3: Validate**

Run:
```bash
kubectl kustomize k8s-kustomized/overlays/production | grep -B 2 -A 3 "jetson2" | head -20
```
Expected: LocalAI Deployment's nodeSelector shows `kubernetes.io/hostname: jetson2`.

- [ ] **Step 4: Apply**

Run:
```bash
kubectl apply -k k8s-kustomized/overlays/production
```
Expected: `deployment.apps/localai configured`. Existing pod may cycle once as nodeSelector changes.

- [ ] **Step 5: Watch rollout**

Run:
```bash
kubectl rollout status deployment/localai -n ai-services --timeout=180s
```
Expected: `deployment "localai" successfully rolled out`. Embeddings briefly (5-30s) unavailable during rollout.

- [ ] **Step 6: Verify LocalAI still serves embeddings**

Run:
```bash
kubectl exec -n ai-services deploy/doc-ingester -- \
  curl -s --max-time 10 http://localai.ai-services.svc.cluster.local:8080/v1/embeddings \
  -H "Content-Type: application/json" \
  -d '{"model": "nomic-embed-text", "input": "ping"}' | head -c 200
```
Expected: JSON response with an embedding vector.

- [ ] **Step 7: Commit**

```bash
git add k8s-kustomized/base/ai-services/localai.yaml
git commit -m "k8s: collapse LocalAI to single replica on jetson2

jetson1 left the cluster (dedicated Nemotron host). jetson2 is now
the only gpu-worker; LocalAI runs there alone for embeddings.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 14: Push to ArgoCD and verify reconciliation

**Files:**
- No file changes in this task. Push + observe.

- [ ] **Step 1: Push all committed changes**

Run:
```bash
git push origin main
```
Expected: push succeeds.

- [ ] **Step 2: Watch ArgoCD sync**

Run:
```bash
ssh elitemini 'kubectl -n argocd get app homelab-apps -o jsonpath="{.status.sync.status} {.status.health.status}"; echo'
```
Expected (may take up to 3 min after push): `Synced Healthy`.

- [ ] **Step 3: If ArgoCD hasn't synced yet, kick it**

Run:
```bash
ssh elitemini 'argocd app sync homelab-apps' 2>&1 | tail -10
```
Expected: `Synced` output.

- [ ] **Step 4: Verify Hermes is running (post-Argo-sync reality check)**

Run:
```bash
kubectl get all -n ai-services -l app=hermes-agent
kubectl get networkpolicy -n ai-services hermes-agent-egress
kubectl get svc,endpoints -n ai-services ollama-nemotron
```
Expected: Hermes Deployment + pod Running, NetworkPolicy present, ollama-nemotron Service + Endpoints exist.

- [ ] **Step 5: Commit nothing**

---

## Task 15: Wire doc-ingester as a Hermes custom tool

**Files:**
- Modify: `k8s-kustomized/base/ai-services/hermes-agent.yaml` — extend ConfigMap with tool config, OR
- Create: `k8s-kustomized/base/ai-services/hermes-tools.yaml` — dedicated tool-config file

Choice: put it in a separate file for clarity, since tool definitions can grow.

- [ ] **Step 1: Check Hermes docs for tool definition format**

Run:
```bash
kubectl exec -n ai-services deploy/hermes-agent -- hermes tools --help 2>&1 | head -20
```
Expected: CLI help for tool registration. The exact config schema comes from this — **if the schema differs from what's below, adjust the manifest accordingly before committing**.

- [ ] **Step 2: Create `k8s-kustomized/base/ai-services/hermes-tools.yaml`**

```yaml
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: hermes-tools
  namespace: ai-services
  labels:
    app: hermes-agent
data:
  tools.yaml: |
    # Custom HTTP tools available to the Hermes agent.
    tools:
      - name: search_personal_memory
        description: |
          Search the user's personal documents (iMessage, Gmail) indexed in
          Qdrant by the doc-ingester service. Returns the top-k semantically
          similar passages with source metadata.
        type: http
        request:
          method: GET
          url: http://doc-ingester.ai-services.svc.cluster.local:3002/api/search
          query:
            q: "{{query}}"
            k: 5
        parameters:
          - name: query
            type: string
            required: true
            description: Natural-language search query
```

- [ ] **Step 3: Mount the tool config into the Hermes pod**

Edit `hermes-agent.yaml` Deployment — add volume + volumeMount:

In `spec.template.spec.volumes`, append:
```yaml
        - name: tools-config
          configMap:
            name: hermes-tools
```

In `spec.template.spec.containers[0].volumeMounts`, append:
```yaml
            - name: tools-config
              mountPath: /opt/data/tools
              readOnly: true
```

Add to `hermes-config` ConfigMap (Task 10's file) a new env var:
```yaml
  HERMES_TOOLS_CONFIG: "/opt/data/tools/tools.yaml"
```

- [ ] **Step 4: Add to kustomization**

Append `- hermes-tools.yaml` to `k8s-kustomized/base/ai-services/kustomization.yaml`.

- [ ] **Step 5: Apply + restart pod to pick up new env + volume**

Run:
```bash
kubectl apply -k k8s-kustomized/base/ai-services
kubectl rollout restart deployment/hermes-agent -n ai-services
kubectl rollout status deployment/hermes-agent -n ai-services --timeout=180s
```

- [ ] **Step 6: Verify tool is registered**

Run:
```bash
kubectl exec -n ai-services deploy/hermes-agent -- \
  hermes tools list 2>&1 | grep search_personal_memory
```
Expected: the tool name appears.

- [ ] **Step 7: Smoke test the tool invocation**

Run:
```bash
kubectl exec -n ai-services deploy/hermes-agent -- \
  hermes agent --local -m "use search_personal_memory for the word hello"
```
Expected: response mentions a search result or a gracefully-handled empty-corpus case.

- [ ] **Step 8: Commit**

```bash
git add k8s-kustomized/base/ai-services/hermes-tools.yaml \
        k8s-kustomized/base/ai-services/hermes-agent.yaml \
        k8s-kustomized/base/ai-services/kustomization.yaml
git commit -m "k8s: wire doc-ingester as a Hermes HTTP tool

Hermes 'search_personal_memory' tool calls doc-ingester's /api/search
for semantic retrieval over the user's iMessage corpus in Qdrant.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 16: Enable Telegram gateway

**Files:**
- Modify: `k8s-kustomized/base/ai-services/hermes-agent.yaml` — extend ConfigMap with gateway config

- [ ] **Step 1: Add gateway env to ConfigMap**

Edit `hermes-config` ConfigMap in `hermes-agent.yaml`, append:

```yaml
  HERMES_GATEWAY_ENABLED: "telegram"
  HERMES_GATEWAY_POLL_INTERVAL_SECONDS: "5"
```

(The `TELEGRAM_BOT_TOKEN` already flows in via `envFrom: secretRef: hermes-secrets`.)

- [ ] **Step 2: Apply + restart**

Run:
```bash
kubectl apply -k k8s-kustomized/base/ai-services
kubectl rollout restart deployment/hermes-agent -n ai-services
kubectl rollout status deployment/hermes-agent -n ai-services --timeout=120s
```

- [ ] **Step 3: Verify the gateway is polling**

Run:
```bash
kubectl logs -n ai-services deploy/hermes-agent --tail=30 | grep -iE "telegram|gateway"
```
Expected: log lines indicating Telegram gateway started and is polling `getUpdates`.

- [ ] **Step 4: Round-trip test**

From your phone: open Telegram, find your bot (via the name you set with @BotFather), send "hello". Wait up to 15s.

Expected: a sensible response from Nemotron. If nothing comes back, check `kubectl logs` for token validation errors or rate-limit messages.

- [ ] **Step 5: Commit**

```bash
git add k8s-kustomized/base/ai-services/hermes-agent.yaml
git commit -m "k8s: enable Hermes Telegram gateway

Primary messaging channel. Token from sealed hermes-secrets.
Poll interval 5s.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 17: Update network.yaml + propagate

**Files:**
- Modify: `config/network.yaml`

- [ ] **Step 1: Edit `config/network.yaml`**

Find the `jetson1` block:
```yaml
  jetson1:
    ip: "10.0.0.73"
    role: "gpu-worker"
    description: "GPU worker (Ollama)"
```

Change to:
```yaml
  jetson1:
    ip: "10.0.0.73"
    role: "inference-host"
    description: "Dedicated Nemotron-3-Nano-4B inference host (out of K3s)"
```

- [ ] **Step 2: Run propagation script**

Run:
```bash
./scripts/apply-network-config.sh
```
Expected: script rewrites relevant manifests + docs. Review the diff before committing.

Run:
```bash
git diff --stat
```
Expected: changes in `ansible/inventory/` (if not already updated by Task 7), possibly in monitoring targets, possibly in docs. Nothing unexpected.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "config: jetson1 role inference-host (out of K3s)

Propagates through ansible inventory, monitoring, and docs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 18: Add governance convention to root CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add a new section to root CLAUDE.md**

Insert after the "Secrets" section (near the end of the file), a new section:

```markdown
## Autonomous agents — governance convention

Any new autonomous/always-on agent added to this homelab follows the Hermes
pattern (see `docs/superpowers/specs/2026-04-18-hermes-agent-design.md`):

- Deployed into `ai-services` via Kustomize.
- Ships with a NetworkPolicy restricting egress to only the services it needs
  — cloud LLM endpoints (OpenAI, Anthropic, etc.) reachable only when a
  committed policy change explicitly allowlists them.
- Pod-level ResourceQuota (CPU + memory ceilings) as a runaway killswitch.
  Non-negotiable after the paperclip incident.
- Local-first inference: prefer the dedicated jetson1 Nemotron endpoint
  (`http://ollama-nemotron.ai-services.svc.cluster.local:11434`) over cloud
  models. Cloud keys added only with explicit justification.
- SealedSecret for any credentials, never plaintext.

Reference implementation: `k8s-kustomized/base/ai-services/hermes-agent.yaml`.
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: governance convention for autonomous agents

Pattern established by Hermes deployment. Reference implementation:
k8s-kustomized/base/ai-services/hermes-agent.yaml.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 19: End-to-end verification

**Files:**
- No file changes. Verification only.

- [ ] **Step 1: Telegram round-trip**

From Telegram, send: "what time is it in UTC?"

Expected: response within 10s containing a plausible UTC time.

Measure:
```bash
kubectl logs -n ai-services deploy/hermes-agent --since=5m | grep -iE "generation|inference" | tail -5
```
Look for `duration_ms` values; should be < 10000.

- [ ] **Step 2: Memory persistence across restart**

Send: "remember that my favorite color is blue."
Wait for acknowledgment.

Run:
```bash
kubectl rollout restart deployment/hermes-agent -n ai-services
kubectl rollout status deployment/hermes-agent -n ai-services --timeout=120s
```

After restart, from Telegram send: "what's my favorite color?"

Expected: response includes "blue".

- [ ] **Step 3: NetworkPolicy denies cloud LLM egress**

Run:
```bash
kubectl exec -n ai-services deploy/hermes-agent -- \
  curl -s --max-time 3 https://api.openai.com 2>&1 | head -3
```
Expected: times out or returns policy denied. Not a successful response.

Separately verify Telegram still works (Step 1).

- [ ] **Step 4: Ollama endpoint stays warm overnight**

Run (next day):
```bash
curl -s --max-time 3 http://10.0.0.73:11434/api/tags | head -c 200
```
Expected: model still loaded, responds fast.

- [ ] **Step 5: Commit the verification log**

Create `docs/superpowers/plans/2026-04-18-hermes-agent-results.md` with:

- Actual response times for Step 1
- Memory persistence confirmation from Step 2
- NetworkPolicy denial observed output from Step 3
- Any surprises / deviations from the plan

Run:
```bash
git add docs/superpowers/plans/2026-04-18-hermes-agent-results.md
git commit -m "docs: Hermes deployment verification results

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Self-review results

**Spec coverage check**:

- Architecture (Section 1) → Tasks 8, 10, 11 (in-cluster) + 5-7 (out-of-cluster) ✓
- Kustomize layout (Section 2) → Tasks 8, 10, 11, 12, 15 ✓
- Config + secrets (Section 3) → Tasks 9, 10, 16 ✓
- Integrations (Section 4) → Tasks 15, 16 ✓
- Governance (Section 5) → Tasks 12, 18 ✓
- jetson1 prep (Section 6) → Tasks 1-7 ✓
- Cluster-side cleanup → Tasks 2, 13, 17 ✓
- Success criteria → Task 19 ✓

**Placeholder scan**: none found. Every step has exact commands and exact content. Two "adjust at install time" notes (Hermes tool format in Task 15 Step 1, Ollama model tag in Task 5 Step 5) are gated on actual Hermes/Ollama CLI output, not deferred to the engineer.

**Type consistency**: Service name `ollama-nemotron` is consistent across Tasks 8, 10, 12. Secret name `hermes-secrets`, ConfigMap `hermes-config` + `hermes-tools`, PVC `hermes-data`, Deployment `hermes-agent` — all consistent. Env var names (`HERMES_HOME`, `HERMES_MODEL_PROVIDER`, etc.) stable across tasks.

**Known open questions (documented in spec, surfaced in plan)**:
- Exact Ollama tag for Nemotron-3-Nano-4B — Task 5 Step 5 has fallback.
- Hermes tool-config schema — Task 15 Step 1 instructs engineer to verify.
- Ollama GPU detection on current L4T — Task 5 Step 7 is the pre-written fallback.
