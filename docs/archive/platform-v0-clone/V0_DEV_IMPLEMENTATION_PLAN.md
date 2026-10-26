# V0.dev Clone Implementation Plan

## Overview
Building a local v0.dev clone that generates, builds, and deploys web applications from natural language prompts.

## Core Architecture Principles
1. **Layered Approach**: Each layer must be solid before moving up
2. **Test-First**: Automated tests at every layer
3. **Simple & Direct**: No overengineering, use existing tools
4. **Progressive Enhancement**: Start simple, add complexity only when working

## Implementation Layers

### Layer 0: Foundation & Testing Framework
- Set up Jest/Vitest for platform-api
- Create test database for integration tests
- Mock services for unit testing
- CI pipeline for automated testing

### Layer 1: Core AI Code Generation
- **Input**: User prompt (project description)
- **Process**: 
  - Call CodeGen service (OpenRouter)
  - Generate project structure
  - Create Next.js/React components
  - Add Tailwind styling
- **Output**: Complete file structure in memory
- **Tests**: 
  - Prompt parsing
  - Code generation quality
  - File structure validation

### Layer 2: Git Integration (Gitea)
- **Input**: Generated code files
- **Process**:
  - Create Gitea repository via API
  - Initialize with generated code
  - Commit and push to main branch
- **Output**: Git repository URL
- **Tests**:
  - Repository creation
  - File commit verification
  - Branch management

### Layer 3: Build Pipeline (Kaniko)
- **Input**: Git repository
- **Process**:
  - Generate Dockerfile
  - Create Kaniko job in K8s
  - Build and push to registry
- **Output**: Container image URL
- **Tests**:
  - Dockerfile generation
  - Build job success
  - Image availability

### Layer 4: Kubernetes Deployment
- **Input**: Container image
- **Process**:
  - Generate K8s manifests (Deployment, Service)
  - Create project namespace
  - Apply manifests
- **Output**: Running deployment
- **Tests**:
  - Manifest generation
  - Deployment health
  - Service connectivity

### Layer 5: Domain & Ingress Management
- **Input**: Running service
- **Process**:
  - Generate subdomain
  - Create Ingress with Traefik
  - Configure SSL with cert-manager
- **Output**: Public URL
- **Tests**:
  - Ingress creation
  - Domain resolution
  - SSL certificate

## Testing Strategy

### Unit Tests (Per Service)
```typescript
describe('AICodeGenerator', () => {
  test('generates valid Next.js project structure')
  test('includes requested features')
  test('handles error cases')
})
```

### Integration Tests (Per Layer)
```typescript
describe('Layer 2: Git Integration', () => {
  test('creates repository successfully')
  test('commits all generated files')
  test('handles auth correctly')
})
```

### End-to-End Tests
```typescript
describe('Complete Flow', () => {
  test('prompt to deployed app in < 2 minutes')
  test('app is accessible via HTTPS')
  test('database provisioning works')
})
```

## Implementation Phases

### Phase 1: Foundation (Week 1)
1. Set up testing framework
2. Create test utilities
3. Mock external services
4. Document API contracts

### Phase 2: Core Pipeline (Week 2)
1. Implement Layer 1: Code Generation
2. Implement Layer 2: Git Integration
3. Write comprehensive tests
4. Validate with simple projects

### Phase 3: Build & Deploy (Week 3)
1. Implement Layer 3: Build Pipeline
2. Implement Layer 4: K8s Deployment
3. Test with various project types
4. Performance optimization

### Phase 4: Production Ready (Week 4)
1. Implement Layer 5: Domain Management
2. Add monitoring/observability
3. Create admin dashboard
4. Documentation & examples

## Success Metrics
- [ ] 95% test coverage
- [ ] < 2 minute prompt-to-deploy time
- [ ] Zero manual intervention required
- [ ] Supports Next.js, React, Vue projects
- [ ] Handles 10 concurrent deployments

## Key APIs to Implement

### 1. Project Generation API
```typescript
POST /api/projects/generate
{
  "prompt": "Create a todo app with authentication",
  "framework": "nextjs",
  "features": ["auth", "database", "tailwind"]
}
```

### 2. Build Pipeline API
```typescript
POST /api/builds/trigger
{
  "projectId": "xxx",
  "gitUrl": "https://git.example.com/...",
  "branch": "main"
}
```

### 3. Deployment API
```typescript
POST /api/deployments/create
{
  "projectId": "xxx",
  "imageUrl": "git.example.com/...",
  "environment": "production"
}
```

## Tools & Technologies
- **AI**: CodeGen Service (OpenRouter), Ollama (fallback)
- **Git**: Gitea API
- **Build**: Kaniko (in-cluster builds)
- **Deploy**: Kubernetes API
- **Ingress**: Traefik
- **SSL**: cert-manager
- **Testing**: Jest/Vitest, Supertest
- **Monitoring**: Prometheus, Grafana

## Risk Mitigation
1. **AI Failures**: Fallback to Ollama, template-based generation
2. **Build Failures**: Retry logic, pre-built base images
3. **Deploy Failures**: Rollback mechanism, health checks
4. **Resource Limits**: Queue management, rate limiting

## Development Workflow
1. Create feature branch in worktree
2. Implement with TDD approach
3. Run automated tests
4. Deploy to staging namespace
5. Validate end-to-end
6. Merge to main

## Next Steps
1. Set up test framework in platform-api
2. Create integration test database
3. Implement Layer 1 with full test coverage
4. Validate foundation before proceeding