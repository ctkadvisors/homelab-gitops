# Local AI Homelab - Ansible Automation

This directory contains Ansible automation for the Local AI Homelab infrastructure. It provides declarative, idempotent provisioning of K3s nodes with GPU support.

## 🏗️ Structure

```
ansible/
├── ansible.cfg              # Ansible configuration
├── inventory/
│   └── hosts.yml            # Inventory with all nodes
├── group_vars/              # Group-specific variables
│   ├── all.yml             # Global variables
│   ├── k3s_masters.yml     # Master node configuration
│   ├── k3s_workers.yml     # Worker node configuration
│   └── gpu_workers.yml     # GPU worker configuration
├── host_vars/              # Host-specific variables (if needed)
├── roles/                  # Ansible roles
│   ├── base-system/        # Base system configuration
│   └── docker/             # Docker and container runtime
├── playbooks/              # Ansible playbooks
│   ├── site.yml            # Main site playbook
│   └── test-connectivity.yml # Connectivity test
└── README.md               # This file
```

## 🚀 Quick Start

### Prerequisites

1. **Ansible installed** on control machine:

   ```bash
   pip install ansible
   ```

2. **SSH key access** to all nodes:

   ```bash
   ssh-copy-id chris@192.168.131.101  # RPi
   ssh-copy-id chris@192.168.131.123  # Jetson1
   ssh-copy-id chris@192.168.131.163  # Jetson2 (optional)
   ```

3. **Passwordless sudo** configured on all nodes:
   ```bash
   echo "chris ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/chris
   ```

### Test Connectivity

```bash
# Test basic connectivity
ansible-playbook -i inventory/hosts.yml playbooks/test-connectivity.yml

# Test specific groups
ansible-playbook -i inventory/hosts.yml playbooks/test-connectivity.yml --limit k3s_masters
ansible-playbook -i inventory/hosts.yml playbooks/test-connectivity.yml --limit gpu_workers
```

### Run Base Configuration

```bash
# Configure all nodes with base system
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags base

# Configure only Docker
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags docker

# Configure specific host
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --limit raspberrypi1
```

## 📋 Inventory Configuration

### Current Nodes

| Node             | IP              | Role   | Type           | Ansible Managed | Services                                   |
| ---------------- | --------------- | ------ | -------------- | --------------- | ------------------------------------------ |
| **elitemini**    | 192.168.131.111 | Master | Control Plane  | ❌ **NO**       | OpenWebUI, n8n, MCPO, Traefik, Databases  |
| **raspberrypi1** | 192.168.131.101 | Worker | Worker         | ✅ **YES**      | K3s Agent, Monitoring                      |
| **jetson1**      | 192.168.131.123 | Worker | GPU Worker     | ✅ **YES**      | Ollama, K3s Agent + NVIDIA Runtime        |
| **jetson2**      | 192.168.131.163 | Worker | GPU Worker     | ✅ **YES**      | Qdrant, K3s Agent + NVIDIA Runtime        |

### ⚠️ Important Note

**EliteMini is NOT managed by Ansible** - it was set up manually and serves as the K3s control plane. Ansible is only used for worker node provisioning (RPi, Jetsons).

### Group Structure

- **all**: All nodes
- **k3s_cluster**: All K3s nodes
  - **k3s_masters**: Master nodes (RPi)
  - **k3s_workers**: Worker nodes (Jetsons + EliteMini)
- **gpu_workers**: GPU-enabled workers (Jetsons)
- **compute_workers**: High-performance compute workers (EliteMini)

## 🔧 Roles

### base-system

Configures base system requirements:

- Package management and updates
- User and SSH configuration
- System optimization and tuning
- Security hardening
- Log management
- Cron jobs and cleanup

### docker

Installs and configures Docker:

- Docker CE installation
- Container runtime optimization
- NVIDIA Container Runtime (for GPU nodes)
- User group management
- Security configuration

## 📊 Variables

### Global Variables (group_vars/all.yml)

Key configuration options:

- `project_name`: "local-ai-homelab"
- `k3s.version`: "v1.32.5+k3s1"
- `network.domain`: "homelab"
- `monitoring.enabled`: true

### Node-Specific Variables

Variables are automatically applied based on group membership:

- **Masters**: DNS, SSL, backup configuration
- **Workers**: Model storage, resource limits
- **GPU Workers**: NVIDIA runtime, performance tuning

## 🎯 Usage Examples

### Basic Operations

```bash
# Check all hosts are reachable
ansible all -i inventory/hosts.yml -m ping

# Run ad-hoc commands
ansible k3s_masters -i inventory/hosts.yml -m shell -a "uptime"
ansible gpu_workers -i inventory/hosts.yml -m shell -a "nvidia-smi"

# Gather facts
ansible all -i inventory/hosts.yml -m setup
```

### Playbook Execution

```bash
# Full site deployment
ansible-playbook -i inventory/hosts.yml playbooks/site.yml

# Specific tags
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags "base-system,docker"

# Limit to specific hosts
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --limit "jetson1,jetson2"

# Dry run (check mode)
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --check

# Verbose output
ansible-playbook -i inventory/hosts.yml playbooks/site.yml -vvv
```

### Maintenance Operations

```bash
# Update packages on all nodes
ansible all -i inventory/hosts.yml -m apt -a "update_cache=yes upgrade=dist" --become

# Restart services
ansible k3s_masters -i inventory/hosts.yml -m systemd -a "name=docker state=restarted" --become

# Check disk space
ansible all -i inventory/hosts.yml -m shell -a "df -h"

# Check system load
ansible all -i inventory/hosts.yml -m shell -a "uptime"
```

## 🔍 Troubleshooting

### Common Issues

1. **SSH Connection Failed**

   ```bash
   # Test SSH manually
   ssh -o StrictHostKeyChecking=no chris@192.168.131.101

   # Check SSH key
   ssh-add -l
   ```

2. **Sudo Permission Denied**

   ```bash
   # Test sudo access
   ansible all -i inventory/hosts.yml -m shell -a "sudo whoami"

   # Configure passwordless sudo
   echo "chris ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/chris
   ```

3. **Host Unreachable**

   ```bash
   # Check network connectivity
   ping 192.168.131.101

   # Check if host is in known_hosts
   ssh-keygen -R 192.168.131.101
   ```

### Debug Mode

```bash
# Enable debug logging
export ANSIBLE_DEBUG=1
ansible-playbook -i inventory/hosts.yml playbooks/site.yml -vvv

# Check Ansible configuration
ansible-config dump

# Validate inventory
ansible-inventory -i inventory/hosts.yml --list
ansible-inventory -i inventory/hosts.yml --graph
```

## 📈 Next Steps

### Phase II Completion Tasks

- [ ] **II.3.1** Create Ansible role for base OS configuration ✅
- [ ] **II.3.2** Create Ansible role for container runtime ✅
- [ ] **II.3.3** Create Ansible role for Tailscale installation
- [ ] **II.3.4** Create Ansible role for Jetson optimizations
- [ ] **II.4.1** Create Ansible role for K3s master installation
- [ ] **II.4.2** Create Ansible role for K3s agent installation
- [ ] **II.5.1** Test full node provisioning

### Implementation Priority

1. **K3s Installation Roles** - Replace manual cluster setup
2. **Jetson Optimization Role** - GPU performance tuning
3. **Tailscale Integration** - Remote access setup
4. **Validation and Testing** - Comprehensive test suite

## 📚 Documentation

- **[IMPLEMENTATION_TODO.md](../IMPLEMENTATION_TODO.md)** - Complete task list
- **[Current State Analysis](../docs/CURRENT_STATE_ANALYSIS.md)** - Infrastructure assessment
- **[Phase I Report](../docs/PHASE_I_COMPLETION_REPORT.md)** - Phase I completion summary

---

**Status**: Phase II - Ansible Foundation (In Progress)  
**Next**: Implement K3s installation roles  
**Goal**: Replace all manual SSH commands with idempotent Ansible automation
