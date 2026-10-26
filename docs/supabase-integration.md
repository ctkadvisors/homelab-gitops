# Supabase Integration with AI Chat Platform

## Overview

The AI Chat platform maintains full compatibility with the existing Supabase integration system. When users create projects through AI chat, they can optionally enable Supabase support, which will automatically provision a dedicated Supabase instance for their project.

## Integration Points

### 1. Database Schema Compatibility

The AI chat system integrates with the existing database schema:

- **Projects Table**: AI-generated projects are stored in the standard `projects` table
- **AI Workflow Tables**: Uses `ai_workflow_executions` and `ai_generated_projects` for tracking
- **User Management**: Leverages existing `users` table and authentication

### 2. Project Creation Flow

When a user starts an AI chat session:

```typescript
// 1. Start chat session
const session = await aiChatService.startChatSession(projectId, userId, {
  supabaseEnabled: true,  // Optional Supabase support
  projectName: 'my-app',
  description: 'My AI-generated app'
});

// 2. AI selects template and creates project
const project = await aiChatService.createProjectForChat(
  projectName,
  userId,
  description,
  {
    supabaseEnabled: true,
    framework: 'nextjs'
  }
);

// 3. Supabase instance is automatically deployed
await supabasePerProjectService.deploySupabaseForProject(project);
```

### 3. Supabase Deployment

When `supabaseEnabled: true` is specified:

1. **Project Creation**: Standard project record created in database
2. **Environment Variables**: Supabase URLs and keys automatically configured
3. **Namespace Creation**: Dedicated Kubernetes namespace (`project-{name}`)
4. **Database Schema**: Project-specific schema created in shared PostgreSQL
5. **Supabase Services**: API, Auth, and Ingress deployed
6. **TLS Certificates**: Automatic certificate provisioning

### 4. Environment Variables

AI-generated projects with Supabase get these environment variables:

```json
{
  "NEXT_PUBLIC_SUPABASE_URL": "https://{project-name}-api.example.com",
  "NEXT_PUBLIC_SUPABASE_ANON_KEY": "{generated-anon-key}"
}
```

### 5. Database Schema Structure

Each Supabase-enabled project gets:

```sql
-- Project-specific schema
CREATE SCHEMA project_{project_name};

-- Supabase-compatible auth tables
CREATE TABLE auth_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email VARCHAR(255) UNIQUE,
  encrypted_password VARCHAR(255),
  email_confirmed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  raw_app_meta_data JSONB,
  raw_user_meta_data JSONB
);

-- User profiles table
CREATE TABLE profiles (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES auth_users(id) ON DELETE CASCADE,
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  username TEXT UNIQUE,
  full_name TEXT,
  avatar_url TEXT
);
```

## API Endpoints

### Start AI Chat Session with Supabase

```http
POST /api/ai-chat/sessions
Content-Type: application/json

{
  "projectName": "my-todo-app",
  "description": "A todo app with user authentication",
  "supabaseEnabled": true,
  "framework": "nextjs"
}
```

Response:
```json
{
  "success": true,
  "data": {
    "sessionId": "chat-1234567890-abc123",
    "projectId": "chat-1234567890-abc123",
    "messages": [...],
    "containerReady": false,
    "supabaseEnabled": true
  }
}
```

### Get Session Status

```http
GET /api/ai-chat/sessions/{sessionId}
```

Response includes project details with Supabase configuration:
```json
{
  "success": true,
  "data": {
    "sessionId": "chat-1234567890-abc123",
    "messages": [...],
    "project": {
      "id": "uuid",
      "name": "my-todo-app",
      "repositoryUrl": "https://git.example.com/ai-generated/my-todo-app.git",
      "envVars": {
        "NEXT_PUBLIC_SUPABASE_URL": "https://my-todo-app-api.example.com",
        "NEXT_PUBLIC_SUPABASE_ANON_KEY": "eyJ..."
      }
    },
    "supabaseEnabled": true
  }
}
```

## Template Integration

AI chat templates can include Supabase-specific code:

### Next.js with Supabase Template

When AI selects a template that requires authentication:

1. **Template Selection**: AI chooses appropriate template (e.g., `auth-starter`)
2. **Supabase Setup**: Automatic Supabase instance deployment
3. **Code Generation**: Template includes Supabase client configuration
4. **Environment Setup**: Supabase URLs and keys injected

### Example Generated Code

```typescript
// lib/supabase.ts
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL!
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!

export const supabase = createClient(supabaseUrl, supabaseAnonKey)
```

## Benefits

1. **Seamless Integration**: No additional setup required for Supabase
2. **Automatic Provisioning**: Database, auth, and API automatically configured
3. **Environment Management**: All environment variables handled automatically
4. **Namespace Isolation**: Each project gets dedicated Kubernetes namespace
5. **TLS Security**: Automatic certificate management
6. **Existing Compatibility**: Works with all existing platform features

## Deployment Architecture

```
AI Chat Session
    ↓
Project Creation (with supabaseEnabled: true)
    ↓
Database Record (projects table)
    ↓
Supabase Deployment
    ├── Kubernetes Namespace (project-{name})
    ├── PostgreSQL Schema (project_{name})
    ├── Supabase API Service
    ├── Supabase Auth Service
    ├── Ingress with TLS
    └── Environment Variables
    ↓
Container Initialization
    ├── Next.js Template
    ├── Supabase Client Setup
    └── Git Repository
    ↓
Build & Deploy Pipeline
    ↓
Live Application with Supabase Backend
```

This integration ensures that AI-generated projects can leverage the full power of Supabase while maintaining compatibility with the existing platform infrastructure.
