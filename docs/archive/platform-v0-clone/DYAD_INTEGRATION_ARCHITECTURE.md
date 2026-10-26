# Dyad Integration Architecture Plan

## Executive Summary

**Recommended Approach: Hybrid Architecture Evolution**

Based on analysis of Dyad (Electron-based local AI app builder) and our current v0.dev clone implementation, this plan recommends a **hybrid evolution** that:

1. **Immediately fixes** the template fallback issue preventing real AI generation
2. **Adopts Dyad's best practices** for context management, streaming, and multi-provider support
3. **Maintains cloud deployment capability** while adding local-first options
4. **Evolves toward a unified platform** supporting both deployment paradigms

**Success Metrics:**
- ✅ Real AI generation (not templates) within 3 days
- ✅ Streaming responses and improved UX within 1-2 weeks  
- ✅ Multi-provider AI support within 2-3 weeks
- ✅ Hybrid local/cloud architecture within 3-4 weeks

## Current State Analysis

### Critical Issues Identified

1. **🚨 AI Generation Fallback to Templates**
   - `aiGeneratorServiceV2` calls agents but agents aren't properly connected to models
   - Real AI generation fails → falls back to pre-defined templates
   - User gets wrong code (e.g., blog template for portfolio request)

2. **🔧 Model Provider Connectivity Issues**
   - Ollama running and accessible (models: qwen2.5-coder:7b, mistral:7b, etc.)
   - ModelProviderService exists but not properly integrated with agents
   - Missing database records for model configurations

3. **📊 Database Schema Gaps**
   - `orchestration_jobs` and `orchestration_logs` tables exist
   - Missing model provider and agent configuration data
   - Agent coordination tables exist but not populated

4. **🏗️ BuildKit RBAC Issues**
   - Build pipeline code exists but lacks Kubernetes permissions
   - Container deployment fails due to missing RBAC

### Current Architecture Strengths

1. **Solid Infrastructure Foundation**
   - K3s cluster with GPU-enabled Jetson nodes
   - Ollama running with multiple code generation models
   - Comprehensive orchestration service architecture
   - GitOps workflow with Gitea integration

2. **Advanced Database Schema**
   - Multi-agent coordination tables ready
   - Model provider abstraction layer
   - Comprehensive orchestration tracking

3. **Well-Designed Services**
   - Separation of concerns (planning vs. implementation agents)
   - Structured project generation workflow
   - Built-in retry and error handling

## Immediate Fixes (1-3 Days)

### Priority 1: Fix AI Generation Pipeline

**Root Cause:** Agents aren't properly calling models through ModelProviderService

**Solution Steps:**

1. **Populate Model Configuration Database**
   ```sql
   -- Add Ollama provider
   INSERT INTO model_providers (name, provider_type, base_url, is_active, is_free, priority)
   VALUES ('local-ollama', 'ollama', 'http://ollama.ai-services.svc.cluster.local:11434', true, true, 100);
   
   -- Add model configurations for available models
   INSERT INTO model_configurations (provider_id, model_name, display_name, model_id, is_free, optimal_for, performance_tier)
   VALUES 
     (provider_id, 'qwen2.5-coder:7b', 'Qwen2.5 Coder 7B', 'qwen2.5-coder:7b', true, ARRAY['coding', 'planning'], 'balanced'),
     (provider_id, 'mistral:7b-instruct', 'Mistral 7B Instruct', 'mistral:7b-instruct', true, ARRAY['planning', 'review'], 'quality');
   ```

2. **Fix Agent Base Class Integration**
   ```typescript
   // Update BaseAgent to use ModelProviderService
   protected async callModel(prompt: string, context: AgentContext): Promise<string> {
     const model = await this.modelProviderService.getBestModelForTask(this.getOptimalTask(), true);
     if (!model) throw new Error('No available model for task');
     
     const response = await this.modelProviderService.callModel(model, [
       { role: 'user', content: prompt }
     ]);
     
     return response.content;
   }
   ```

3. **Update Agent Implementations**
   - Fix `PlannerAgent` to call models instead of returning mock data
   - Fix `ImplementerAgent` to generate real code
   - Add proper error handling and fallbacks

### Priority 2: Database Migration

**Create migration script:**
```bash
./scripts/apply-database-migrations.sh
```

**Populate initial data:**
```sql
-- Set up default agent definitions
INSERT INTO agent_definitions (agent_type, display_name, model_configuration_id, system_prompt)
VALUES 
  ('planner', 'Project Planner', (SELECT id FROM model_configurations WHERE model_id = 'qwen2.5-coder:7b'), 'You are an expert software architect...'),
  ('implementer', 'Code Implementer', (SELECT id FROM model_configurations WHERE model_id = 'qwen2.5-coder:7b'), 'You are an expert developer...');
```

### Priority 3: Fix BuildKit RBAC

**Add missing Kubernetes permissions:**
```yaml
# k8s-kustomized/base/platform/platform-api-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: platform-api-buildkit
rules:
- apiGroups: [""]
  resources: ["pods", "services"]
  verbs: ["create", "get", "list", "delete"]
- apiGroups: ["batch"]
  resources: ["jobs"]
  verbs: ["create", "get", "list", "delete", "watch"]
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["create", "get"]
```

## Dyad Integration Opportunities (1-2 Weeks)

### 1. Custom AI Markup Language

**Dyad Strength:** Custom markup for AI prompt engineering
**Our Integration:** Extend agent system prompts with structured markup

```typescript
interface AIMarkupTemplate {
  role: 'planner' | 'implementer' | 'reviewer';
  template: string;
  variables: Record<string, string>;
  context_requirements: string[];
}

// Example markup for code generation
const IMPLEMENTER_MARKUP = `
<ai-context>
  <project-type>{framework}</project-type>
  <features>{features}</features>
  <existing-files>{context.files}</existing-files>
</ai-context>

<ai-task>
  Create {component_type} component for {description}
  
  Requirements:
  - Use {styling} for styles
  - Follow {framework} best practices
  - Integrate with {database} if needed
</ai-task>

<ai-output format="typescript">
  Return only the code content without explanations
</ai-output>
`;
```

### 2. Real-Time Streaming Responses

**Dyad Strength:** Streaming AI responses for better UX
**Our Integration:** Add streaming to ModelProviderService

```typescript
// Add streaming support to model calls
async streamModel(
  modelConfig: ModelConfiguration,
  messages: Array<{role: string; content: string}>,
  onChunk: (chunk: string) => void
): Promise<string> {
  const response = await fetch(`${modelConfig.base_url}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      model: modelConfig.model_id,
      messages,
      stream: true
    })
  });

  let fullResponse = '';
  const reader = response.body?.getReader();
  
  while (true) {
    const { done, value } = await reader!.read();
    if (done) break;
    
    const chunk = new TextDecoder().decode(value);
    const lines = chunk.split('\n').filter(line => line.trim());
    
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        const data = JSON.parse(line.slice(6));
        if (data.message?.content) {
          onChunk(data.message.content);
          fullResponse += data.message.content;
        }
      }
    }
  }
  
  return fullResponse;
}
```

### 3. Advanced Context Management

**Dyad Strength:** Sophisticated context passing between AI calls
**Our Integration:** Enhanced agent coordination system

```typescript
interface EnhancedAgentContext {
  orchestrationJobId: string;
  conversationHistory: Array<{
    agent: string;
    input: string;
    output: string;
    timestamp: Date;
  }>;
  projectContext: {
    files: Map<string, string>;
    dependencies: string[];
    framework: string;
    userRequirements: string[];
  };
  sharedMemory: Map<string, any>;
}

class ContextManager {
  async getContextForAgent(
    orchestrationJobId: string, 
    agentType: string
  ): Promise<EnhancedAgentContext> {
    // Build context from database and previous agent outputs
    // Include relevant file contents, previous decisions, etc.
  }
  
  async updateContext(
    orchestrationJobId: string,
    agentType: string,
    newContext: Partial<EnhancedAgentContext>
  ): Promise<void> {
    // Update shared context state
  }
}
```

### 4. Multi-Provider AI Support

**Dyad Strength:** Support for multiple AI providers with automatic fallback
**Our Integration:** Enhanced ModelProviderService with intelligence

```typescript
class IntelligentModelSelector {
  async selectOptimalModel(
    task: string,
    context: AgentContext,
    requirements: {
      maxCost?: number;
      maxLatency?: number;
      preferLocal?: boolean;
    }
  ): Promise<ModelConfiguration> {
    const candidates = await this.getModelsForTask(task);
    
    // Score models based on:
    // - Performance for task type
    // - Current availability/load
    // - Cost constraints
    // - Latency requirements
    // - Local vs cloud preference
    
    return this.selectBestCandidate(candidates, requirements);
  }
  
  async fallbackChain(
    task: string,
    prompt: string,
    context: AgentContext
  ): Promise<string> {
    const fallbackOrder = await this.getFallbackOrder(task);
    
    for (const model of fallbackOrder) {
      try {
        return await this.modelProviderService.callModel(model, prompt, context);
      } catch (error) {
        console.warn(`Model ${model.model_name} failed, trying next...`);
        continue;
      }
    }
    
    throw new Error('All model providers failed');
  }
}
```

## Architecture Evolution (2-4 Weeks)

### Hybrid Local/Cloud Architecture

**Decision: Maintain Cloud Deployment + Add Local Option**

Rather than pivoting completely to Electron like Dyad, we'll create a hybrid architecture that supports both deployment paradigms:

#### Architecture Diagram (Text)

```
┌─────────────────────────┐    ┌─────────────────────────┐
│     Web Interface       │    │    Desktop Client       │
│   (platform.example)   │    │   (Electron/Tauri)     │
├─────────────────────────┤    ├─────────────────────────┤
│   Platform Dashboard    │    │   Local Dashboard       │
│   (Next.js 15)         │    │   (React/Vue)          │
└─────────────────────────┘    └─────────────────────────┘
            │                              │
            ▼                              ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│   Cloud Platform API    │    │    Local Platform API   │
│   (K8s + GPU Cluster)   │    │   (Docker Desktop)      │
├─────────────────────────┤    ├─────────────────────────┤
│ • Ollama (GPU)          │    │ • Ollama (CPU/GPU)      │
│ • Full K8s Deploy      │    │ • Local Docker          │
│ • GitOps               │    │ • Local Git             │
│ • Production Ready     │    │ • Development Focus     │
└─────────────────────────┘    └─────────────────────────┘
```

#### Implementation Strategy

1. **Shared Core Services**
   ```typescript
   // platform-core/ (shared between cloud and local)
   export class PlatformCore {
     constructor(
       private deploymentTarget: 'cloud' | 'local',
       private config: PlatformConfig
     ) {}
     
     async generateProject(request: GenerateRequest): Promise<Project> {
       // Same generation logic, different deployment targets
     }
   }
   ```

2. **Deployment Target Abstraction**
   ```typescript
   interface DeploymentProvider {
     deploy(project: Project): Promise<DeploymentResult>;
     getStatus(deploymentId: string): Promise<DeploymentStatus>;
     delete(deploymentId: string): Promise<void>;
   }
   
   class CloudDeploymentProvider implements DeploymentProvider {
     // Kubernetes + Gitea + BuildKit implementation
   }
   
   class LocalDeploymentProvider implements DeploymentProvider {
     // Docker Desktop + local git implementation  
   }
   ```

3. **Configuration-Driven Behavior**
   ```yaml
   # config/cloud.yaml
   deployment:
     target: cloud
     kubernetes:
       namespace: project-{id}
       registry: git.example.com
     ai:
       providers:
         - type: ollama
           url: http://ollama.ai-services.svc.cluster.local:11434
         - type: openrouter
           fallback: true
   
   # config/local.yaml  
   deployment:
     target: local
     docker:
       network: platform-local
     ai:
       providers:
         - type: ollama
           url: http://localhost:11434
         - type: openai
           fallback: true
   ```

### Benefits of Hybrid Approach

1. **Maintains Current Investment**
   - Cloud infrastructure continues to work
   - GitOps and production deployments preserved
   - Team collaboration features remain

2. **Adds Developer-Friendly Local Option**
   - Faster iteration for development
   - Works offline
   - No cluster management overhead
   - Better debugging experience

3. **Unified User Experience**
   - Same UI for both deployment targets
   - Project portability between cloud and local
   - Consistent AI generation quality

4. **Business Model Flexibility**
   - Free local development tier
   - Premium cloud deployment features
   - Enterprise on-premises deployment

## Technical Implementation Details

### Phase 1: Immediate Fixes (1-3 days)

#### File Changes Required

1. **Fix Agent Integration**
   ```typescript
   // platform-api/src/agents/baseAgent.ts
   export abstract class BaseAgent {
     constructor(
       protected agentType: string,
       protected modelProviderService: ModelProviderService = modelProviderService
     ) {}
     
     async execute(context: AgentContext, prompt: string): Promise<AgentResult> {
       const model = await this.modelProviderService.getBestModelForTask(
         this.getOptimalTask(), 
         true // prefer free models
       );
       
       if (!model) {
         throw new Error(`No available model for ${this.agentType} task`);
       }
       
       const messages = this.prepareMessages(prompt, context);
       const response = await this.modelProviderService.callModel(model, messages);
       
       return this.processResponse(response.content, context);
     }
   }
   ```

2. **Database Initialization Script**
   ```bash
   # scripts/init-model-providers.sh
   #!/bin/bash
   kubectl exec -n database deployment/postgresql -- psql -U platform -d platform << 'EOF'
   
   -- Insert Ollama provider
   INSERT INTO model_providers (name, provider_type, base_url, is_active, is_free, priority)
   VALUES ('local-ollama', 'ollama', 'http://ollama.ai-services.svc.cluster.local:11434', true, true, 100)
   ON CONFLICT (name) DO UPDATE SET is_active = true;
   
   -- Get provider ID
   \set provider_id (SELECT id FROM model_providers WHERE name = 'local-ollama')
   
   -- Insert model configurations
   INSERT INTO model_configurations (provider_id, model_name, display_name, model_id, is_free, optimal_for, performance_tier, max_context_tokens, max_output_tokens)
   VALUES 
     (:'provider_id', 'qwen2.5-coder:7b', 'Qwen2.5 Coder 7B', 'qwen2.5-coder:7b', true, ARRAY['coding', 'implementation'], 'balanced', 4096, 4096),
     (:'provider_id', 'mistral:7b-instruct', 'Mistral 7B Instruct', 'mistral:7b-instruct', true, ARRAY['planning', 'review'], 'quality', 8192, 4096),
     (:'provider_id', 'qwen2.5-coder:0.5b', 'Qwen2.5 Coder 0.5B (Fast)', 'qwen2.5-coder:0.5b', true, ARRAY['coding'], 'fast', 2048, 2048)
   ON CONFLICT (provider_id, model_id) DO UPDATE SET is_active = true;
   
   -- Insert agent definitions
   INSERT INTO agent_definitions (agent_type, display_name, model_configuration_id, system_prompt, temperature)
   VALUES 
     ('planner', 'Project Planner', 
      (SELECT id FROM model_configurations WHERE model_id = 'mistral:7b-instruct'), 
      'You are an expert software architect and project planner. Create detailed implementation plans for web applications.',
      0.3),
     ('implementer', 'Code Implementer',
      (SELECT id FROM model_configurations WHERE model_id = 'qwen2.5-coder:7b'),
      'You are an expert developer. Generate high-quality, production-ready code based on specifications.',
      0.1)
   ON CONFLICT (agent_type) DO UPDATE SET is_active = true;
   
   EOF
   ```

3. **BuildKit RBAC Fix**
   ```yaml
   # k8s-kustomized/base/platform/platform-api-rbac-extension.yaml
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRole
   metadata:
     name: platform-api-buildkit
   rules:
   - apiGroups: [""]
     resources: ["pods", "pods/log", "services", "secrets", "configmaps"]
     verbs: ["create", "get", "list", "watch", "delete"]
   - apiGroups: ["batch"]
     resources: ["jobs"]
     verbs: ["create", "get", "list", "watch", "delete"]
   - apiGroups: ["apps"]
     resources: ["deployments", "replicasets"]
     verbs: ["create", "get", "list", "watch", "delete", "patch", "update"]
   ---
   apiVersion: rbac.authorization.k8s.io/v1
   kind: ClusterRoleBinding
   metadata:
     name: platform-api-buildkit
   roleRef:
     apiGroup: rbac.authorization.k8s.io
     kind: ClusterRole
     name: platform-api-buildkit
   subjects:
   - kind: ServiceAccount
     name: platform-api
     namespace: platform
   ```

#### Deployment Commands

```bash
# 1. Apply database migrations
kubectl apply -f platform-api/sql/migrations/

# 2. Initialize model providers
./scripts/init-model-providers.sh

# 3. Apply RBAC fixes
kubectl apply -k k8s-kustomized/overlays/production

# 4. Restart platform-api to pick up changes
kubectl rollout restart -n platform deployment/platform-api

# 5. Test AI generation
curl -X POST https://platform.example.com/api/v1/orchestration/generate-deploy \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Create a simple portfolio website with hero section"}'
```

### Phase 2: Dyad Integration (1-2 weeks)

#### Streaming Implementation

```typescript
// platform-api/src/services/streamingOrchestrationService.ts
export class StreamingOrchestrationService extends OrchestrationService {
  async generateAndDeployWithStreaming(
    request: GenerateDeployRequest,
    onProgress: (update: OrchestrationProgress) => void
  ): Promise<GenerateDeployResult> {
    
    const stream = new EventEmitter();
    
    // Set up streaming progress updates
    stream.on('progress', onProgress);
    
    // Override agent calls to use streaming
    const originalGenerateProjectCode = this.generateProjectCode;
    this.generateProjectCode = async (state: OrchestrationState) => {
      const streamingResult = await this.generateWithStreaming(state, stream);
      return streamingResult;
    };
    
    return super.generateAndDeploy(request);
  }
  
  private async generateWithStreaming(
    state: OrchestrationState,
    stream: EventEmitter
  ): Promise<GeneratedProject> {
    // Stream planning phase
    stream.emit('progress', {
      stage: 'planning',
      message: 'Analyzing requirements...',
      progress: 10
    });
    
    const planResult = await plannerAgent.executeWithStreaming(
      state,
      (chunk) => stream.emit('progress', {
        stage: 'planning', 
        message: `Planning: ${chunk}`,
        progress: 15
      })
    );
    
    // Stream implementation phase
    const tasks = await this.getPlannedTasks(state.projectId);
    for (let i = 0; i < tasks.length; i++) {
      const task = tasks[i];
      stream.emit('progress', {
        stage: 'implementing',
        message: `Implementing ${task.title}...`,
        progress: 30 + (i / tasks.length) * 50
      });
      
      await implementerAgent.generateForTaskWithStreaming(
        state,
        task.task_id,
        (chunk) => stream.emit('progress', {
          stage: 'implementing',
          message: `Code: ${chunk.substring(0, 100)}...`,
          progress: 30 + (i / tasks.length) * 50
        })
      );
    }
    
    return this.assembleGeneratedProject(state.projectId);
  }
}
```

#### Advanced Context Management

```typescript
// platform-api/src/services/contextManager.ts
export class AdvancedContextManager {
  private contexts = new Map<string, OrchestrationContext>();
  
  async buildContext(orchestrationJobId: string): Promise<OrchestrationContext> {
    // Get previous agent outputs
    const executions = await this.getAgentExecutions(orchestrationJobId);
    
    // Build file context from previous implementations
    const fileContext = await this.buildFileContext(executions);
    
    // Extract user requirements and constraints
    const requirements = await this.extractRequirements(orchestrationJobId);
    
    // Build dependency graph
    const dependencies = await this.analyzeDependencies(fileContext);
    
    return {
      orchestrationJobId,
      conversationHistory: executions.map(e => ({
        agent: e.agent_type,
        input: e.input_prompt,
        output: e.output_response,
        timestamp: e.created_at
      })),
      projectContext: {
        files: fileContext,
        dependencies,
        requirements: requirements.functional,
        constraints: requirements.technical,
        framework: requirements.framework
      },
      sharedMemory: new Map()
    };
  }
  
  async updateContextWithAgentOutput(
    orchestrationJobId: string,
    agentType: string,
    output: AgentOutput
  ): Promise<void> {
    const context = this.contexts.get(orchestrationJobId);
    if (!context) return;
    
    // Update project files if agent generated code
    if (output.type === 'code' && output.filePath) {
      context.projectContext.files.set(output.filePath, output.content);
    }
    
    // Update shared memory with agent insights
    if (output.insights) {
      for (const [key, value] of Object.entries(output.insights)) {
        context.sharedMemory.set(`${agentType}.${key}`, value);
      }
    }
    
    // Update conversation history
    context.conversationHistory.push({
      agent: agentType,
      input: output.originalPrompt,
      output: output.response,
      timestamp: new Date()
    });
  }
}
```

### Phase 3: Hybrid Architecture (2-4 weeks)

#### Local Platform Service

```typescript
// platform-local/src/localPlatformService.ts
export class LocalPlatformService implements PlatformService {
  private docker: Docker;
  private localGit: SimpleGit;
  
  constructor() {
    this.docker = new Docker();
    this.localGit = simpleGit('./local-projects');
  }
  
  async deployProject(project: GeneratedProject): Promise<LocalDeployment> {
    // 1. Create local project directory
    const projectPath = path.join('./local-projects', project.name);
    await fs.mkdir(projectPath, { recursive: true });
    
    // 2. Write project files
    for (const file of project.files) {
      const filePath = path.join(projectPath, file.path);
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      await fs.writeFile(filePath, file.content);
    }
    
    // 3. Initialize git repository
    await this.localGit.cwd(projectPath);
    await this.localGit.init();
    await this.localGit.add('.');
    await this.localGit.commit('Initial commit from AI generation');
    
    // 4. Build Docker image
    const imageTag = `local-platform/${project.name}:latest`;
    await this.buildDockerImage(projectPath, imageTag);
    
    // 5. Start container
    const container = await this.docker.createContainer({
      Image: imageTag,
      name: `platform-${project.name}`,
      HostConfig: {
        PortBindings: {
          '3000/tcp': [{ HostPort: '0' }] // Auto-assign port
        }
      }
    });
    
    await container.start();
    const containerInfo = await container.inspect();
    const port = containerInfo.NetworkSettings.Ports['3000/tcp'][0].HostPort;
    
    return {
      deploymentId: container.id,
      projectName: project.name,
      url: `http://localhost:${port}`,
      status: 'running',
      containerInfo
    };
  }
  
  private async buildDockerImage(projectPath: string, tag: string): Promise<void> {
    // Generate Dockerfile based on project type
    const dockerfile = await this.generateDockerfile(projectPath);
    await fs.writeFile(path.join(projectPath, 'Dockerfile'), dockerfile);
    
    // Build image
    const stream = await this.docker.buildImage({
      context: projectPath,
      src: ['.']
    }, { t: tag });
    
    await new Promise((resolve, reject) => {
      this.docker.modem.followProgress(stream, (err, res) => {
        if (err) reject(err);
        else resolve(res);
      });
    });
  }
}
```

#### Electron Desktop Client

```typescript
// platform-desktop/src/main/main.ts
import { app, BrowserWindow, ipcMain } from 'electron';
import { LocalPlatformService } from '../services/localPlatformService';

class PlatformDesktopApp {
  private mainWindow: BrowserWindow | null = null;
  private platformService: LocalPlatformService;
  
  constructor() {
    this.platformService = new LocalPlatformService();
  }
  
  async createWindow(): Promise<void> {
    this.mainWindow = new BrowserWindow({
      width: 1200,
      height: 800,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
        preload: path.join(__dirname, 'preload.js')
      }
    });
    
    // Load the React dashboard
    if (process.env.NODE_ENV === 'development') {
      await this.mainWindow.loadURL('http://localhost:3000');
    } else {
      await this.mainWindow.loadFile(path.join(__dirname, '../renderer/index.html'));
    }
  }
  
  setupIPC(): void {
    // Handle project generation requests
    ipcMain.handle('generate-project', async (event, request: GenerateRequest) => {
      try {
        const result = await this.platformService.generateProject(request);
        return { success: true, data: result };
      } catch (error) {
        return { success: false, error: error.message };
      }
    });
    
    // Handle deployment requests  
    ipcMain.handle('deploy-project', async (event, projectId: string) => {
      try {
        const result = await this.platformService.deployProject(projectId);
        return { success: true, data: result };
      } catch (error) {
        return { success: false, error: error.message };
      }
    });
    
    // Handle streaming progress updates
    ipcMain.handle('subscribe-progress', (event, projectId: string) => {
      this.platformService.onProgress(projectId, (progress) => {
        event.sender.send('progress-update', progress);
      });
    });
  }
}
```

## Migration Path

### Backwards Compatibility Strategy

1. **API Versioning**
   ```typescript
   // Support both v1 (current) and v2 (enhanced) APIs
   app.use('/api/v1', legacyRoutes);
   app.use('/api/v2', enhancedRoutes);
   ```

2. **Feature Flags**
   ```typescript
   const features = {
     useStreamingGeneration: process.env.ENABLE_STREAMING === 'true',
     useAdvancedContext: process.env.ENABLE_ADVANCED_CONTEXT === 'true',
     enableLocalDeployment: process.env.ENABLE_LOCAL_DEPLOYMENT === 'true'
   };
   ```

3. **Gradual Rollout**
   ```bash
   # Week 1: Fix immediate issues, maintain current API
   kubectl patch deployment platform-api -p '{"spec":{"template":{"metadata":{"labels":{"version":"v3.3.0"}}}}}'
   
   # Week 2: Add streaming support as opt-in feature
   kubectl set env deployment/platform-api ENABLE_STREAMING=true
   
   # Week 3: Enable advanced context management
   kubectl set env deployment/platform-api ENABLE_ADVANCED_CONTEXT=true
   
   # Week 4: Launch local deployment option
   kubectl set env deployment/platform-api ENABLE_LOCAL_DEPLOYMENT=true
   ```

### Testing and Validation Approach

1. **Automated Testing Pipeline**
   ```bash
   # Test current functionality
   npm run test:integration:v1
   
   # Test new features
   npm run test:integration:v2
   
   # Test backwards compatibility
   npm run test:compatibility
   
   # Test local deployment
   npm run test:local-deployment
   ```

2. **Progressive Enhancement Testing**
   ```typescript
   describe('AI Generation Pipeline', () => {
     it('should work with current template fallback', async () => {
       // Test existing behavior
     });
     
     it('should work with real AI models when available', async () => {
       // Test enhanced behavior
     });
     
     it('should gracefully fallback when AI unavailable', async () => {
       // Test resilience
     });
   });
   ```

3. **User Acceptance Testing**
   - Deploy to staging environment with feature flags
   - A/B test streaming vs. non-streaming UX
   - Gather feedback on local vs. cloud deployment preferences

## Resource Requirements

### Compute Resources

**Current Infrastructure (Sufficient):**
- EliteMini control plane (4 cores, 16GB RAM)
- Jetson Orin Nano GPU nodes (6-core ARM, 8GB RAM, GPU)
- 10+ AI models already loaded (qwen2.5-coder:7b, mistral:7b, etc.)

**Additional Requirements:**
- **Database**: +2GB storage for agent coordination tables (existing PostgreSQL)
- **Registry**: +10GB for container images (existing Gitea registry)
- **Local Development**: Docker Desktop with 4GB RAM allocation

### Network Requirements

**Current Network (Adequate):**
- Internal cluster networking: 10.42.0.0/16
- Load balancer pool: 192.168.131.200-210
- External domains: *.example.com (Let's Encrypt SSL)

**No Additional Network Changes Required**

### Storage Requirements

**Current Storage (Sufficient):**
- Models: /opt/ollama-models (~50GB used, ~100GB available)
- Database: PostgreSQL with 100GB allocation
- Container Registry: Gitea with 500GB allocation

**Estimated Additional Usage:**
- Database growth: +1GB/month (orchestration logs)
- Container images: +5GB/month (generated project builds)
- Local projects: +10GB/developer (local deployment mode)

## Success Metrics and Validation Criteria

### Phase 1 Success Criteria (1-3 days)

✅ **AI Generation Working**
- [ ] Generate project with prompt: "Create a portfolio with hero section"
- [ ] Verify generated code is NOT template fallback
- [ ] Confirm Ollama models are being called
- [ ] Check database for agent execution records

✅ **Database Integration Complete**
- [ ] All migration scripts applied successfully
- [ ] Model providers and configurations populated
- [ ] Agent definitions created and active
- [ ] Test queries return expected data

✅ **BuildKit Permissions Fixed**  
- [ ] Create build job without RBAC errors
- [ ] Build simple Next.js project successfully
- [ ] Deploy to Kubernetes namespace
- [ ] Access deployed application via ingress

**Validation Commands:**
```bash
# Test AI generation endpoint
curl -X POST https://platform.example.com/api/v1/orchestration/generate-deploy \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Create a simple blog with dark mode toggle", "framework": "nextjs"}'

# Verify models are accessible
kubectl exec -n ai-services deployment/ollama -- ollama list

# Check database state
kubectl exec -n database deployment/postgresql -- psql -U platform -d platform \
  -c "SELECT COUNT(*) FROM model_providers WHERE is_active = true;"
```

### Phase 2 Success Criteria (1-2 weeks)

✅ **Streaming Responses Active**
- [ ] Real-time progress updates during generation
- [ ] WebSocket connection established and maintained
- [ ] Progressive code generation visible in UI
- [ ] Smooth UX without long loading states

✅ **Enhanced Context Management**
- [ ] Agents share context between calls
- [ ] File context maintained across implementation tasks
- [ ] Requirements properly extracted and preserved
- [ ] Agent coordination messages logged

✅ **Multi-Provider Fallback**
- [ ] Automatic fallback from Ollama to OpenRouter
- [ ] Cost and latency tracking per provider
- [ ] Provider selection based on task requirements
- [ ] Graceful handling of provider failures

**Validation Tests:**
```typescript
// Test streaming generation
const streamingTest = await startStreamingGeneration({
  prompt: "Create a todo app with authentication"
});

expect(streamingTest.progressUpdates.length).toBeGreaterThan(5);
expect(streamingTest.finalResult.files.length).toBeGreaterThan(3);

// Test context management
const contextTest = await generateWithContext({
  prompt: "Add user authentication to existing todo app",
  existingFiles: previousProject.files
});

expect(contextTest.modifiedFiles).toContain('src/components/TodoList.tsx');
expect(contextTest.newFiles).toContain('src/lib/auth.ts');
```

### Phase 3 Success Criteria (2-4 weeks)

✅ **Hybrid Architecture Operational**
- [ ] Same project deployable to cloud or local
- [ ] Local Docker deployment working
- [ ] Electron desktop app functional
- [ ] Feature parity between deployment targets

✅ **Enhanced Developer Experience**
- [ ] Sub-30-second local project creation
- [ ] Hot reloading in development mode
- [ ] Debugging capabilities for generated code
- [ ] Export/import between cloud and local

✅ **Production Ready**
- [ ] Comprehensive error handling and logging
- [ ] Performance monitoring and alerts
- [ ] Resource usage optimization
- [ ] Security review completed

**Final Validation Scenarios:**
```bash
# Test complete local workflow
./platform-desktop/dist/platform-desktop.app/Contents/MacOS/platform-desktop
# Generate project → Deploy locally → Test in browser → Export to cloud

# Test complete cloud workflow  
curl -X POST https://platform.example.com/api/v2/projects/generate
# Generate project → Deploy to K8s → Access via custom domain → Scale to multiple replicas

# Test hybrid scenarios
./scripts/test-project-portability.sh
# Create locally → Export → Import to cloud → Deploy → Sync back to local
```

## Risk Assessment and Mitigation Strategies

### High Risk - AI Model Dependencies

**Risk:** Ollama or specific models become unavailable
**Impact:** Complete generation pipeline failure
**Probability:** Medium

**Mitigation:**
1. **Multi-provider redundancy**: OpenRouter fallback configured
2. **Model versioning**: Pin specific model versions, test before updates
3. **Local model caching**: Download and cache models on multiple nodes
4. **Graceful degradation**: Template fallback as last resort

```typescript
// Risk mitigation in code
async generateWithFallback(prompt: string): Promise<GeneratedProject> {
  const providers = ['ollama-local', 'openrouter', 'template-fallback'];
  
  for (const provider of providers) {
    try {
      return await this.generateWithProvider(provider, prompt);
    } catch (error) {
      console.warn(`Provider ${provider} failed:`, error);
      if (provider === 'template-fallback') throw error;
    }
  }
}
```

### Medium Risk - Database Schema Changes

**Risk:** Migration fails or causes data loss
**Impact:** Service downtime, data corruption
**Probability:** Low

**Mitigation:**
1. **Backup before migration**: Automated PostgreSQL backups
2. **Staged rollout**: Test in staging environment first
3. **Rollback plan**: Keep previous schema version deployable
4. **Zero-downtime migration**: Use database migration tools

```bash
# Migration safety script
#!/bin/bash
echo "Creating database backup..."
kubectl exec -n database deployment/postgresql -- pg_dump -U platform platform > backup-$(date +%Y%m%d-%H%M%S).sql

echo "Testing migration in read-only mode..."
kubectl exec -n database deployment/postgresql -- psql -U platform platform --dry-run < migration.sql

echo "Applying migration with rollback plan..."
kubectl exec -n database deployment/postgresql -- psql -U platform platform < migration.sql
```

### Medium Risk - Kubernetes Resource Constraints

**Risk:** BuildKit jobs consume excessive resources
**Impact:** Cluster instability, failed deployments
**Probability:** Medium

**Mitigation:**
1. **Resource quotas**: Limit BuildKit job resources
2. **Priority classes**: Ensure core services get priority
3. **Node affinity**: Isolate build workloads
4. **Monitoring**: Alert on high resource usage

```yaml
# Resource management
apiVersion: v1
kind: ResourceQuota
metadata:
  name: buildkit-quota
  namespace: builds
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 8Gi
    limits.cpu: "8" 
    limits.memory: 16Gi
    count/jobs.batch: "5"
```

### Low Risk - Network Connectivity

**Risk:** DNS resolution or service mesh issues
**Impact:** Service communication failures
**Probability:** Low

**Mitigation:**
1. **Health checks**: Comprehensive readiness/liveness probes
2. **Circuit breakers**: Fail fast with retries
3. **Monitoring**: Network latency and error rate alerts
4. **Service mesh**: Consider Istio for advanced networking

```typescript
// Network resilience
class ResilientHttpClient {
  async callWithRetry(url: string, options: RequestOptions): Promise<Response> {
    const maxRetries = 3;
    const backoffMs = 1000;
    
    for (let attempt = 1; attempt <= maxRetries; attempt++) {
      try {
        return await fetch(url, { ...options, timeout: 10000 });
      } catch (error) {
        if (attempt === maxRetries) throw error;
        await new Promise(resolve => setTimeout(resolve, backoffMs * attempt));
      }
    }
  }
}
```

## Conclusion

This architecture plan provides a clear path to fix immediate issues while evolving toward a Dyad-inspired hybrid platform. The phased approach ensures minimal disruption to current functionality while delivering significant improvements in AI generation quality, user experience, and deployment flexibility.

**Key Success Factors:**
1. **Fix the fundamentals first** - Real AI generation must work before adding advanced features
2. **Maintain backwards compatibility** - Existing projects and workflows must continue working
3. **Incremental enhancement** - Each phase delivers value independently
4. **Hybrid approach** - Combines best of cloud infrastructure with local development experience

**Timeline Summary:**
- **Week 1**: AI generation working with real models ✅
- **Week 2-3**: Streaming responses and enhanced context ✅  
- **Week 4-6**: Hybrid architecture and local deployment ✅
- **Ongoing**: Performance optimization and feature expansion

This plan positions the platform as a competitive alternative to v0.dev while leveraging unique strengths like local AI inference and flexible deployment targets.