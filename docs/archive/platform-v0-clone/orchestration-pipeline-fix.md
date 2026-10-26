# Orchestration Pipeline Fix - Implementation Plan

**Date**: 2025-08-17  
**Priority**: CRITICAL  
**Estimated Time**: 1-1.5 hours

## Executive Summary

The v0.dev clone's orchestration pipeline is failing silently. Projects are created in the database and Git repositories are initialized, but the AI generation pipeline never triggers. Instead, the system falls back to static templates. The root cause is that `orchestration_jobs` records are never created in the database, preventing the entire AI agent system from activating.

## Current State Analysis

### Working Components ✅
- Platform API running (v3.7.0)
- Platform Dashboard accessible
- Database schema with all tables created
- OpenRouter API key configured
- Git repository creation (Gitea)
- BuildKit RBAC permissions fixed
- Model providers and configurations seeded

### Broken Components ❌
- Orchestration job creation fails silently
- AI agents never triggered
- No agent_executions records created
- Falls back to template-based generation
- No error logging for failures

### Evidence of Failure
```sql
-- Query results show NO orchestration jobs in last 3 days
SELECT * FROM orchestration_jobs WHERE created_at > NOW() - INTERVAL '3 days';
-- Result: 0 rows

-- Query results show NO agent executions
SELECT * FROM agent_executions WHERE created_at > NOW() - INTERVAL '3 days';  
-- Result: 0 rows
```

## Root Cause Analysis

### Primary Failure Point
The `orchestrationService.createOrchestrationJob()` method is failing silently when trying to insert records into the `orchestration_jobs` table.

### Call Flow
```
User Input (Chat UI)
    ↓
aiChatService.createProjectForChat()
    ↓
orchestrationService.generateAndDeploy() 
    ↓
createOrchestrationJob() ← FAILS SILENTLY HERE
    ✗
AI Agents Never Triggered
```

### Hypotheses (Ranked by Probability)

1. **Schema Mismatch** (70% likely)
   - INSERT query fields don't match table columns
   - Missing required fields or wrong data types
   
2. **Database Connection Issue** (20% likely)
   - Connection pool not initialized
   - Wrong credentials or host
   
3. **Transaction Rollback** (5% likely)
   - Error causes rollback without logging
   
4. **Missing Error Handling** (5% likely)
   - Try-catch swallowing errors

## Implementation Plan

### Phase 1: Diagnostics (15 minutes)

#### 1.1 Verify Database Connectivity
```bash
# Test from platform-api pod
kubectl exec -n platform deployment/platform-api -- \
  psql postgresql://platform:REDACTED@postgresql.database.svc.cluster.local/platform \
  -c "SELECT NOW()"
```

#### 1.2 Check Table Schema
```bash
# Get actual table structure
kubectl exec -n database deployment/postgresql -- \
  psql -U platform platform -c "\d orchestration_jobs"
```

#### 1.3 Trace Execution Path
```typescript
// Add to orchestrationService.ts
console.log('[TRACE] generateAndDeploy called with:', request);
console.log('[TRACE] State before job creation:', state);
console.log('[TRACE] Calling createOrchestrationJob...');
```

### Phase 2: Fix Implementation (45 minutes)

#### 2.1 Add Comprehensive Error Logging

```typescript
// orchestrationService.ts - Enhanced error handling
private async createOrchestrationJob(state: OrchestrationState): Promise<void> {
  const jobId = state.projectId || uuidv4();
  
  console.log('[DEBUG] Creating orchestration job:', {
    jobId,
    projectName: state.projectName,
    framework: state.request.framework,
    hasRequiredFields: {
      projectId: !!state.projectId,
      prompt: !!state.request.prompt,
      framework: !!state.request.framework
    }
  });

  try {
    // Log the exact query being executed
    const queryParams = [
      jobId,
      state.projectId,
      state.request.prompt,
      // ... all other parameters
    ];
    
    console.log('[DEBUG] Executing INSERT with params:', queryParams);
    
    const result = await this.pool.query(query, queryParams);
    
    console.log('[SUCCESS] Orchestration job created:', {
      jobId,
      rowCount: result.rowCount
    });
    
  } catch (error: any) {
    console.error('[CRITICAL] Failed to create orchestration job');
    console.error('[CRITICAL] Error message:', error.message);
    console.error('[CRITICAL] Error code:', error.code);
    console.error('[CRITICAL] Error detail:', error.detail);
    console.error('[CRITICAL] Stack trace:', error.stack);
    console.error('[CRITICAL] State dump:', JSON.stringify(state, null, 2));
    
    // Re-throw to prevent silent failure
    throw new Error(`Orchestration job creation failed: ${error.message}`);
  }
}
```

#### 2.2 Fix Database Query

```typescript
// Ensure all fields match schema exactly
private async createOrchestrationJob(state: OrchestrationState): Promise<void> {
  // First, verify connection
  try {
    await this.pool.query('SELECT 1');
  } catch (error) {
    console.error('[CRITICAL] Database connection failed:', error);
    throw new Error('Database connection unavailable');
  }

  // Build INSERT dynamically to handle optional fields
  const fields = {
    id: state.projectId || uuidv4(),
    project_id: state.projectId,
    original_prompt: state.request.prompt,
    framework: state.request.framework,
    features: state.request.features || [],
    status: state.status,
    progress: state.progress,
    current_stage: state.currentStage,
    current_message: state.message,
    started_at: state.startedAt,
    retry_count: state.retryCount,
    max_retries: state.maxRetries,
    // Handle optional fields with NULL
    tier: state.request.tier || null,
    custom_domain: state.request.customDomain || null,
    env_vars: state.request.envVars || {},
  };

  // Use parameterized query with explicit field list
  const query = `
    INSERT INTO orchestration_jobs (${Object.keys(fields).join(', ')})
    VALUES (${Object.keys(fields).map((_, i) => `$${i + 1}`).join(', ')})
    ON CONFLICT (id) DO UPDATE SET
      status = EXCLUDED.status,
      progress = EXCLUDED.progress
  `;

  await this.pool.query(query, Object.values(fields));
}
```

#### 2.3 Add Health Check Endpoint

```typescript
// Add to platform-api routes
app.get('/api/health/orchestration', async (req, res) => {
  const checks = {
    database: false,
    openrouter: false,
    tables: false,
  };

  // Check database connection
  try {
    await pool.query('SELECT NOW()');
    checks.database = true;
  } catch (error) {
    console.error('Database check failed:', error);
  }

  // Check required tables
  try {
    await pool.query('SELECT COUNT(*) FROM orchestration_jobs');
    await pool.query('SELECT COUNT(*) FROM agent_executions');
    checks.tables = true;
  } catch (error) {
    console.error('Table check failed:', error);
  }

  // Check OpenRouter API
  try {
    const response = await fetch('https://openrouter.ai/api/v1/models', {
      headers: { 'Authorization': `Bearer ${process.env.OPENROUTER_API_KEY}` }
    });
    checks.openrouter = response.ok;
  } catch (error) {
    console.error('OpenRouter check failed:', error);
  }

  const healthy = Object.values(checks).every(v => v);
  res.status(healthy ? 200 : 503).json({ healthy, checks });
});
```

### Phase 3: Testing Strategy (30 minutes)

#### 3.1 Unit Test - Direct Orchestration Call

```typescript
// test-orchestration.ts
import { orchestrationService } from './orchestrationService.js';

async function testOrchestration() {
  console.log('Starting orchestration test...');
  
  try {
    const result = await orchestrationService.generateAndDeploy({
      prompt: 'Test project for debugging',
      framework: 'nextjs',
      features: [],
      repositoryName: 'test-debug-' + Date.now()
    });
    
    console.log('SUCCESS:', result);
  } catch (error) {
    console.error('FAILED:', error);
  }
}

testOrchestration();
```

#### 3.2 Integration Test - Via API

```bash
# Test via curl
curl -X POST https://platform.example.com/api/projects/generate \
  -H "Content-Type: application/json" \
  -d '{
    "prompt": "Simple Next.js app",
    "framework": "nextjs",
    "userId": "6c66fb81-5922-4486-a6fb-28d39b550c2c"
  }'
```

#### 3.3 End-to-End Test - Via UI

1. Open https://platform.example.com
2. Enter prompt: "Create a simple todo app"
3. Monitor logs in real-time:
```bash
kubectl logs -n platform deployment/platform-api -f | grep -E "TRACE|DEBUG|CRITICAL|SUCCESS"
```

### Phase 4: Validation (15 minutes)

#### 4.1 Verify Job Creation
```sql
-- Check orchestration jobs
SELECT id, status, current_stage, created_at 
FROM orchestration_jobs 
ORDER BY created_at DESC 
LIMIT 5;
```

#### 4.2 Verify Agent Execution
```sql
-- Check agent activity
SELECT 
  ad.agent_type,
  ae.status,
  ae.created_at
FROM agent_executions ae
JOIN agent_definitions ad ON ae.agent_definition_id = ad.id
ORDER BY ae.created_at DESC
LIMIT 10;
```

#### 4.3 Verify AI Generation
```bash
# Check generated code in Gitea
curl https://git.example.com/api/v1/repos/ai-generated/{project-name}/contents
```

## Success Metrics

### Immediate Success (Must Have)
- [ ] Orchestration jobs created in database
- [ ] No silent failures - all errors logged
- [ ] AI agents triggered for new projects

### Full Success (Should Have)
- [ ] Real AI-generated code (not templates)
- [ ] Complete pipeline execution (generate → build → deploy)
- [ ] Deployment URL accessible

### Bonus Success (Nice to Have)
- [ ] Streaming responses to UI
- [ ] Progress updates in real-time
- [ ] Error recovery and retry logic

## Rollback Plan

If issues arise:

1. **Immediate Rollback**
```bash
# Revert to previous image
kubectl set image -n platform deployment/platform-api \
  api=git.example.com/homelab/platform-api:v3.6.0
```

2. **Data Cleanup**
```sql
-- Remove failed job records
DELETE FROM orchestration_jobs 
WHERE status = 'failed' 
AND created_at > NOW() - INTERVAL '1 hour';
```

3. **Restore Template Fallback**
- Temporarily re-enable template generation
- Document issues for next iteration

## Next Steps After Fix

1. **Add Monitoring**
   - Prometheus metrics for pipeline stages
   - Grafana dashboard for success rates
   - Alert on silent failures

2. **Implement Dyad Patterns**
   - Structured AI markup system
   - Smart context management
   - Streaming responses

3. **Performance Optimization**
   - Connection pooling
   - Caching for model responses
   - Parallel agent execution

## Commands Reference

```bash
# Monitor logs
kubectl logs -n platform deployment/platform-api -f

# Test database connection
kubectl exec -n platform deployment/platform-api -- \
  psql $DATABASE_URL -c "SELECT NOW()"

# Check orchestration jobs
kubectl exec -n database deployment/postgresql -- \
  psql -U platform platform -c "SELECT * FROM orchestration_jobs ORDER BY created_at DESC LIMIT 5"

# Restart platform-api
kubectl rollout restart -n platform deployment/platform-api

# Check pod status
kubectl get pods -n platform -l app=platform-api
```

## Contact & Escalation

- **Primary**: Fix locally via SSH to elitemini
- **Logs**: Available in k9s or kubectl
- **Database**: PostgreSQL in database namespace
- **Git**: Gitea at git.example.com

---

**Status**: Ready for implementation  
**Owner**: Platform Team  
**Last Updated**: 2025-08-17