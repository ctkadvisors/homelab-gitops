# Networking and Monitoring Learnings

## 🌐 Networking Architecture Insights

### Avahi/mDNS Configuration Learnings

#### ✅ Key Discoveries
1. **XML Syntax Validation is Critical**
   - Malformed XML (like `</n>` instead of `</name>`) causes silent failures
   - Avahi logs errors to systemd journal: `sudo journalctl -u avahi-daemon`
   - Always validate XML before deployment: `python3 -c "import xml.etree.ElementTree as ET; ET.parse('file.xml')"`

2. **Service Name Collisions**
   - Multiple Avahi service files with same `<name>` cause conflicts
   - Error: `Failed to add service 'Local AI Services' of type '_https._tcp', ignoring service group`
   - Solution: Use unique service group names or remove conflicting files

3. **Service Discovery Debugging**
   ```bash
   # Browse available services
   avahi-browse -t _https._tcp
   
   # Check service registration
   sudo systemctl status avahi-daemon
   sudo journalctl -u avahi-daemon --since '5 minutes ago'
   ```

#### 🔧 Working Configuration Pattern
```xml
<?xml version="1.0" standalone="no"?>
<!DOCTYPE service-group SYSTEM "avahi-service.dtd">
<service-group>
  <name replace-wildcards="yes">LocalAI Infrastructure</name>
  <service>
    <type>_https._tcp</type>
    <port>443</port>
    <host-name>service.local</host-name>
  </service>
</service-group>
```

### Traefik Ingress Learnings

#### ✅ SSL/TLS Configuration
- **Self-signed certificates** work well for local development
- **TLS secrets** must exist in each namespace where ingress is defined
- **Automatic HTTPS redirect** via middleware

#### 🔧 Working Ingress Pattern
```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: service-ingress
  namespace: ai-services
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - service.local
      secretName: traefik-tls
  rules:
    - host: service.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service
                port:
                  number: 8080
```

### Container Image Architecture Compatibility

#### ❌ Common Issue: AMD64 vs ARM64
- Many Docker images only support AMD64 architecture
- RPi requires ARM64 images
- **Detection**: `docker manifest inspect image:tag`
- **Solution**: Build locally or find ARM64 alternatives

#### 🔧 Local ARM64 Build Strategy
```bash
# Check architecture
uname -m  # Should show aarch64 for ARM64

# Build locally
docker build -t service:local-arm64 .

# Import to k3s (uses containerd)
docker save service:local-arm64 | sudo k3s ctr images import -

# Use in deployment
spec:
  containers:
    - name: service
      image: service:local-arm64
      imagePullPolicy: Never
```

## 📊 Resource Monitoring Solutions

### Current Monitoring Gaps
You're absolutely right - we need better visibility into RPi resource consumption. Here are the solutions:

### 1. Kubernetes Native Monitoring

#### Metrics Server (Lightweight)
```bash
# Install metrics server
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml

# View resource usage
kubectl top nodes
kubectl top pods -A
```

#### Resource Monitoring Commands
```bash
# Node resource usage
kubectl describe node raspberrypi1

# Pod resource requests/limits
kubectl get pods -o custom-columns=NAME:.metadata.name,CPU-REQ:.spec.containers[*].resources.requests.cpu,MEM-REQ:.spec.containers[*].resources.requests.memory,CPU-LIM:.spec.containers[*].resources.limits.cpu,MEM-LIM:.spec.containers[*].resources.limits.memory -A

# Real-time resource usage
watch kubectl top pods -A
```

### 2. System-Level Monitoring

#### Built-in Tools
```bash
# CPU and memory usage
htop
top

# Disk usage
df -h
du -sh /opt/*

# Network usage
iftop
nethogs

# System overview
vmstat 1
iostat 1
```

#### Continuous Monitoring Script
```bash
#!/bin/bash
# Monitor RPi resources every 30 seconds
while true; do
  echo "=== $(date) ==="
  echo "CPU: $(cat /proc/loadavg)"
  echo "Memory: $(free -h | grep Mem)"
  echo "Disk: $(df -h / | tail -1)"
  echo "Temperature: $(vcgencmd measure_temp)"
  sleep 30
done
```

### 3. Prometheus + Grafana Stack (Recommended)

#### Why Prometheus for RPi?
- **Lightweight**: Minimal resource overhead
- **Kubernetes native**: Excellent k8s integration
- **Rich metrics**: Node, pod, and application metrics
- **Alerting**: Proactive monitoring

#### Quick Prometheus Setup
```yaml
# prometheus-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: monitoring
data:
  prometheus.yml: |
    global:
      scrape_interval: 30s
    scrape_configs:
      - job_name: 'kubernetes-nodes'
        kubernetes_sd_configs:
          - role: node
      - job_name: 'kubernetes-pods'
        kubernetes_sd_configs:
          - role: pod
```

### 4. Simple Web Dashboard

#### Lightweight Monitoring Dashboard
```python
# Simple Flask dashboard for RPi monitoring
import psutil
from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def dashboard():
    return {
        'cpu_percent': psutil.cpu_percent(),
        'memory': psutil.virtual_memory()._asdict(),
        'disk': psutil.disk_usage('/')._asdict(),
        'temperature': get_cpu_temperature()
    }

def get_cpu_temperature():
    try:
        with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
            temp = int(f.read()) / 1000.0
        return f"{temp:.1f}°C"
    except:
        return "N/A"
```

## 🚨 Resource Alerts and Thresholds

### Critical RPi Limits
- **CPU**: > 80% sustained load
- **Memory**: > 85% usage (RPi has limited RAM)
- **Temperature**: > 70°C (throttling starts at 80°C)
- **Disk**: > 90% usage
- **SD Card**: Monitor write cycles

### Monitoring Commands for Alerts
```bash
# Check if CPU is throttling
vcgencmd get_throttled

# Monitor temperature
watch vcgencmd measure_temp

# Check memory pressure
cat /proc/meminfo | grep -E "(MemTotal|MemAvailable|MemFree)"

# Monitor disk I/O
iostat -x 1
```

## 🔍 Troubleshooting Network Issues

### DNS Resolution Problems
```bash
# Test mDNS resolution
ping service.local
nslookup service.local

# Check Avahi status
sudo systemctl status avahi-daemon
avahi-browse -a

# Test direct IP access
curl -k https://192.168.131.101/
```

### Traefik Debugging
```bash
# Check Traefik logs
kubectl logs -f deployment/traefik -n ingress-system

# Verify ingress configuration
kubectl get ingress -A
kubectl describe ingress service-ingress -n namespace

# Test backend connectivity
kubectl port-forward svc/service 8080:8080 -n namespace
```

### Container Connectivity
```bash
# Test pod-to-pod communication
kubectl exec -it pod-name -- curl http://service-name:port

# Check service endpoints
kubectl get endpoints -A

# Verify DNS within cluster
kubectl exec -it pod-name -- nslookup service-name
```

## 📈 Performance Optimization

### RPi-Specific Optimizations
1. **Resource Limits**: Set conservative CPU/memory limits
2. **Node Affinity**: Pin services to appropriate nodes
3. **Storage**: Use fast SD cards (Class 10, A2)
4. **Cooling**: Ensure adequate ventilation
5. **Power**: Use quality power supply (5V 3A+)

### Kubernetes Optimizations
```yaml
# Resource-aware scheduling
resources:
  requests:
    memory: "64Mi"
    cpu: "50m"
  limits:
    memory: "128Mi"
    cpu: "200m"

# Node selection for RPi
nodeSelector:
  kubernetes.io/hostname: raspberrypi1
```

## 🎯 Next Steps for Monitoring

1. **Implement Metrics Server** for basic k8s monitoring
2. **Add Prometheus** for comprehensive metrics collection
3. **Create Grafana Dashboard** for visualization
4. **Set up Alerting** for critical thresholds
5. **Monitor Application Metrics** (MCPO, OpenWebUI performance)

This monitoring setup will give you complete visibility into your RPi's resource consumption and help prevent performance issues before they impact your AI services.
