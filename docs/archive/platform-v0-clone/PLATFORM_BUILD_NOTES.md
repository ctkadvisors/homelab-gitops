# Platform Build and Deployment Notes

## Current Status (2025-07-02)

### ✅ Successfully Completed

- Built fresh platform-api and platform-dashboard images for x86_64 architecture
- Images pushed to Gitea registry at `git.example.com/homelab/`
- Registry authentication working properly
- **Images available:**
  - `git.example.com/homelab/platform-api:20250702-233153-amd64` ✅
  - `git.example.com/homelab/platform-dashboard:20250702-233237-amd64` ✅

### 🔧 Current Issues

- Complex automation pipeline with GitHub authentication issues
- Multi-architecture image building complications with `:latest` tags
- ArgoCD sync conflicts with manual kubectl commands
- **Architecture mismatch**: `:latest` tags pointing to ARM64 instead of x86_64

### 📝 Manual Build Process (Working)

The following manual process works reliably:

```bash
# 1. Build Platform API (x86_64)
cd platform-api
docker buildx build --platform linux/amd64 -t git.example.com/homelab/platform-api:$(date +%Y%m%d-%H%M%S)-amd64 --push .

# 2. Build Platform Dashboard (x86_64)
cd ../platform-dashboard
docker buildx build --platform linux/amd64 -t git.example.com/homelab/platform-dashboard:$(date +%Y%m%d-%H%M%S)-amd64 --push .

# 3. Update deployment manifests with specific tags (GitOps approach)
# Edit k8s/platform/api.yaml and k8s/platform/dashboard.yaml
# Change image tags to the specific timestamped versions
# Commit and push to trigger ArgoCD sync

# OR for immediate deployment:
kubectl set image deployment/platform-api api=git.example.com/homelab/platform-api:TIMESTAMP-amd64 -n platform
kubectl set image deployment/platform-dashboard dashboard=git.example.com/homelab/platform-dashboard:TIMESTAMP-amd64 -n platform
```

### 🚫 Abandoned Approaches

- **Automated GitHub-based builds**: Authentication issues with private repos
- **ArgoCD pre-sync hooks**: Too complex for current needs
- **Complex multi-arch manifests**: Architecture conflicts
- **Using `:latest` tags**: Architecture confusion between ARM64 (Mac) and x86_64 (EliteMini)

### 💡 Recommendations

1. **Use specific timestamped tags** instead of `:latest` to avoid architecture conflicts
2. **Build on M3 Mac with explicit `--platform linux/amd64`** for EliteMini compatibility
3. **Update GitOps manifests** with specific image tags for reliable deployments
4. **Avoid manual kubectl commands** - prefer GitOps workflow

### 🎯 Next Steps

- [ ] Update k8s/platform/\*.yaml with working image tags
- [ ] Clean up test build jobs
- [ ] Test platform functionality with new images
- [ ] Consider ArgoCD Image Updater for automatic updates

### ✅ FINAL WORKING SOLUTION (2025-07-03)

**What Actually Works:**

1. **Build on M3 Mac with explicit x86_64 target**: `docker buildx build --platform linux/amd64`
2. **Push to GitHub packages**: `ghcr.io/chrisknu/` (not Gitea registry due to architecture issues)
3. **Use specific timestamped tags**: Never use `:latest` due to architecture confusion
4. **Update GitOps manifests**: Edit k8s/platform/\*.yaml with specific image tags
5. **Commit and push**: Let ArgoCD sync (avoid manual kubectl commands)

**Working Images (TESTED AND CONFIRMED):**

- API: `ghcr.io/chrisknu/platform-api:20250703-000401` ✅
- Dashboard: `ghcr.io/chrisknu/platform-dashboard:v20250619-132248` ✅

**CRITICAL LESSONS FOR NEXT TIME:**

- ❌ **DON'T use Gitea registry** - architecture issues with multi-arch builds
- ❌ **DON'T use `:latest` tags** - causes ARM64/x86_64 confusion
- ❌ **DON'T use manual kubectl commands** - violates GitOps principles
- ✅ **DO build with `--platform linux/amd64`** for EliteMini compatibility
- ✅ **DO push to GitHub packages** (`ghcr.io/chrisknu/`)
- ✅ **DO use specific timestamped tags** in GitOps manifests
- ✅ **DO follow GitOps workflow** - commit, push, let ArgoCD sync

**Platform Status: FULLY OPERATIONAL** 🚀

- Frontend: Working ✅
- Backend: Working ✅
- Real data flowing ✅
- Ready for project deployment testing ✅
