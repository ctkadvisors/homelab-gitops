# new_localai

A sanitized snapshot of a homelab K3s GitOps repo: ArgoCD-reconciled manifests (`k8s-kustomized/`), runbooks and design docs (`docs/`), and the fleet service sources (`services/`).

It is a reference, not a turnkey install. Secrets, sealed-secret ciphertext, hostnames, IPs and contact details have been removed or replaced with placeholders (`example.com`, `10.0.0.x`), and manifests that referenced removed Secrets will not apply as-is. No git history is included.
