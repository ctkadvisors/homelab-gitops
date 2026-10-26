# Archived: v0.dev Clone Platform (August 2025)

These files document the custom v0.dev clone platform that was in development from June-August 2025.

**Status:** Superseded by bolt.diy adoption (see `docs/2025-12-INFRASTRUCTURE-EVALUATION.md`)

## Files

- `CICD_DEPLOYMENT_GUIDE.md` - Guide for testing CI/CD functionality
- `CICD_IMPLEMENTATION_SUMMARY.md` - Summary of what was built
- `NEXTJS_PLATFORM_PLAN.md` - Original platform planning document
- `PLATFORM_BUILD_NOTES.md` - Build troubleshooting notes
- `PLATFORM_DEPLOYMENT.md` - Deployment guide

## What Was Built

A 5-layer orchestration pipeline for AI-powered app generation:
1. ✅ Layer 1: AI Generation (Planner + Implementer Agents)
2. ✅ Layer 2: Git Repository (Gitea integration)
3. ⚠️ Layer 3: Container Build (BuildKit) - Partial
4. ❌ Layer 4: Kubernetes Deployment - Not completed
5. ❌ Layer 5: Ingress/Domain Allocation - Not completed

## Why Archived

The custom platform was superseded by bolt.diy, an open-source project with:
- 18.7k GitHub stars
- 1600+ contributors
- Native Ollama integration
- Active maintenance

See `docs/2025-12-INFRASTRUCTURE-EVALUATION.md` for full analysis.

