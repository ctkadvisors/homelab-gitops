# Multi-Agent SDLC Coordination Design

## Overview
This document outlines how multiple AI agents coordinate to generate, validate, and deploy code through a structured SDLC pipeline, with all operations tracked in PostgreSQL and code pushed to Gitea.

## Agent Types & Responsibilities

### 1. Planner Agent
**Purpose**: Analyze requirements and create implementation plan
**Model**: Claude 3 Opus (via OpenRouter)
**Database Tables**: 
- `agent_executions` - tracks planning attempts
- `agent_plans` - stores structured plan output
- `agent_tasks` - individual tasks to implement

**Workflow**:
1. Receives user prompt/requirements
2. Analyzes and breaks down into tasks
3. Creates dependency graph
4. Estimates complexity and resources
5. Outputs structured plan to database

### 2. Implementer Agent  
**Purpose**: Generate actual code based on plan
**Model**: DeepSeek Coder (free via OpenRouter)
**Database Tables**:
- `agent_executions` - tracks each code generation
- `agent_tasks` - updates task status
- `agent_git_operations` - records file operations

**Workflow**:
1. Reads tasks from `agent_tasks` WHERE status='pending'
2. Generates code for each task
3. Writes files to git working directory
4. Updates task status to 'completed'
5. Records git operations

### 3. Validator Agent
**Purpose**: Check code quality, syntax, security
**Model**: CodeLlama 70B (free via OpenRouter)  
**Database Tables**:
- `agent_executions` - validation attempts
- `agent_iterations` - issues found requiring fixes
- `agent_coordination` - messages to implementer

**Workflow**:
1. Reads generated code from git
2. Performs validation checks
3. If issues found:
   - Creates `agent_iterations` record
   - Sends message via `agent_coordination`
   - Triggers implementer to fix
4. Approves code when clean

### 4. Tester Agent
**Purpose**: Generate and run tests
**Model**: Phind CodeLlama 34B (free via OpenRouter)
**Database Tables**:
- `agent_executions` - test generation/execution
- `agent_tasks` - test tasks
- `agent_iterations` - test failures needing fixes

**Workflow**:
1. Analyzes code to identify test points
2. Generates test files
3. Executes tests (if environment available)
4. Reports coverage and results
5. Requests fixes for failures

### 5. Reviewer Agent (Optional)
**Purpose**: Final review before deployment
**Model**: Claude 3 Sonnet (via OpenRouter)
**Database Tables**:
- `agent_executions` - review sessions
- `agent_coordination` - approval/rejection messages

## Coordination Mechanisms

### 1. Database-Driven State Machine
```sql
-- Agent checks for work
SELECT * FROM agent_coordination 
WHERE to_agent = 'implementer' 
  AND is_processed = false
ORDER BY created_at;

-- Agent claims work
UPDATE agent_coordination 
SET is_processed = true, 
    processed_at = NOW(),
    processed_by_execution_id = ?
WHERE id = ?;
```

### 2. Task Assignment
```sql
-- Get next task for agent
SELECT * FROM agent_tasks
WHERE assigned_agent = 'implementer'
  AND status = 'pending'
  AND dependencies NOT IN (
    SELECT task_id FROM agent_tasks 
    WHERE status != 'completed'
  )
LIMIT 1 FOR UPDATE SKIP LOCKED;
```

### 3. Iteration Loops
When validator finds issues:
1. Create `agent_iterations` record with feedback
2. Update task status to 'needs_revision'
3. Send coordination message to implementer
4. Implementer reads feedback and regenerates
5. Cycle continues until validation passes

## Gitea Integration Strategy

### 1. Working Directory Structure
```
/tmp/agent-workspace/{orchestration_job_id}/
├── .git/                 # Git repository
├── src/                  # Generated source code
├── tests/                # Generated tests
├── docs/                 # Generated documentation
└── agent-metadata.json   # Agent coordination data
```

### 2. Git Operations Flow

#### Initial Setup (Planner Agent)
```typescript
// After plan creation
async function initializeGitRepository(plan: AgentPlan) {
  // 1. Create working directory
  const workDir = `/tmp/agent-workspace/${plan.orchestration_job_id}`;
  
  // 2. Initialize git
  await exec(`git init ${workDir}`);
  
  // 3. Create initial structure from plan
  for (const dir of plan.project_structure.directories) {
    await exec(`mkdir -p ${workDir}/${dir}`);
  }
  
  // 4. Initial commit
  await exec(`cd ${workDir} && git add . && git commit -m "Initial structure from planner agent"`);
  
  // 5. Create Gitea repository
  const repo = await giteaService.createRepository({
    name: plan.project_name,
    organization: 'ai-generated'
  });
  
  // 6. Add remote
  await exec(`cd ${workDir} && git remote add origin ${repo.clone_url}`);
  
  // 7. Record in database
  await db.query(
    `INSERT INTO agent_git_operations 
     (orchestration_job_id, operation_type, repository_url, branch, commit_message)
     VALUES ($1, 'init', $2, 'main', 'Initial structure')`,
    [plan.orchestration_job_id, repo.clone_url]
  );
}
```

#### Code Generation (Implementer Agent)
```typescript
async function commitGeneratedCode(task: AgentTask, code: string) {
  const workDir = `/tmp/agent-workspace/${task.orchestration_job_id}`;
  
  // 1. Write file
  await fs.writeFile(`${workDir}/${task.file_path}`, code);
  
  // 2. Stage file
  await exec(`cd ${workDir} && git add ${task.file_path}`);
  
  // 3. Commit with task reference
  const message = `feat: ${task.title} [task:${task.task_id}]`;
  await exec(`cd ${workDir} && git commit -m "${message}"`);
  
  // 4. Record operation
  await db.query(
    `INSERT INTO agent_git_operations 
     (orchestration_job_id, execution_id, operation_type, files_added, commit_message)
     VALUES ($1, $2, 'commit', $3, $4)`,
    [task.orchestration_job_id, executionId, [task.file_path], message]
  );
}
```

#### Validation Fixes (Iteration Loop)
```typescript
async function commitValidationFix(iteration: AgentIteration, fixedCode: string) {
  const workDir = `/tmp/agent-workspace/${iteration.orchestration_job_id}`;
  
  // 1. Apply fix
  await fs.writeFile(`${workDir}/${iteration.file_path}`, fixedCode);
  
  // 2. Commit with iteration reference
  const message = `fix: ${iteration.feedback_type} [iteration:${iteration.id}]`;
  await exec(`cd ${workDir} && git add -A && git commit -m "${message}"`);
  
  // 3. Update iteration status
  await db.query(
    `UPDATE agent_iterations 
     SET resolution_status = 'resolved', resolved_at = NOW()
     WHERE id = $1`,
    [iteration.id]
  );
}
```

#### Final Push (After All Validation)
```typescript
async function pushToGitea(orchestrationJobId: string) {
  const workDir = `/tmp/agent-workspace/${orchestrationJobId}`;
  
  // 1. Push all commits
  await exec(`cd ${workDir} && git push origin main`);
  
  // 2. Get final commit SHA
  const sha = await exec(`cd ${workDir} && git rev-parse HEAD`);
  
  // 3. Update orchestration job
  await db.query(
    `UPDATE orchestration_jobs 
     SET git_commit_sha = $1, repository_url = $2
     WHERE id = $3`,
    [sha.trim(), repoUrl, orchestrationJobId]
  );
  
  // 4. Record final push
  await db.query(
    `INSERT INTO agent_git_operations 
     (orchestration_job_id, operation_type, commit_sha, status)
     VALUES ($1, 'push', $2, 'completed')`,
    [orchestrationJobId, sha.trim()]
  );
}
```

## Parallel Processing Strategy

### Task Parallelization
```typescript
// Identify parallel task groups from plan
const parallelGroups = await db.query(
  `SELECT jsonb_array_elements(parallel_groups) as group
   FROM agent_plans 
   WHERE orchestration_job_id = $1 AND is_active = true`,
  [orchestrationJobId]
);

// Process each group in parallel
for (const group of parallelGroups) {
  const tasks = group.tasks;
  await Promise.all(
    tasks.map(taskId => 
      implementerAgent.generateCode(taskId)
    )
  );
}
```

### Agent Concurrency
- **Planner**: Single instance per orchestration
- **Implementer**: Multiple instances for parallel tasks
- **Validator**: Can validate multiple files concurrently
- **Tester**: Can generate tests in parallel

## Error Handling & Recovery

### 1. Agent Failure
```sql
-- Mark execution as failed
UPDATE agent_executions 
SET status = 'failed', 
    error_message = ?,
    completed_at = NOW()
WHERE id = ?;

-- Trigger retry if under limit
INSERT INTO agent_coordination 
(orchestration_job_id, from_agent, to_agent, message_type, message_content)
VALUES (?, 'orchestrator', 'implementer', 'request', 'retry_task');
```

### 2. Validation Loop Limit
```typescript
// Prevent infinite validation loops
const MAX_ITERATIONS = 5;
const iterations = await db.query(
  `SELECT COUNT(*) FROM agent_iterations 
   WHERE orchestration_job_id = $1 
     AND source_agent = 'validator'
     AND target_agent = 'implementer'`,
  [orchestrationJobId]
);

if (iterations.count >= MAX_ITERATIONS) {
  // Escalate to human or fail gracefully
  await markOrchestrationFailed(orchestrationJobId, 'Max validation iterations reached');
}
```

## Monitoring & Observability

### Key Metrics
1. **Agent Performance**
   - Execution time per agent type
   - Token usage and costs
   - Success/failure rates

2. **Task Progress**
   - Tasks completed vs pending
   - Average task completion time
   - Iteration counts per task

3. **Git Operations**
   - Commits per orchestration
   - Files changed
   - Push success rate

### Dashboard Queries
```sql
-- Real-time agent status
SELECT 
  agent_type,
  COUNT(*) FILTER (WHERE status = 'running') as running,
  COUNT(*) FILTER (WHERE status = 'completed') as completed,
  COUNT(*) FILTER (WHERE status = 'failed') as failed,
  AVG(duration_ms) as avg_duration_ms
FROM agent_executions
WHERE orchestration_job_id = ?
GROUP BY agent_type;

-- Task completion progress
SELECT 
  COUNT(*) FILTER (WHERE status = 'completed') * 100.0 / COUNT(*) as completion_percentage,
  COUNT(*) FILTER (WHERE status = 'failed') as failed_tasks,
  COUNT(*) FILTER (WHERE validation_status = 'passed') as validated_tasks
FROM agent_tasks
WHERE plan_id IN (
  SELECT id FROM agent_plans 
  WHERE orchestration_job_id = ? AND is_active = true
);
```

## Security Considerations

1. **Input Sanitization**: All agent inputs sanitized before database storage
2. **Code Scanning**: Validator agent checks for security issues
3. **Git Credentials**: Stored securely, never in agent prompts
4. **Resource Limits**: Token limits per agent, timeout controls
5. **Sandbox Execution**: Code execution in isolated containers

## Next Steps

1. Implement OpenRouter service with model rotation
2. Create agent base classes with database integration
3. Build coordination service for message passing
4. Implement git workspace manager
5. Create monitoring dashboard for agent operations