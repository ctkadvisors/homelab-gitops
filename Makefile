# Local AI Stack Makefile
# K3s Kubernetes Cluster Management Commands

.PHONY: help init deploy stop clean logs scale add-node setup-secrets monitoring

# Default target
help:
	@echo "Local AI Stack Management Commands (K3s):"
	@echo "  make init          - Initialize K3s cluster and create secrets"
	@echo "  make deploy        - Deploy the entire stack"
	@echo "  make stop          - Stop all services"
	@echo "  make clean         - Remove all services and volumes"
	@echo "  make logs          - View logs for all services"
	@echo "  make monitoring    - Open monitoring dashboards"
	@echo ""
	@echo "Service Management:"
	@echo "  make deploy-core   - Deploy core infrastructure only"
	@echo "  make deploy-ai     - Deploy AI services only"
	@echo "  make deploy-data   - Deploy data services only"
	@echo ""
	@echo "Model Management:"
	@echo "  make pull-model MODEL=<model>  - Pull a specific model"
	@echo "  make list-models              - List available models"
	@echo "  make add-finetune PATH=<path> - Add a fine-tuned model"
	@echo ""
	@echo "Node Management:"
	@echo "  make add-node HOST=<hostname> - Add a new node to cluster"
	@echo "  make node-status              - Check node status"
	@echo "  make setup-k3s                - Setup K3s cluster"
	@echo ""
	@echo "📁 All services managed via Kubernetes and ArgoCD GitOps"

# Initialize K3s cluster
init:
	@echo "Initializing K3s cluster..."
	@./scripts/setup-k3s-cluster.sh
	@echo "Creating secrets..."
	@./scripts/create-secrets.sh
	@echo "Setting up NFS mounts (optional)..."
	@./scripts/setup-nfs.sh || echo "⚠️  NFS setup failed, continuing without NFS..."
	@echo "Initialization complete!"

# Deploy entire stack with monitoring enabled  
deploy: init
	@echo "Deploying Local AI Stack on K3s..."
	@export KUBECONFIG=./kubeconfig && \
	kubectl apply -f k8s/networking/metallb.yaml && \
	kubectl apply -f k8s/ingress/traefik.yaml && \
	kubectl apply -f k8s/apps/ -R && \
	kubectl apply -f k8s/monitoring/ -R
	@echo "Waiting for services to start..."
	@sleep 15
	@echo "Stack deployed! Access services at:"
	@echo "  - OpenWebUI: https://chat.example.com"
	@echo "  - n8n: https://n8n.example.com"
	@echo "  - Ollama: https://ollama.example.com"
	@echo "  - MCPO Control Panel: https://mcpo-ui.example.com"

# Deploy individual components
deploy-core:
	@export KUBECONFIG=./kubeconfig && \
	kubectl apply -f k8s/networking/metallb.yaml && \
	kubectl apply -f k8s/ingress/traefik.yaml

deploy-data:
	@export KUBECONFIG=./kubeconfig && \
	kubectl apply -f k8s/apps/storage/ -R

deploy-ai:
	@export KUBECONFIG=./kubeconfig && \
	kubectl apply -f k8s/apps/ai-services/ -R

deploy-monitoring:
	@export KUBECONFIG=./kubeconfig && \
	kubectl apply -f k8s/monitoring/ -R

# Stop all services
stop:
	@export KUBECONFIG=./kubeconfig && \
	kubectl delete -f k8s/apps/ -R --ignore-not-found=true

# Clean everything (including volumes)
clean: stop
	@echo "Waiting for cleanup..."
	@sleep 10
	@export KUBECONFIG=./kubeconfig && \
	kubectl delete pvc --all -A --ignore-not-found=true
	@echo "Cleanup complete!"

# View logs
logs:
	@export KUBECONFIG=./kubeconfig && \
	kubectl logs -f deployment/openwebui -n ai-services

logs-ollama:
	@export KUBECONFIG=./kubeconfig && \
	kubectl logs -f deployment/ollama -n ai-services

logs-all:
	@export KUBECONFIG=./kubeconfig && \
	kubectl logs -f --all-containers=true --selector="app in (openwebui,ollama,n8n,mcpo-control-panel)" -A

# Model management
pull-model:
	@./scripts/model-manager.sh pull $(MODEL)

list-models:
	@./scripts/model-manager.sh list

add-finetune:
	@./scripts/model-manager.sh add-finetune $(PATH)

# Scale services
scale-openwebui:
	@export KUBECONFIG=./kubeconfig && \
	kubectl scale deployment openwebui --replicas=2 -n ai-services

scale-n8n:
	@export KUBECONFIG=./kubeconfig && \
	kubectl scale deployment n8n --replicas=2 -n automation

# Node management
add-node:
	@./scripts/add-node.sh $(HOST)

node-status:
	@echo "K3s Cluster nodes:"
	@export KUBECONFIG=./kubeconfig && kubectl get nodes -o wide
	@echo ""
	@echo "Node resources:"
	@export KUBECONFIG=./kubeconfig && kubectl top nodes

# K3s-specific commands
setup-k3s:
	@echo "Setting up K3s cluster..."
	@./scripts/setup-k3s-cluster.sh

# Monitoring shortcuts
monitoring:
	@echo "Opening monitoring dashboards..."
	@echo "Grafana: https://grafana.homelab"
	@echo "Prometheus: https://prometheus.homelab"

# Setup secrets (called by init)
setup-secrets:
	@./scripts/create-secrets.sh

# Health check
health:
	@echo "Checking service health..."
	@export KUBECONFIG=./kubeconfig && kubectl get pods -A
	@echo ""
	@echo "Checking ingress status:"
	@export KUBECONFIG=./kubeconfig && kubectl get ingress -A

# Quick test
test:
	@echo "Testing Ollama connection..."
	@curl -k -s https://ollama.example.com/api/tags || echo "Ollama not accessible"
	@echo ""
	@echo "Testing OpenWebUI..."
	@curl -k -s -o /dev/null -w "%{http_code}" https://chat.example.com

# Update services (K3s)
update:
	@echo "Updating K3s services..."
	@export KUBECONFIG=./kubeconfig && \
	kubectl set image deployment/openwebui openwebui=ghcr.io/open-webui/open-webui:main -n ai-services && \
	kubectl set image deployment/ollama ollama=ollama/ollama:latest -n ai-services && \
	kubectl set image deployment/n8n n8n=n8nio/n8n:latest -n automation && \
	kubectl set image deployment/mcpo-control-panel mcpo-control-panel=ghcr.io/ctkadvisors/mcpo-control-panel:latest -n ai-services && \
	echo "✅ All services updated"

# K3s cluster status
status:
	@echo "K3s Cluster Status:"
	@export KUBECONFIG=./kubeconfig && kubectl get nodes -o wide
	@echo ""
	@echo "Services:"
	@export KUBECONFIG=./kubeconfig && kubectl get services -A
	@echo ""
	@echo "Pods:"
	@export KUBECONFIG=./kubeconfig && kubectl get pods -A

# Fix DNS issues
fix-dns:
	@echo "Running DNS fix script..."
	@./scripts/fix-dns-issues.sh

# Backup data
backup:
	@./scripts/backup.sh

# Restore from backup
restore:
	@./scripts/restore.sh $(BACKUP_FILE)
