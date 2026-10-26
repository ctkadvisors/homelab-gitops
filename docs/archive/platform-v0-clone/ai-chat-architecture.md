# AI Chat Architecture - Real-time Iterative Development

## Overview

A real-time chat interface that allows users to iteratively develop Next.js applications through conversation with AI. The AI can analyze requirements, select appropriate templates, and make code changes that are immediately built and deployed for live preview.

## User Experience Flow

1. **New Project Creation**

   - User clicks "New Project"
   - System creates new project entry in database
   - User starts chatting about their application idea

2. **Template Selection & Initial Setup**

   - AI analyzes user requirements from initial conversation
   - AI selects appropriate Next.js template from [Vercel examples](https://github.com/vercel/next.js/tree/canary/examples)
   - AI runs `npx create-next-app --example <template-name>` in container
   - Initial app is built and deployed → User gets live preview URL

3. **Iterative Development**

   - User sends messages describing changes/features
   - AI responds in chat AND makes code changes (when confident)
   - Code changes trigger async build/deploy
   - User can continue chatting while build happens in background
   - Preview auto-refreshes when build completes

4. **Message Queueing**
   - Messages are queued to prevent overwhelming the system
   - User can see queue status and cancel/clarify pending messages
   - Only one message processed at a time per project

## Technical Architecture

### Components

1. **Light Shell Container**

   - Docker container with node/npx/git/build tools
   - One container per active project
   - Full development environment for AI to work in
   - Destroyed when project is completed

2. **Message Queue System**

   - Queues user messages per project
   - Processes one message at a time
   - Allows cancellation/clarification of pending messages
   - Prevents system overload

3. **AI Chat Service**

   - Processes queued messages
   - Decides: chat-only response OR code changes
   - Has access to shell commands in container
   - Only commits changes when confident in user request

4. **Build/Deploy Pipeline**
   - Triggered by git commits from AI
   - Async build process (doesn't block chat)
   - Updates live preview when complete
   - WebSocket notifications for build status

### API Endpoints

- `POST /api/projects` - Create new project
- `POST /api/chat/{projectId}/message` - Send chat message
- `GET /api/chat/{projectId}/queue` - Get message queue status
- `DELETE /api/chat/{projectId}/queue/{messageId}` - Cancel queued message
- `GET /api/projects/{projectId}/build-status` - Get current build status
- `WebSocket /ws/projects/{projectId}` - Real-time updates

### Data Flow

```
User Message → Message Queue → AI Processing → Shell Commands → Git Commit → Build Trigger
     ↓              ↓              ↓              ↓              ↓              ↓
Chat Response   Queue Status   Code Analysis   File Changes   Version Control   Live Preview
```

## Implementation Phases

### Phase 1: Core Infrastructure ✅ COMPLETED

- ✅ Message queue system (`messageQueueService.ts`)
- ✅ Docker container management (`containerService.ts`)
- ✅ AI chat service integration (`aiChatService.ts`)
- ✅ Docker container template (`ai-dev-container`)
- ✅ Helper scripts for project initialization and git operations
- ✅ Supabase integration support
- ✅ API routes for AI chat (`/api/ai-chat/*`)
- ✅ Database integration with existing project schema

**Key Components Built:**

- **Message Queue Service**: Handles queuing, processing, and cancellation of user messages per project
- **Container Service**: Manages Docker container lifecycle with automatic cleanup and health monitoring
- **AI Chat Service**: Processes messages, makes decisions between chat/code generation, and coordinates actions
- **AI Dev Container**: Pre-built environment with Node.js, git, and Next.js tools ready for AI development
- **Supabase Integration**: Optional Supabase deployment for AI-generated projects with automatic configuration
- **Database Integration**: Full compatibility with existing project database schema and Supabase per-project service

### Phase 2: Template Selection & Setup

- Next.js template analysis and selection
- Container initialization with chosen template
- Initial build/deploy pipeline integration

### Phase 3: Iterative Development

- AI shell command execution
- Git integration for change tracking
- Real-time build status updates
- Preview auto-refresh

### Phase 4: User Experience Polish

- Message queue UI/UX
- Build progress indicators
- Error handling and recovery
- Performance optimization

## Security Considerations

- Container isolation for each project
- Limited shell command permissions
- Git repository access controls
- Resource limits per container
- Automatic cleanup of abandoned projects

## Performance Considerations

- Container resource limits
- Message queue throughput
- Build pipeline optimization
- WebSocket connection management
- Automatic scaling based on active projects
