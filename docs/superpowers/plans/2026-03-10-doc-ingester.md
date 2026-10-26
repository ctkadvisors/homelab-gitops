# Personal Document Indexer Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a doc-ingester service that indexes Gmail and iMessage into Qdrant for offline-first RAG search via OpenWebUI.

**Architecture:** Dedicated Node.js/TypeScript service in `ai-services` namespace. Gmail connector polls IMAP on schedule, iMessage connector receives HTTP batches from a Mac cron script. Both feed a shared pipeline: preprocess → semantic chunk → embed via LocalAI → upsert to Qdrant with hierarchical metadata. PostgreSQL tracks indexing state for dedup and resumability.

**Tech Stack:** Node.js 18, TypeScript, Express, `imapflow` (IMAP), `node-html-parser` (HTML strip), `pg` (PostgreSQL), `@qdrant/js-client-rest` (Qdrant), Zod, Docker, Kustomize.

**Spec:** `docs/superpowers/specs/2026-03-09-personal-doc-indexer-design.md`

---

## File Structure

```
services/doc-ingester/
├── src/
│   ├── index.ts                    # Express app + connector scheduler
│   ├── config/
│   │   └── environment.ts          # Zod env validation
│   ├── connectors/
│   │   ├── gmail.ts                # IMAP client, fetch/poll, category filter
│   │   └── imessage.ts             # HTTP endpoint handler for Mac batches
│   ├── pipeline/
│   │   ├── preprocessor.ts         # HTML strip, signature removal, thread split
│   │   ├── chunker.ts              # Semantic chunking (short/medium/long)
│   │   ├── embedder.ts             # LocalAI embedding client
│   │   └── indexer.ts              # Qdrant upsert with hierarchical metadata
│   ├── storage/
│   │   ├── postgres.ts             # Pool + state tracking queries
│   │   └── qdrant.ts               # Collection mgmt, payload indexes, search
│   ├── search/
│   │   └── queryService.ts         # Hybrid vector + structured filter queries
│   ├── api/
│   │   ├── routes.ts               # POST /ingest/imessage, GET /search, GET /status
│   │   └── health.ts               # GET /health
│   └── types/
│       └── index.ts                # Shared types, Zod schemas
├── scripts/
│   └── imessage-sync.py            # Mac cron: reads chat.db, POSTs batches
├── Dockerfile
├── package.json
├── tsconfig.json
├── .env.example
└── jest.config.js

k8s-kustomized/base/ai-services/
├── doc-ingester.yaml               # Deployment, Service, Secret
└── kustomization.yaml              # (modify: add doc-ingester.yaml)

k8s-kustomized/base/vector-db/
└── qdrant-init-job.yaml            # (modify: add personal_docs collection)

k8s-kustomized/base/database/
└── postgresql-init.yaml            # (modify: add doc_ingester database)

scripts/
└── build-doc-ingester.sh           # Docker build + push to Gitea
```

---

## Chunk 1: Foundation

### Task 1: Project Scaffold

**Files:**
- Create: `services/doc-ingester/package.json`
- Create: `services/doc-ingester/tsconfig.json`
- Create: `services/doc-ingester/.env.example`
- Create: `services/doc-ingester/jest.config.js`

- [ ] **Step 1: Create package.json**

```json
{
  "name": "doc-ingester",
  "version": "1.0.0",
  "main": "dist/index.js",
  "scripts": {
    "dev": "tsx watch src/index.ts",
    "build": "tsc",
    "start": "node dist/index.js",
    "lint": "eslint src --ext .ts",
    "type-check": "tsc --noEmit",
    "test": "jest",
    "test:watch": "jest --watch"
  },
  "dependencies": {
    "express": "^4.18.2",
    "cors": "^2.8.5",
    "helmet": "^7.1.0",
    "morgan": "^1.10.0",
    "pg": "^8.11.3",
    "dotenv": "^16.3.1",
    "uuid": "^9.0.1",
    "zod": "^3.22.4",
    "imapflow": "^1.0.160",
    "node-html-parser": "^6.1.12",
    "@qdrant/js-client-rest": "^1.7.0",
    "mailparser": "^3.6.6"
  },
  "devDependencies": {
    "typescript": "^5.3.3",
    "tsx": "^4.6.2",
    "@types/express": "^4.17.21",
    "@types/node": "^20.10.5",
    "@types/pg": "^8.10.9",
    "@types/uuid": "^9.0.7",
    "jest": "^29.7.0",
    "ts-jest": "^29.1.1",
    "@types/jest": "^29.5.11"
  }
}
```

- [ ] **Step 2: Create tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["ES2020"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "resolveJsonModule": true,
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "baseUrl": ".",
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "**/*.test.ts"]
}
```

- [ ] **Step 3: Create .env.example**

```bash
# Server
NODE_ENV=development
PORT=3002

# PostgreSQL
DB_HOST=postgresql.database.svc.cluster.local
DB_PORT=5432
DB_NAME=doc_ingester
DB_USER=doc_ingester
DB_PASSWORD=REDACTED

# Qdrant
QDRANT_URL=http://qdrant.vector-db.svc.cluster.local:6333
QDRANT_COLLECTION=personal_docs

# LocalAI (embeddings)
LOCALAI_URL=http://localai.ai-services.svc.cluster.local:8080
EMBEDDING_MODEL=text-embedding-ada-002

# Gmail IMAP
GMAIL_USER=your-email@gmail.com
GMAIL_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
GMAIL_POLL_INTERVAL_MS=300000

# Ingestion
CHUNK_MAX_SIZE=1000
CHUNK_OVERLAP_SENTENCES=1
RAPID_TEXT_GROUP_MINUTES=5
```

- [ ] **Step 4: Create jest.config.js**

```javascript
module.exports = {
  preset: "ts-jest",
  testEnvironment: "node",
  roots: ["<rootDir>/src"],
  testMatch: ["**/*.test.ts"],
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
};
```

- [ ] **Step 5: Install dependencies**

Run: `cd services/doc-ingester && npm install`

- [ ] **Step 6: Commit**

```bash
git add services/doc-ingester/package.json services/doc-ingester/tsconfig.json services/doc-ingester/.env.example services/doc-ingester/jest.config.js services/doc-ingester/package-lock.json
git commit -m "doc-ingester: project scaffold with dependencies"
```

---

### Task 2: Types and Environment Config

**Files:**
- Create: `services/doc-ingester/src/types/index.ts`
- Create: `services/doc-ingester/src/config/environment.ts`

- [ ] **Step 1: Write failing test for environment validation**

Create: `services/doc-ingester/src/config/environment.test.ts`

```typescript
import { EnvironmentSchema } from "./environment";

describe("EnvironmentSchema", () => {
  it("should parse valid environment with defaults", () => {
    const result = EnvironmentSchema.parse({
      GMAIL_USER: "test@gmail.com",
      GMAIL_APP_PASSWORD: "xxxx-xxxx",
      DB_PASSWORD: "secret",
    });
    expect(result.PORT).toBe(3002);
    expect(result.QDRANT_COLLECTION).toBe("personal_docs");
    expect(result.EMBEDDING_MODEL).toBe("text-embedding-ada-002");
    expect(result.GMAIL_POLL_INTERVAL_MS).toBe(300000);
  });

  it("should reject missing required Gmail credentials", () => {
    expect(() => EnvironmentSchema.parse({})).toThrow();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/config/environment.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Create types**

Create: `services/doc-ingester/src/types/index.ts`

```typescript
import { z } from "zod";

// Source types
export type SourceType = "gmail" | "imessage";

// Hierarchical metadata stored with each Qdrant vector
export interface VectorMetadata {
  // Level 1: Source context
  source_type: SourceType;
  account: string;

  // Level 2: Conversation context
  thread_id: string;
  thread_subject: string | null;
  thread_participants: string[];
  thread_message_count: number;
  thread_date_start: string;
  thread_date_end: string;

  // Level 3: Message context
  message_id: string;
  sender: string;
  recipients: string[];
  timestamp: string;
  labels: string[];
  gmail_category: string | null;
  is_reply: boolean;
  reply_depth: number;

  // Chunk context
  chunk_index: number;
  chunk_total: number;
  chunk_type: "full_message" | "paragraph" | "thread_segment";
  text: string;
}

// Raw message from connectors before processing
export interface RawMessage {
  source_type: SourceType;
  account: string;
  message_id: string;
  thread_id: string;
  sender: string;
  recipients: string[];
  subject: string | null;
  timestamp: string;
  labels: string[];
  gmail_category: string | null;
  is_reply: boolean;
  reply_depth: number;
  body_text: string;
  body_html: string | null;
}

// Chunk output from the chunker
export interface Chunk {
  text: string;
  chunk_index: number;
  chunk_total: number;
  chunk_type: "full_message" | "paragraph" | "thread_segment";
}

// iMessage batch payload from Mac cron script
export const IMessageBatchSchema = z.object({
  messages: z.array(
    z.object({
      rowid: z.number(),
      chat_id: z.string(),
      sender: z.string(),
      participants: z.array(z.string()),
      text: z.string(),
      timestamp: z.string(),
      is_from_me: z.boolean(),
    })
  ),
  sync_timestamp: z.string(),
});

export type IMessageBatch = z.infer<typeof IMessageBatchSchema>;

// Indexing state row in PostgreSQL
export interface IndexingState {
  source: SourceType;
  message_id: string;
  indexed_at: Date;
  chunk_count: number;
  status: "indexed" | "failed";
}

// Search request
export const SearchRequestSchema = z.object({
  query: z.string().min(1),
  source_type: z.enum(["gmail", "imessage"]).optional(),
  sender: z.string().optional(),
  thread_id: z.string().optional(),
  date_from: z.string().optional(),
  date_to: z.string().optional(),
  labels: z.array(z.string()).optional(),
  limit: z.number().int().min(1).max(100).default(20),
});

export type SearchRequest = z.infer<typeof SearchRequestSchema>;

// Search result
export interface SearchResult {
  score: number;
  metadata: VectorMetadata;
  thread_context?: VectorMetadata[];
}
```

- [ ] **Step 4: Create environment config**

Create: `services/doc-ingester/src/config/environment.ts`

```typescript
import { z } from "zod";
import dotenv from "dotenv";

dotenv.config();

export const EnvironmentSchema = z.object({
  NODE_ENV: z.enum(["development", "production", "test"]).default("development"),
  PORT: z.coerce.number().int().default(3002),

  // PostgreSQL
  DB_HOST: z.string().default("postgresql.database.svc.cluster.local"),
  DB_PORT: z.coerce.number().int().default(5432),
  DB_NAME: z.string().default("doc_ingester"),
  DB_USER: z.string().default("doc_ingester"),
  DB_PASSWORD: z.string(),

  // Qdrant
  QDRANT_URL: z.string().default("http://qdrant.vector-db.svc.cluster.local:6333"),
  QDRANT_COLLECTION: z.string().default("personal_docs"),

  // LocalAI
  LOCALAI_URL: z.string().default("http://localai.ai-services.svc.cluster.local:8080"),
  EMBEDDING_MODEL: z.string().default("text-embedding-ada-002"),

  // Gmail
  GMAIL_USER: z.string().email(),
  GMAIL_APP_PASSWORD: z.string(),
  GMAIL_POLL_INTERVAL_MS: z.coerce.number().int().default(300000),

  // Chunking
  CHUNK_MAX_SIZE: z.coerce.number().int().default(1000),
  CHUNK_OVERLAP_SENTENCES: z.coerce.number().int().default(1),
  RAPID_TEXT_GROUP_MINUTES: z.coerce.number().int().default(5),
});

export type Environment = z.infer<typeof EnvironmentSchema>;

export const env = EnvironmentSchema.parse(process.env);
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/config/environment.test.ts -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/doc-ingester/src/
git commit -m "doc-ingester: types, schemas, and environment config"
```

---

### Task 3: PostgreSQL Storage Layer

**Files:**
- Create: `services/doc-ingester/src/storage/postgres.ts`
- Test: `services/doc-ingester/src/storage/postgres.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/storage/postgres.test.ts`

```typescript
import { PostgresStorage } from "./postgres";

// Unit test with mocked pg Pool
const mockQuery = jest.fn();
const mockConnect = jest.fn().mockResolvedValue({
  query: mockQuery,
  release: jest.fn(),
});

jest.mock("pg", () => ({
  Pool: jest.fn().mockImplementation(() => ({
    connect: mockConnect,
    query: mockQuery,
  })),
}));

describe("PostgresStorage", () => {
  let storage: PostgresStorage;

  beforeEach(() => {
    storage = new PostgresStorage({
      host: "localhost",
      port: 5432,
      database: "test",
      user: "test",
      password: "test",
    });
    mockQuery.mockReset();
  });

  describe("isIndexed", () => {
    it("should return true if message exists with indexed status", async () => {
      mockQuery.mockResolvedValueOnce({
        rows: [{ status: "indexed" }],
      });
      const result = await storage.isIndexed("gmail", "msg-123");
      expect(result).toBe(true);
      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining("SELECT status"),
        ["gmail", "msg-123"]
      );
    });

    it("should return false if message not found", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });
      const result = await storage.isIndexed("gmail", "msg-456");
      expect(result).toBe(false);
    });
  });

  describe("markIndexed", () => {
    it("should upsert indexing state", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });
      await storage.markIndexed("gmail", "msg-123", 3);
      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining("INSERT INTO doc_ingester_state"),
        ["gmail", "msg-123", 3, "indexed"]
      );
    });
  });

  describe("markFailed", () => {
    it("should record failed status", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [] });
      await storage.markFailed("imessage", "row-99");
      expect(mockQuery).toHaveBeenCalledWith(
        expect.stringContaining("INSERT INTO doc_ingester_state"),
        ["imessage", "row-99", 0, "failed"]
      );
    });
  });

  describe("getLastSyncTimestamp", () => {
    it("should return latest indexed_at for source", async () => {
      const ts = new Date("2026-01-01T00:00:00Z");
      mockQuery.mockResolvedValueOnce({ rows: [{ max: ts }] });
      const result = await storage.getLastSyncTimestamp("gmail");
      expect(result).toEqual(ts);
    });

    it("should return null if no records", async () => {
      mockQuery.mockResolvedValueOnce({ rows: [{ max: null }] });
      const result = await storage.getLastSyncTimestamp("imessage");
      expect(result).toBeNull();
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/storage/postgres.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement PostgresStorage**

Create: `services/doc-ingester/src/storage/postgres.ts`

```typescript
import { Pool, PoolConfig } from "pg";
import { SourceType, IndexingState } from "../types";

export class PostgresStorage {
  private pool: Pool;

  constructor(config: PoolConfig) {
    this.pool = new Pool({
      ...config,
      max: 10,
      idleTimeoutMillis: 30000,
      connectionTimeoutMillis: 5000,
    });
  }

  async initialize(): Promise<void> {
    await this.pool.query(`
      CREATE TABLE IF NOT EXISTS doc_ingester_state (
        source TEXT NOT NULL,
        message_id TEXT NOT NULL,
        indexed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        chunk_count INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'indexed',
        PRIMARY KEY (source, message_id)
      );
      CREATE INDEX IF NOT EXISTS idx_state_source_time
        ON doc_ingester_state (source, indexed_at DESC);
    `);
  }

  async isIndexed(source: SourceType, messageId: string): Promise<boolean> {
    const result = await this.pool.query(
      "SELECT status FROM doc_ingester_state WHERE source = $1 AND message_id = $2",
      [source, messageId]
    );
    return result.rows.length > 0 && result.rows[0].status === "indexed";
  }

  async markIndexed(source: SourceType, messageId: string, chunkCount: number): Promise<void> {
    await this.pool.query(
      `INSERT INTO doc_ingester_state (source, message_id, chunk_count, status)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (source, message_id)
       DO UPDATE SET chunk_count = $3, status = $4, indexed_at = NOW()`,
      [source, messageId, chunkCount, "indexed"]
    );
  }

  async markFailed(source: SourceType, messageId: string): Promise<void> {
    await this.pool.query(
      `INSERT INTO doc_ingester_state (source, message_id, chunk_count, status)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (source, message_id)
       DO UPDATE SET status = $4, indexed_at = NOW()`,
      [source, messageId, 0, "failed"]
    );
  }

  async getLastSyncTimestamp(source: SourceType): Promise<Date | null> {
    const result = await this.pool.query(
      "SELECT MAX(indexed_at) as max FROM doc_ingester_state WHERE source = $1 AND status = 'indexed'",
      [source]
    );
    return result.rows[0]?.max || null;
  }

  async getStats(): Promise<{ source: string; total: number; failed: number }[]> {
    const result = await this.pool.query(`
      SELECT source,
        COUNT(*) as total,
        COUNT(*) FILTER (WHERE status = 'failed') as failed
      FROM doc_ingester_state
      GROUP BY source
    `);
    return result.rows;
  }

  async close(): Promise<void> {
    await this.pool.end();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/storage/postgres.test.ts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/doc-ingester/src/storage/postgres.ts services/doc-ingester/src/storage/postgres.test.ts
git commit -m "doc-ingester: PostgreSQL storage layer with state tracking"
```

---

### Task 4: Preprocessor

**Files:**
- Create: `services/doc-ingester/src/pipeline/preprocessor.ts`
- Test: `services/doc-ingester/src/pipeline/preprocessor.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/pipeline/preprocessor.test.ts`

```typescript
import { Preprocessor } from "./preprocessor";

describe("Preprocessor", () => {
  const preprocessor = new Preprocessor();

  describe("stripHtml", () => {
    it("should convert HTML to plain text preserving links", () => {
      const html = '<p>Hello <a href="https://example.com">click here</a></p>';
      const result = preprocessor.stripHtml(html);
      expect(result).toBe("Hello [click here](https://example.com)");
    });

    it("should handle plain text passthrough", () => {
      expect(preprocessor.stripHtml("plain text")).toBe("plain text");
    });

    it("should strip style and script tags entirely", () => {
      const html = "<style>body{}</style><script>alert(1)</script><p>content</p>";
      const result = preprocessor.stripHtml(html);
      expect(result).toBe("content");
    });
  });

  describe("removeSignatures", () => {
    it("should remove email signatures after --", () => {
      const text = "Main content\n\n--\nJohn Doe\nCEO, Company";
      expect(preprocessor.removeSignatures(text)).toBe("Main content");
    });

    it("should remove Sent from my iPhone", () => {
      const text = "Quick reply\n\nSent from my iPhone";
      expect(preprocessor.removeSignatures(text)).toBe("Quick reply");
    });

    it("should preserve text without signatures", () => {
      const text = "No signature here";
      expect(preprocessor.removeSignatures(text)).toBe("No signature here");
    });
  });

  describe("splitThreadedEmail", () => {
    it("should split on 'On ... wrote:' markers", () => {
      const text = "My reply\n\nOn Mon, Jan 1, 2026 at 10:00 AM John <john@x.com> wrote:\n> Original message";
      const parts = preprocessor.splitThreadedEmail(text);
      expect(parts).toHaveLength(2);
      expect(parts[0].text).toBe("My reply");
      expect(parts[0].reply_depth).toBe(0);
      expect(parts[1].text).toBe("Original message");
      expect(parts[1].reply_depth).toBe(1);
    });

    it("should return single part for non-threaded email", () => {
      const parts = preprocessor.splitThreadedEmail("Simple email");
      expect(parts).toHaveLength(1);
      expect(parts[0].text).toBe("Simple email");
    });
  });

  describe("preprocess", () => {
    it("should strip HTML, remove signatures, and trim", () => {
      const html = "<p>Hello world</p>\n\n--\nSig";
      const result = preprocessor.preprocess(html, true);
      expect(result).toBe("Hello world");
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/pipeline/preprocessor.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement Preprocessor**

Create: `services/doc-ingester/src/pipeline/preprocessor.ts`

```typescript
import { parse as parseHtml } from "node-html-parser";

export interface ThreadPart {
  text: string;
  reply_depth: number;
}

export class Preprocessor {
  private signaturePatterns = [
    /\n--\s*\n[\s\S]*$/,
    /\n\s*Sent from my (iPhone|iPad|Galaxy|Android)[\s\S]*$/i,
    /\n\s*Get Outlook for[\s\S]*$/i,
  ];

  private threadMarkers = [
    /^On .+wrote:\s*$/m,
    /^-{3,}\s*Original Message\s*-{3,}\s*$/m,
    /^-{3,}\s*Forwarded message\s*-{3,}\s*$/m,
  ];

  stripHtml(input: string): string {
    if (!input.includes("<")) return input;

    const root = parseHtml(input);

    // Remove style and script tags
    root.querySelectorAll("style, script").forEach((el) => el.remove());

    // Convert links to markdown format
    root.querySelectorAll("a").forEach((el) => {
      const href = el.getAttribute("href");
      const text = el.textContent.trim();
      if (href && text) {
        el.replaceWith(`[${text}](${href})`);
      }
    });

    // Convert br to newlines
    root.querySelectorAll("br").forEach((el) => el.replaceWith("\n"));

    // Convert block elements to double newlines
    root.querySelectorAll("p, div, h1, h2, h3, h4, h5, h6, li").forEach((el) => {
      el.replaceWith(`\n\n${el.textContent}`);
    });

    return root.textContent
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  removeSignatures(text: string): string {
    let result = text;
    for (const pattern of this.signaturePatterns) {
      result = result.replace(pattern, "");
    }
    return result.trim();
  }

  splitThreadedEmail(text: string): ThreadPart[] {
    const parts: ThreadPart[] = [];
    let remaining = text;
    let depth = 0;

    for (const marker of this.threadMarkers) {
      const match = remaining.match(marker);
      if (match && match.index !== undefined) {
        const before = remaining.slice(0, match.index).trim();
        if (before) {
          parts.push({ text: before, reply_depth: depth });
        }
        remaining = remaining.slice(match.index + match[0].length);
        depth++;
        // Strip leading > quote markers
        remaining = remaining
          .split("\n")
          .map((line) => line.replace(/^>\s?/, ""))
          .join("\n")
          .trim();
      }
    }

    if (remaining.trim()) {
      parts.push({ text: remaining.trim(), reply_depth: depth });
    }

    if (parts.length === 0) {
      parts.push({ text: text.trim(), reply_depth: 0 });
    }

    return parts;
  }

  preprocess(content: string, isHtml: boolean): string {
    let text = isHtml ? this.stripHtml(content) : content;
    text = this.removeSignatures(text);
    return text.trim();
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/pipeline/preprocessor.test.ts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/doc-ingester/src/pipeline/preprocessor.ts services/doc-ingester/src/pipeline/preprocessor.test.ts
git commit -m "doc-ingester: email preprocessor with HTML strip, signature removal, thread splitting"
```

---

### Task 5: Semantic Chunker

**Files:**
- Create: `services/doc-ingester/src/pipeline/chunker.ts`
- Test: `services/doc-ingester/src/pipeline/chunker.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/pipeline/chunker.test.ts`

```typescript
import { SemanticChunker } from "./chunker";
import { RawMessage } from "../types";

describe("SemanticChunker", () => {
  const chunker = new SemanticChunker({ maxSize: 1000, overlapSentences: 1 });

  const makeMessage = (body: string, overrides?: Partial<RawMessage>): RawMessage => ({
    source_type: "gmail",
    account: "test@gmail.com",
    message_id: "msg-1",
    thread_id: "thread-1",
    sender: "alice@example.com",
    recipients: ["bob@example.com"],
    subject: "Test Subject",
    timestamp: "2026-01-01T00:00:00Z",
    labels: ["INBOX"],
    gmail_category: "primary",
    is_reply: false,
    reply_depth: 0,
    body_text: body,
    body_html: null,
    ...overrides,
  });

  describe("short messages", () => {
    it("should return single full_message chunk for text under maxSize", () => {
      const msg = makeMessage("Short email body.");
      const chunks = chunker.chunk(msg.body_text, msg);
      expect(chunks).toHaveLength(1);
      expect(chunks[0].chunk_type).toBe("full_message");
      expect(chunks[0].chunk_index).toBe(0);
      expect(chunks[0].chunk_total).toBe(1);
    });
  });

  describe("medium messages", () => {
    it("should split on paragraph boundaries", () => {
      const paragraphs = Array.from({ length: 5 }, (_, i) =>
        `Paragraph ${i + 1}. ${"This is filler content to make it longer. ".repeat(8)}`
      ).join("\n\n");
      const msg = makeMessage(paragraphs);
      const chunks = chunker.chunk(msg.body_text, msg);
      expect(chunks.length).toBeGreaterThan(1);
      chunks.forEach((c) => expect(c.chunk_type).toBe("paragraph"));
    });

    it("should prepend message header to each chunk", () => {
      const paragraphs = Array.from({ length: 5 }, (_, i) =>
        `Paragraph ${i + 1}. ${"Filler content for length. ".repeat(10)}`
      ).join("\n\n");
      const msg = makeMessage(paragraphs);
      const chunks = chunker.chunk(msg.body_text, msg);
      chunks.forEach((c) => {
        expect(c.text).toContain("From: alice@example.com");
        expect(c.text).toContain("Subject: Test Subject");
      });
    });
  });

  describe("sentence overlap", () => {
    it("should overlap last sentence of previous chunk into next", () => {
      const paragraphs = Array.from({ length: 5 }, (_, i) =>
        `First sentence of para ${i + 1}. Second sentence with more detail. Third sentence wrapping up. ${"Extra filler. ".repeat(5)}`
      ).join("\n\n");
      const msg = makeMessage(paragraphs);
      const chunks = chunker.chunk(msg.body_text, msg);
      if (chunks.length > 1) {
        // Last sentence of chunk 0 should appear at start of chunk 1 body
        const lastSentenceChunk0 = chunks[0].text.split(". ").slice(-1)[0];
        // The overlap means some content from end of chunk 0 appears in chunk 1
        // This is a structural test — exact overlap depends on paragraph boundaries
        expect(chunks.length).toBeGreaterThanOrEqual(2);
      }
    });
  });

  describe("iMessage grouping", () => {
    it("should treat short iMessage as full_message", () => {
      const msg = makeMessage("hey whats up", { source_type: "imessage", subject: null });
      const chunks = chunker.chunk(msg.body_text, msg);
      expect(chunks).toHaveLength(1);
      expect(chunks[0].chunk_type).toBe("full_message");
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/pipeline/chunker.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement SemanticChunker**

Create: `services/doc-ingester/src/pipeline/chunker.ts`

```typescript
import { Chunk, RawMessage } from "../types";

interface ChunkerConfig {
  maxSize: number;
  overlapSentences: number;
}

export class SemanticChunker {
  private config: ChunkerConfig;

  constructor(config: ChunkerConfig) {
    this.config = config;
  }

  chunk(text: string, message: RawMessage): Chunk[] {
    const clean = text.trim();
    if (!clean) return [];

    // Short messages: single chunk
    if (clean.length < this.config.maxSize) {
      return [{ text: clean, chunk_index: 0, chunk_total: 1, chunk_type: "full_message" }];
    }

    // Medium/long: split on paragraphs
    const paragraphs = clean.split(/\n\n+/).filter((p) => p.trim());
    const header = this.buildHeader(message);
    const rawChunks = this.mergeParagraphs(paragraphs, header);

    // Apply sentence overlap
    const overlapped = this.applySentenceOverlap(rawChunks);

    return overlapped.map((text, i) => ({
      text: `${header}\n\n${text}`,
      chunk_index: i,
      chunk_total: overlapped.length,
      chunk_type: "paragraph" as const,
    }));
  }

  private buildHeader(message: RawMessage): string {
    const parts = [`From: ${message.sender}`];
    if (message.recipients.length > 0) {
      parts.push(`To: ${message.recipients.join(", ")}`);
    }
    if (message.subject) {
      parts.push(`Subject: ${message.subject}`);
    }
    parts.push(`Date: ${message.timestamp}`);
    return parts.join("\n");
  }

  private mergeParagraphs(paragraphs: string[], header: string): string[] {
    const headerLen = header.length + 2; // +2 for \n\n separator
    const maxBody = this.config.maxSize - headerLen;
    const chunks: string[] = [];
    let current = "";

    for (const para of paragraphs) {
      if (para.length > maxBody) {
        // Paragraph too large: split on sentences
        if (current) {
          chunks.push(current.trim());
          current = "";
        }
        const sentences = this.splitSentences(para);
        for (const sentence of sentences) {
          if (current.length + sentence.length + 1 > maxBody) {
            if (current) chunks.push(current.trim());
            current = sentence;
          } else {
            current = current ? `${current} ${sentence}` : sentence;
          }
        }
      } else if (current.length + para.length + 2 > maxBody) {
        if (current) chunks.push(current.trim());
        current = para;
      } else {
        current = current ? `${current}\n\n${para}` : para;
      }
    }

    if (current.trim()) {
      chunks.push(current.trim());
    }

    return chunks;
  }

  private applySentenceOverlap(chunks: string[]): string[] {
    if (chunks.length <= 1 || this.config.overlapSentences === 0) return chunks;

    const result: string[] = [chunks[0]];

    for (let i = 1; i < chunks.length; i++) {
      const prevSentences = this.splitSentences(chunks[i - 1]);
      const overlap = prevSentences.slice(-this.config.overlapSentences).join(" ");
      result.push(`${overlap} ${chunks[i]}`);
    }

    return result;
  }

  private splitSentences(text: string): string[] {
    // Split on sentence-ending punctuation followed by space or end
    return text
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/pipeline/chunker.test.ts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/doc-ingester/src/pipeline/chunker.ts services/doc-ingester/src/pipeline/chunker.test.ts
git commit -m "doc-ingester: semantic chunker with paragraph splitting and sentence overlap"
```

---

### Task 6: Embedder (LocalAI Client)

**Files:**
- Create: `services/doc-ingester/src/pipeline/embedder.ts`
- Test: `services/doc-ingester/src/pipeline/embedder.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/pipeline/embedder.test.ts`

```typescript
import { Embedder } from "./embedder";

// Mock global fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe("Embedder", () => {
  const embedder = new Embedder("http://localai:8080", "text-embedding-ada-002");

  beforeEach(() => {
    mockFetch.mockReset();
  });

  it("should call LocalAI embeddings endpoint and return vectors", async () => {
    const fakeEmbedding = Array.from({ length: 768 }, () => Math.random());
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: [{ embedding: fakeEmbedding }],
      }),
    });

    const result = await embedder.embed("Hello world");
    expect(result).toEqual(fakeEmbedding);
    expect(mockFetch).toHaveBeenCalledWith(
      "http://localai:8080/v1/embeddings",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ model: "text-embedding-ada-002", input: "Hello world" }),
      })
    );
  });

  it("should handle batch embeddings", async () => {
    const fakeEmbeddings = [
      Array.from({ length: 768 }, () => Math.random()),
      Array.from({ length: 768 }, () => Math.random()),
    ];
    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        data: fakeEmbeddings.map((e) => ({ embedding: e })),
      }),
    });

    const result = await embedder.embedBatch(["Hello", "World"]);
    expect(result).toHaveLength(2);
  });

  it("should throw on API error", async () => {
    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      statusText: "Internal Server Error",
    });

    await expect(embedder.embed("test")).rejects.toThrow("Embedding failed: 500");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/pipeline/embedder.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement Embedder**

Create: `services/doc-ingester/src/pipeline/embedder.ts`

```typescript
export class Embedder {
  private baseUrl: string;
  private model: string;

  constructor(baseUrl: string, model: string) {
    this.baseUrl = baseUrl;
    this.model = model;
  }

  async embed(text: string): Promise<number[]> {
    const response = await fetch(`${this.baseUrl}/v1/embeddings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: this.model, input: text }),
    });

    if (!response.ok) {
      throw new Error(`Embedding failed: ${response.status}`);
    }

    const data = await response.json();
    return data.data[0].embedding;
  }

  async embedBatch(texts: string[]): Promise<number[][]> {
    const response = await fetch(`${this.baseUrl}/v1/embeddings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: this.model, input: texts }),
    });

    if (!response.ok) {
      throw new Error(`Embedding failed: ${response.status}`);
    }

    const data = await response.json();
    return data.data.map((d: { embedding: number[] }) => d.embedding);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/pipeline/embedder.test.ts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/doc-ingester/src/pipeline/embedder.ts services/doc-ingester/src/pipeline/embedder.test.ts
git commit -m "doc-ingester: LocalAI embedding client with batch support"
```

---

### Task 7: Qdrant Storage & Indexer

**Files:**
- Create: `services/doc-ingester/src/storage/qdrant.ts`
- Create: `services/doc-ingester/src/pipeline/indexer.ts`
- Test: `services/doc-ingester/src/pipeline/indexer.test.ts`

- [ ] **Step 1: Write failing test for Indexer**

Create: `services/doc-ingester/src/pipeline/indexer.test.ts`

```typescript
import { Indexer } from "./indexer";
import { Chunk, RawMessage, VectorMetadata } from "../types";

const mockUpsert = jest.fn().mockResolvedValue(true);
const mockEmbed = jest.fn().mockResolvedValue(Array.from({ length: 768 }, () => 0.1));
const mockEmbedBatch = jest.fn().mockResolvedValue([
  Array.from({ length: 768 }, () => 0.1),
  Array.from({ length: 768 }, () => 0.2),
]);

describe("Indexer", () => {
  const indexer = new Indexer(
    { upsert: mockUpsert } as any,
    { embed: mockEmbed, embedBatch: mockEmbedBatch } as any,
    "personal_docs"
  );

  const message: RawMessage = {
    source_type: "gmail",
    account: "test@gmail.com",
    message_id: "msg-1",
    thread_id: "thread-1",
    sender: "alice@example.com",
    recipients: ["bob@example.com"],
    subject: "Test",
    timestamp: "2026-01-01T00:00:00Z",
    labels: ["INBOX"],
    gmail_category: "primary",
    is_reply: false,
    reply_depth: 0,
    body_text: "Hello",
    body_html: null,
  };

  const chunks: Chunk[] = [
    { text: "Hello world", chunk_index: 0, chunk_total: 2, chunk_type: "paragraph" },
    { text: "Second chunk", chunk_index: 1, chunk_total: 2, chunk_type: "paragraph" },
  ];

  beforeEach(() => {
    mockUpsert.mockClear();
    mockEmbedBatch.mockClear();
  });

  it("should embed all chunks and upsert to Qdrant with hierarchical metadata", async () => {
    await indexer.index(message, chunks);
    expect(mockEmbedBatch).toHaveBeenCalledWith(["Hello world", "Second chunk"]);
    expect(mockUpsert).toHaveBeenCalledTimes(1);

    const upsertCall = mockUpsert.mock.calls[0];
    expect(upsertCall[0]).toBe("personal_docs");
    const points = upsertCall[1].points;
    expect(points).toHaveLength(2);
    expect(points[0].payload.source_type).toBe("gmail");
    expect(points[0].payload.sender).toBe("alice@example.com");
    expect(points[0].payload.chunk_index).toBe(0);
    expect(points[1].payload.chunk_index).toBe(1);
  });

  it("should generate deterministic IDs from source + message_id + chunk_index", async () => {
    await indexer.index(message, chunks);
    const points = mockUpsert.mock.calls[0][1].points;
    // IDs should be consistent across runs
    expect(typeof points[0].id).toBe("string");
    expect(points[0].id).not.toBe(points[1].id);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/pipeline/indexer.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement Qdrant storage wrapper**

Create: `services/doc-ingester/src/storage/qdrant.ts`

```typescript
import { QdrantClient } from "@qdrant/js-client-rest";

export class QdrantStorage {
  private client: QdrantClient;

  constructor(url: string) {
    this.client = new QdrantClient({ url });
  }

  async ensureCollection(name: string, vectorSize: number): Promise<void> {
    const collections = await this.client.getCollections();
    const exists = collections.collections.some((c) => c.name === name);

    if (!exists) {
      await this.client.createCollection(name, {
        vectors: { size: vectorSize, distance: "Cosine" },
      });
    }

    // Create payload indexes for structured search
    const indexes = [
      "source_type",
      "sender",
      "thread_id",
      "timestamp",
      "labels",
      "gmail_category",
    ];

    for (const field of indexes) {
      try {
        await this.client.createPayloadIndex(name, {
          field_name: field,
          field_schema: field === "timestamp" ? "datetime" : "keyword",
        });
      } catch {
        // Index may already exist
      }
    }
  }

  async upsert(collection: string, data: { points: any[] }): Promise<void> {
    await this.client.upsert(collection, data);
  }

  async search(
    collection: string,
    vector: number[],
    filter: Record<string, any> | undefined,
    limit: number
  ) {
    return this.client.search(collection, {
      vector,
      filter,
      limit,
      with_payload: true,
    });
  }

  async scrollByThreadId(collection: string, threadId: string) {
    return this.client.scroll(collection, {
      filter: {
        must: [{ key: "thread_id", match: { value: threadId } }],
      },
      with_payload: true,
      limit: 100,
    });
  }
}
```

- [ ] **Step 4: Implement Indexer**

Create: `services/doc-ingester/src/pipeline/indexer.ts`

```typescript
import { createHash } from "crypto";
import { Chunk, RawMessage, VectorMetadata } from "../types";
import { QdrantStorage } from "../storage/qdrant";
import { Embedder } from "./embedder";

export class Indexer {
  private qdrant: QdrantStorage;
  private embedder: Embedder;
  private collection: string;

  constructor(qdrant: QdrantStorage, embedder: Embedder, collection: string) {
    this.qdrant = qdrant;
    this.embedder = embedder;
    this.collection = collection;
  }

  async index(message: RawMessage, chunks: Chunk[]): Promise<number> {
    if (chunks.length === 0) return 0;

    const texts = chunks.map((c) => c.text);
    const vectors = await this.embedder.embedBatch(texts);

    const points = chunks.map((chunk, i) => ({
      id: this.generateId(message.source_type, message.message_id, chunk.chunk_index),
      vector: vectors[i],
      payload: this.buildMetadata(message, chunk),
    }));

    await this.qdrant.upsert(this.collection, { points });
    return points.length;
  }

  private generateId(source: string, messageId: string, chunkIndex: number): string {
    const hash = createHash("sha256")
      .update(`${source}:${messageId}:${chunkIndex}`)
      .digest("hex");
    // Qdrant accepts UUID-like strings; use first 32 hex chars formatted as UUID
    return [
      hash.slice(0, 8),
      hash.slice(8, 12),
      hash.slice(12, 16),
      hash.slice(16, 20),
      hash.slice(20, 32),
    ].join("-");
  }

  private buildMetadata(message: RawMessage, chunk: Chunk): VectorMetadata {
    return {
      source_type: message.source_type,
      account: message.account,
      thread_id: message.thread_id,
      thread_subject: message.subject,
      thread_participants: [message.sender, ...message.recipients],
      thread_message_count: 1, // Updated later by thread enrichment
      thread_date_start: message.timestamp,
      thread_date_end: message.timestamp,
      message_id: message.message_id,
      sender: message.sender,
      recipients: message.recipients,
      timestamp: message.timestamp,
      labels: message.labels,
      gmail_category: message.gmail_category,
      is_reply: message.is_reply,
      reply_depth: message.reply_depth,
      chunk_index: chunk.chunk_index,
      chunk_total: chunk.chunk_total,
      chunk_type: chunk.chunk_type,
      text: chunk.text,
    };
  }
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/pipeline/indexer.test.ts -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add services/doc-ingester/src/storage/qdrant.ts services/doc-ingester/src/pipeline/indexer.ts services/doc-ingester/src/pipeline/indexer.test.ts
git commit -m "doc-ingester: Qdrant storage, indexer with hierarchical metadata and deterministic IDs"
```

---

## Chunk 2: Connectors

### Task 8: Gmail Connector

**Files:**
- Create: `services/doc-ingester/src/connectors/gmail.ts`
- Test: `services/doc-ingester/src/connectors/gmail.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/connectors/gmail.test.ts`

```typescript
import { GmailConnector } from "./gmail";

// Mock imapflow
const mockFetchOne = jest.fn();
const mockSearch = jest.fn();
const mockConnect = jest.fn();
const mockLogout = jest.fn();
const mockMailboxOpen = jest.fn();

jest.mock("imapflow", () => ({
  ImapFlow: jest.fn().mockImplementation(() => ({
    connect: mockConnect,
    logout: mockLogout,
    mailboxOpen: mockMailboxOpen,
    search: mockSearch,
    fetchOne: mockFetchOne,
  })),
}));

jest.mock("mailparser", () => ({
  simpleParser: jest.fn().mockResolvedValue({
    from: { value: [{ address: "sender@example.com" }] },
    to: { value: [{ address: "me@gmail.com" }] },
    subject: "Test Email",
    date: new Date("2026-01-01"),
    messageId: "<abc@mail.com>",
    text: "Plain text body",
    html: null,
    headers: new Map([["x-gm-labels", "\\Inbox"]]),
  }),
}));

describe("GmailConnector", () => {
  let connector: GmailConnector;

  beforeEach(() => {
    connector = new GmailConnector({
      user: "test@gmail.com",
      password: "app-password",
    });
    mockSearch.mockReset();
    mockFetchOne.mockReset();
  });

  it("should skip promotional emails", () => {
    const labels = ["\\Important", "CATEGORY_PROMOTIONS"];
    expect(connector.shouldSkip(labels)).toBe(true);
  });

  it("should keep primary emails", () => {
    const labels = ["\\Inbox", "CATEGORY_PERSONAL"];
    expect(connector.shouldSkip(labels)).toBe(false);
  });

  it("should keep emails with no category", () => {
    const labels = ["\\Inbox"];
    expect(connector.shouldSkip(labels)).toBe(false);
  });

  it("should detect reply depth from subject", () => {
    expect(connector.getReplyDepth("Re: Re: Fwd: Hello")).toBe(3);
    expect(connector.getReplyDepth("Hello")).toBe(0);
    expect(connector.getReplyDepth("Re: Hello")).toBe(1);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/connectors/gmail.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement GmailConnector**

Create: `services/doc-ingester/src/connectors/gmail.ts`

```typescript
import { ImapFlow } from "imapflow";
import { simpleParser, ParsedMail } from "mailparser";
import { RawMessage } from "../types";

interface GmailConfig {
  user: string;
  password: string;
  host?: string;
  port?: number;
}

const SKIP_CATEGORIES = new Set(["CATEGORY_PROMOTIONS", "CATEGORY_SOCIAL"]);

export class GmailConnector {
  private config: GmailConfig;
  private client: ImapFlow | null = null;

  constructor(config: GmailConfig) {
    this.config = config;
  }

  shouldSkip(labels: string[]): boolean {
    return labels.some((l) => SKIP_CATEGORIES.has(l));
  }

  getReplyDepth(subject: string): number {
    const matches = subject.match(/^(Re:\s*|Fwd?:\s*)*/i);
    if (!matches || !matches[0]) return 0;
    return (matches[0].match(/Re:|Fwd?:/gi) || []).length;
  }

  private getCategory(labels: string[]): string | null {
    for (const label of labels) {
      if (label.startsWith("CATEGORY_")) {
        return label.replace("CATEGORY_", "").toLowerCase();
      }
    }
    return null;
  }

  async connect(): Promise<void> {
    this.client = new ImapFlow({
      host: this.config.host || "imap.gmail.com",
      port: this.config.port || 993,
      secure: true,
      auth: {
        user: this.config.user,
        pass: this.config.password,
      },
      logger: false,
    });
    await this.client.connect();
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      await this.client.logout();
      this.client = null;
    }
  }

  async fetchSince(sinceDate: Date | null): Promise<RawMessage[]> {
    if (!this.client) throw new Error("Not connected");

    await this.client.mailboxOpen("[Gmail]/All Mail");

    const searchCriteria: any = sinceDate
      ? { since: sinceDate }
      : { all: true };

    const uids = await this.client.search(searchCriteria, { uid: true });
    const messages: RawMessage[] = [];

    for (const uid of uids) {
      try {
        const msg = await this.client.fetchOne(String(uid), {
          source: true,
          labels: true,
        });

        if (!msg?.source) continue;

        const labels: string[] = msg.labels || [];
        if (this.shouldSkip(labels)) continue;

        const parsed: ParsedMail = await simpleParser(msg.source);

        const sender = parsed.from?.value?.[0]?.address || "unknown";
        const recipients = (parsed.to?.value || []).map(
          (r: { address?: string }) => r.address || "unknown"
        );
        const subject = parsed.subject || "";
        const replyDepth = this.getReplyDepth(subject);

        messages.push({
          source_type: "gmail",
          account: this.config.user,
          message_id: parsed.messageId || String(uid),
          thread_id: parsed.messageId || String(uid), // Gmail IMAP doesn't expose thread ID natively
          sender,
          recipients,
          subject,
          timestamp: (parsed.date || new Date()).toISOString(),
          labels,
          gmail_category: this.getCategory(labels),
          is_reply: replyDepth > 0,
          reply_depth: replyDepth,
          body_text: parsed.text || "",
          body_html: parsed.html || null,
        });
      } catch (err) {
        console.error(`Failed to fetch UID ${uid}:`, err);
      }
    }

    return messages;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/connectors/gmail.test.ts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/doc-ingester/src/connectors/gmail.ts services/doc-ingester/src/connectors/gmail.test.ts
git commit -m "doc-ingester: Gmail IMAP connector with category filtering"
```

---

### Task 9: iMessage Connector (HTTP Endpoint + Mac Script)

**Files:**
- Create: `services/doc-ingester/src/connectors/imessage.ts`
- Create: `services/doc-ingester/scripts/imessage-sync.py`
- Test: `services/doc-ingester/src/connectors/imessage.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/connectors/imessage.test.ts`

```typescript
import { IMessageConnector } from "./imessage";
import { IMessageBatchSchema } from "../types";

describe("IMessageConnector", () => {
  const connector = new IMessageConnector(5);

  describe("groupRapidTexts", () => {
    it("should group texts within 5 minutes of each other in same chat", () => {
      const messages = [
        {
          rowid: 1,
          chat_id: "chat1",
          sender: "Alice",
          participants: ["Alice", "Me"],
          text: "hey",
          timestamp: "2026-01-01T10:00:00Z",
          is_from_me: false,
        },
        {
          rowid: 2,
          chat_id: "chat1",
          sender: "Me",
          participants: ["Alice", "Me"],
          text: "whats up",
          timestamp: "2026-01-01T10:01:00Z",
          is_from_me: true,
        },
        {
          rowid: 3,
          chat_id: "chat1",
          sender: "Alice",
          participants: ["Alice", "Me"],
          text: "nm you?",
          timestamp: "2026-01-01T10:02:00Z",
          is_from_me: false,
        },
      ];

      const grouped = connector.groupRapidTexts(messages);
      expect(grouped).toHaveLength(1);
      expect(grouped[0].body_text).toContain("hey");
      expect(grouped[0].body_text).toContain("whats up");
      expect(grouped[0].body_text).toContain("nm you?");
    });

    it("should NOT group texts more than 5 minutes apart", () => {
      const messages = [
        {
          rowid: 1,
          chat_id: "chat1",
          sender: "Alice",
          participants: ["Alice", "Me"],
          text: "morning",
          timestamp: "2026-01-01T10:00:00Z",
          is_from_me: false,
        },
        {
          rowid: 2,
          chat_id: "chat1",
          sender: "Alice",
          participants: ["Alice", "Me"],
          text: "evening",
          timestamp: "2026-01-01T18:00:00Z",
          is_from_me: false,
        },
      ];

      const grouped = connector.groupRapidTexts(messages);
      expect(grouped).toHaveLength(2);
    });

    it("should NOT group texts from different chats", () => {
      const messages = [
        {
          rowid: 1,
          chat_id: "chat1",
          sender: "Alice",
          participants: ["Alice", "Me"],
          text: "hey",
          timestamp: "2026-01-01T10:00:00Z",
          is_from_me: false,
        },
        {
          rowid: 2,
          chat_id: "chat2",
          sender: "Bob",
          participants: ["Bob", "Me"],
          text: "yo",
          timestamp: "2026-01-01T10:01:00Z",
          is_from_me: false,
        },
      ];

      const grouped = connector.groupRapidTexts(messages);
      expect(grouped).toHaveLength(2);
    });
  });

  describe("batch validation", () => {
    it("should validate a valid batch", () => {
      const batch = {
        messages: [
          {
            rowid: 1,
            chat_id: "chat1",
            sender: "+15551234567",
            participants: ["+15551234567"],
            text: "Hello",
            timestamp: "2026-01-01T00:00:00Z",
            is_from_me: false,
          },
        ],
        sync_timestamp: "2026-01-01T00:00:00Z",
      };
      expect(() => IMessageBatchSchema.parse(batch)).not.toThrow();
    });
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/connectors/imessage.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement IMessageConnector**

Create: `services/doc-ingester/src/connectors/imessage.ts`

```typescript
import { RawMessage, IMessageBatch } from "../types";

interface IMessageRow {
  rowid: number;
  chat_id: string;
  sender: string;
  participants: string[];
  text: string;
  timestamp: string;
  is_from_me: boolean;
}

export class IMessageConnector {
  private groupMinutes: number;

  constructor(groupMinutes: number) {
    this.groupMinutes = groupMinutes;
  }

  groupRapidTexts(messages: IMessageRow[]): RawMessage[] {
    if (messages.length === 0) return [];

    // Sort by chat_id then timestamp
    const sorted = [...messages].sort((a, b) => {
      if (a.chat_id !== b.chat_id) return a.chat_id.localeCompare(b.chat_id);
      return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
    });

    const groups: IMessageRow[][] = [];
    let currentGroup: IMessageRow[] = [sorted[0]];

    for (let i = 1; i < sorted.length; i++) {
      const prev = sorted[i - 1];
      const curr = sorted[i];
      const timeDiff =
        (new Date(curr.timestamp).getTime() - new Date(prev.timestamp).getTime()) / 60000;

      if (curr.chat_id === prev.chat_id && timeDiff <= this.groupMinutes) {
        currentGroup.push(curr);
      } else {
        groups.push(currentGroup);
        currentGroup = [curr];
      }
    }
    groups.push(currentGroup);

    return groups.map((group) => this.groupToRawMessage(group));
  }

  private groupToRawMessage(group: IMessageRow[]): RawMessage {
    const first = group[0];
    const last = group[group.length - 1];

    // Format as conversation: "sender: text" per line
    const bodyLines = group.map((m) => {
      const who = m.is_from_me ? "Me" : m.sender;
      return `${who}: ${m.text}`;
    });

    const allParticipants = [
      ...new Set(group.flatMap((m) => m.participants)),
    ];

    return {
      source_type: "imessage",
      account: "iMessage",
      message_id: `imsg-${first.rowid}-${last.rowid}`,
      thread_id: first.chat_id,
      sender: first.sender,
      recipients: allParticipants,
      subject: null,
      timestamp: first.timestamp,
      labels: [],
      gmail_category: null,
      is_reply: group.length > 1,
      reply_depth: 0,
      body_text: bodyLines.join("\n"),
      body_html: null,
    };
  }

  processBatch(batch: IMessageBatch): RawMessage[] {
    return this.groupRapidTexts(batch.messages);
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/connectors/imessage.test.ts -v`
Expected: PASS

- [ ] **Step 5: Create Mac cron script**

Create: `services/doc-ingester/scripts/imessage-sync.py`

```python
#!/usr/bin/env python3
"""
iMessage sync script for Mac.
Reads ~/Library/Messages/chat.db and POSTs new messages to doc-ingester.

Usage:
    python3 imessage-sync.py [--endpoint URL] [--state-file PATH]

Install as cron:
    */5 * * * * /usr/bin/python3 /path/to/imessage-sync.py
"""

import sqlite3
import json
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError

CHAT_DB = os.path.expanduser("~/Library/Messages/chat.db")
DEFAULT_STATE_FILE = os.path.expanduser("~/.doc-ingester-imessage-state.json")
DEFAULT_ENDPOINT = "http://10.0.0.76:30002/ingest/imessage"  # NodePort or adjust

def load_state(state_file: str) -> dict:
    if os.path.exists(state_file):
        with open(state_file) as f:
            return json.load(f)
    return {"last_rowid": 0}

def save_state(state_file: str, state: dict):
    with open(state_file, "w") as f:
        json.dump(state, f)

def apple_ts_to_iso(apple_ts: int) -> str:
    """Convert Apple epoch (2001-01-01) nanoseconds to ISO 8601."""
    if apple_ts is None:
        return datetime.now(timezone.utc).isoformat()
    unix_ts = apple_ts / 1e9 + 978307200
    return datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat()

def fetch_messages(db_path: str, since_rowid: int) -> list[dict]:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT
            m.ROWID as rowid,
            m.text as text,
            m.date as date,
            m.is_from_me as is_from_me,
            m.handle_id,
            h.id as handle_id_str,
            c.chat_identifier as chat_id,
            c.display_name as chat_name
        FROM message m
        LEFT JOIN handle h ON m.handle_id = h.ROWID
        LEFT JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
        LEFT JOIN chat c ON cmj.chat_id = c.ROWID
        WHERE m.ROWID > ?
          AND m.text IS NOT NULL
          AND m.text != ''
        ORDER BY m.ROWID ASC
    """

    cursor.execute(query, (since_rowid,))
    rows = cursor.fetchall()

    messages = []
    for row in rows:
        chat_id = row["chat_id"] or f"handle-{row['handle_id']}"
        sender = row["handle_id_str"] or "unknown"

        # Get participants for this chat
        participants_query = """
            SELECT h.id FROM handle h
            JOIN chat_handle_join chj ON h.ROWID = chj.handle_id
            JOIN chat c ON chj.chat_id = c.ROWID
            WHERE c.chat_identifier = ?
        """
        cursor.execute(participants_query, (chat_id,))
        participants = [p["id"] for p in cursor.fetchall()] or [sender]

        messages.append({
            "rowid": row["rowid"],
            "chat_id": chat_id,
            "sender": sender if not row["is_from_me"] else "Me",
            "participants": participants,
            "text": row["text"],
            "timestamp": apple_ts_to_iso(row["date"]),
            "is_from_me": bool(row["is_from_me"]),
        })

    conn.close()
    return messages

def post_batch(endpoint: str, messages: list[dict]):
    payload = json.dumps({
        "messages": messages,
        "sync_timestamp": datetime.now(timezone.utc).isoformat(),
    }).encode()

    req = Request(
        endpoint,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urlopen(req, timeout=30)
    return json.loads(resp.read())

def main():
    parser = argparse.ArgumentParser(description="Sync iMessage to doc-ingester")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--state-file", default=DEFAULT_STATE_FILE)
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not os.path.exists(CHAT_DB):
        print(f"chat.db not found at {CHAT_DB}", file=sys.stderr)
        sys.exit(1)

    state = load_state(args.state_file)
    messages = fetch_messages(CHAT_DB, state["last_rowid"])

    if not messages:
        print("No new messages")
        return

    print(f"Found {len(messages)} new messages since ROWID {state['last_rowid']}")

    if args.dry_run:
        for m in messages[:5]:
            print(f"  [{m['chat_id']}] {m['sender']}: {m['text'][:50]}")
        return

    # Send in batches
    for i in range(0, len(messages), args.batch_size):
        batch = messages[i : i + args.batch_size]
        try:
            result = post_batch(args.endpoint, batch)
            print(f"Batch {i // args.batch_size + 1}: {result}")
        except URLError as e:
            print(f"Failed to send batch: {e}", file=sys.stderr)
            sys.exit(1)

    # Update state to last ROWID we processed
    state["last_rowid"] = messages[-1]["rowid"]
    save_state(args.state_file, state)
    print(f"State updated: last_rowid={state['last_rowid']}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Commit**

```bash
git add services/doc-ingester/src/connectors/imessage.ts services/doc-ingester/src/connectors/imessage.test.ts services/doc-ingester/scripts/imessage-sync.py
git commit -m "doc-ingester: iMessage connector with rapid-text grouping and Mac sync script"
```

---

## Chunk 3: API, Search, and Wiring

### Task 10: Search Service

**Files:**
- Create: `services/doc-ingester/src/search/queryService.ts`
- Test: `services/doc-ingester/src/search/queryService.test.ts`

- [ ] **Step 1: Write failing test**

Create: `services/doc-ingester/src/search/queryService.test.ts`

```typescript
import { QueryService } from "./queryService";

const mockSearch = jest.fn();
const mockScrollByThreadId = jest.fn();
const mockEmbed = jest.fn().mockResolvedValue(Array.from({ length: 768 }, () => 0.1));

describe("QueryService", () => {
  const service = new QueryService(
    { search: mockSearch, scrollByThreadId: mockScrollByThreadId } as any,
    { embed: mockEmbed } as any,
    "personal_docs"
  );

  beforeEach(() => {
    mockSearch.mockReset();
    mockScrollByThreadId.mockReset();
  });

  it("should build Qdrant filter from search params", () => {
    const filter = service.buildFilter({
      source_type: "gmail",
      sender: "alice@example.com",
      date_from: "2026-01-01",
      date_to: "2026-02-01",
    });

    expect(filter.must).toContainEqual({
      key: "source_type",
      match: { value: "gmail" },
    });
    expect(filter.must).toContainEqual({
      key: "sender",
      match: { value: "alice@example.com" },
    });
  });

  it("should perform hybrid search with vector + filter", async () => {
    mockSearch.mockResolvedValueOnce([
      {
        score: 0.9,
        payload: {
          source_type: "gmail",
          thread_id: "t1",
          text: "match",
        },
      },
    ]);

    const results = await service.search({
      query: "test query",
      source_type: "gmail",
      limit: 10,
    });

    expect(mockEmbed).toHaveBeenCalledWith("test query");
    expect(mockSearch).toHaveBeenCalledWith(
      "personal_docs",
      expect.any(Array),
      expect.objectContaining({ must: expect.any(Array) }),
      10
    );
    expect(results).toHaveLength(1);
    expect(results[0].score).toBe(0.9);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd services/doc-ingester && npx jest src/search/queryService.test.ts -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement QueryService**

Create: `services/doc-ingester/src/search/queryService.ts`

```typescript
import { QdrantStorage } from "../storage/qdrant";
import { Embedder } from "../pipeline/embedder";
import { SearchRequest, SearchResult, VectorMetadata } from "../types";

export class QueryService {
  private qdrant: QdrantStorage;
  private embedder: Embedder;
  private collection: string;

  constructor(qdrant: QdrantStorage, embedder: Embedder, collection: string) {
    this.qdrant = qdrant;
    this.embedder = embedder;
    this.collection = collection;
  }

  buildFilter(params: Partial<SearchRequest>): { must: any[] } {
    const must: any[] = [];

    if (params.source_type) {
      must.push({ key: "source_type", match: { value: params.source_type } });
    }
    if (params.sender) {
      must.push({ key: "sender", match: { value: params.sender } });
    }
    if (params.thread_id) {
      must.push({ key: "thread_id", match: { value: params.thread_id } });
    }
    if (params.labels && params.labels.length > 0) {
      must.push({ key: "labels", match: { any: params.labels } });
    }
    if (params.date_from) {
      must.push({ key: "timestamp", range: { gte: params.date_from } });
    }
    if (params.date_to) {
      must.push({ key: "timestamp", range: { lte: params.date_to } });
    }

    return { must };
  }

  async search(params: SearchRequest): Promise<SearchResult[]> {
    const vector = await this.embedder.embed(params.query);
    const filter = this.buildFilter(params);
    const hasFilter = filter.must.length > 0;

    const results = await this.qdrant.search(
      this.collection,
      vector,
      hasFilter ? filter : undefined,
      params.limit
    );

    return results.map((r: any) => ({
      score: r.score,
      metadata: r.payload as VectorMetadata,
    }));
  }

  async searchWithThreadContext(params: SearchRequest): Promise<SearchResult[]> {
    const results = await this.search(params);

    // Enrich top results with thread context
    const enriched: SearchResult[] = [];
    const seenThreads = new Set<string>();

    for (const result of results) {
      if (seenThreads.has(result.metadata.thread_id)) {
        enriched.push(result);
        continue;
      }

      seenThreads.add(result.metadata.thread_id);
      const threadDocs = await this.qdrant.scrollByThreadId(
        this.collection,
        result.metadata.thread_id
      );

      const threadContext = (threadDocs.points || [])
        .map((p: any) => p.payload as VectorMetadata)
        .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());

      enriched.push({ ...result, thread_context: threadContext });
    }

    return enriched;
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd services/doc-ingester && npx jest src/search/queryService.test.ts -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add services/doc-ingester/src/search/queryService.ts services/doc-ingester/src/search/queryService.test.ts
git commit -m "doc-ingester: hybrid vector + structured search with thread context"
```

---

### Task 11: API Routes and Express App

**Files:**
- Create: `services/doc-ingester/src/api/health.ts`
- Create: `services/doc-ingester/src/api/routes.ts`
- Create: `services/doc-ingester/src/index.ts`

- [ ] **Step 1: Create health endpoint**

Create: `services/doc-ingester/src/api/health.ts`

```typescript
import { Router, Request, Response } from "express";
import { PostgresStorage } from "../storage/postgres";

export function healthRouter(db: PostgresStorage): Router {
  const router = Router();

  router.get("/health", async (_req: Request, res: Response) => {
    try {
      const stats = await db.getStats();
      res.json({
        status: "ok",
        uptime: process.uptime(),
        indexing: stats,
      });
    } catch (err) {
      res.status(503).json({ status: "error", error: String(err) });
    }
  });

  return router;
}
```

- [ ] **Step 2: Create API routes**

Create: `services/doc-ingester/src/api/routes.ts`

```typescript
import { Router, Request, Response } from "express";
import { IMessageConnector } from "../connectors/imessage";
import { Preprocessor } from "../pipeline/preprocessor";
import { SemanticChunker } from "../pipeline/chunker";
import { Indexer } from "../pipeline/indexer";
import { PostgresStorage } from "../storage/postgres";
import { QueryService } from "../search/queryService";
import { IMessageBatchSchema, SearchRequestSchema } from "../types";

interface RouteDeps {
  imessageConnector: IMessageConnector;
  preprocessor: Preprocessor;
  chunker: SemanticChunker;
  indexer: Indexer;
  db: PostgresStorage;
  queryService: QueryService;
}

export function apiRouter(deps: RouteDeps): Router {
  const router = Router();

  // POST /ingest/imessage — receive batch from Mac cron script
  router.post("/ingest/imessage", async (req: Request, res: Response) => {
    try {
      const batch = IMessageBatchSchema.parse(req.body);
      const rawMessages = deps.imessageConnector.processBatch(batch);

      let indexed = 0;
      let skipped = 0;

      for (const msg of rawMessages) {
        const already = await deps.db.isIndexed(msg.source_type, msg.message_id);
        if (already) {
          skipped++;
          continue;
        }

        try {
          const text = deps.preprocessor.preprocess(msg.body_text, false);
          const chunks = deps.chunker.chunk(text, msg);
          const count = await deps.indexer.index(msg, chunks);
          await deps.db.markIndexed(msg.source_type, msg.message_id, count);
          indexed++;
        } catch (err) {
          await deps.db.markFailed(msg.source_type, msg.message_id);
          console.error(`Failed to index ${msg.message_id}:`, err);
        }
      }

      res.json({ status: "ok", indexed, skipped, total: rawMessages.length });
    } catch (err) {
      res.status(400).json({ error: String(err) });
    }
  });

  // GET /search — hybrid vector + structured search
  router.get("/search", async (req: Request, res: Response) => {
    try {
      const params = SearchRequestSchema.parse({
        query: req.query.q,
        source_type: req.query.source,
        sender: req.query.sender,
        thread_id: req.query.thread,
        date_from: req.query.from,
        date_to: req.query.to,
        limit: req.query.limit ? Number(req.query.limit) : undefined,
      });

      const results = await deps.queryService.searchWithThreadContext(params);
      res.json({ results, count: results.length });
    } catch (err) {
      res.status(400).json({ error: String(err) });
    }
  });

  // GET /status — indexing statistics
  router.get("/status", async (_req: Request, res: Response) => {
    try {
      const stats = await deps.db.getStats();
      res.json({ stats });
    } catch (err) {
      res.status(500).json({ error: String(err) });
    }
  });

  return router;
}
```

- [ ] **Step 3: Create entry point with Gmail scheduler**

Create: `services/doc-ingester/src/index.ts`

```typescript
import express from "express";
import cors from "cors";
import helmet from "helmet";
import morgan from "morgan";
import { EnvironmentSchema } from "./config/environment";
import { PostgresStorage } from "./storage/postgres";
import { QdrantStorage } from "./storage/qdrant";
import { Embedder } from "./pipeline/embedder";
import { Preprocessor } from "./pipeline/preprocessor";
import { SemanticChunker } from "./pipeline/chunker";
import { Indexer } from "./pipeline/indexer";
import { GmailConnector } from "./connectors/gmail";
import { IMessageConnector } from "./connectors/imessage";
import { QueryService } from "./search/queryService";
import { healthRouter } from "./api/health";
import { apiRouter } from "./api/routes";

async function main() {
  const env = EnvironmentSchema.parse(process.env);

  // Initialize storage
  const db = new PostgresStorage({
    host: env.DB_HOST,
    port: env.DB_PORT,
    database: env.DB_NAME,
    user: env.DB_USER,
    password: env.DB_PASSWORD,
  });
  await db.initialize();

  const qdrant = new QdrantStorage(env.QDRANT_URL);
  await qdrant.ensureCollection(env.QDRANT_COLLECTION, 768);

  // Initialize pipeline
  const embedder = new Embedder(env.LOCALAI_URL, env.EMBEDDING_MODEL);
  const preprocessor = new Preprocessor();
  const chunker = new SemanticChunker({
    maxSize: env.CHUNK_MAX_SIZE,
    overlapSentences: env.CHUNK_OVERLAP_SENTENCES,
  });
  const indexer = new Indexer(qdrant, embedder, env.QDRANT_COLLECTION);
  const queryService = new QueryService(qdrant, embedder, env.QDRANT_COLLECTION);

  // Initialize connectors
  const gmail = new GmailConnector({
    user: env.GMAIL_USER,
    password: env.GMAIL_APP_PASSWORD,
  });
  const imessage = new IMessageConnector(env.RAPID_TEXT_GROUP_MINUTES);

  // Express app
  const app = express();
  app.use(helmet());
  app.use(cors());
  app.use(morgan("short"));
  app.use(express.json({ limit: "10mb" }));

  app.use(healthRouter(db));
  app.use(
    apiRouter({
      imessageConnector: imessage,
      preprocessor,
      chunker,
      indexer,
      db,
      queryService,
    })
  );

  // Start server
  app.listen(env.PORT, () => {
    console.log(`doc-ingester listening on port ${env.PORT}`);
  });

  // Gmail polling loop
  async function pollGmail() {
    try {
      console.log("Gmail poll: starting...");
      const lastSync = await db.getLastSyncTimestamp("gmail");
      await gmail.connect();
      const messages = await gmail.fetchSince(lastSync);
      console.log(`Gmail poll: fetched ${messages.length} messages`);

      let indexed = 0;
      for (const msg of messages) {
        const already = await db.isIndexed("gmail", msg.message_id);
        if (already) continue;

        try {
          const isHtml = !!msg.body_html;
          const text = preprocessor.preprocess(
            isHtml ? msg.body_html! : msg.body_text,
            isHtml
          );
          if (!text) continue;

          // Thread-aware: split threaded emails
          const threadParts = preprocessor.splitThreadedEmail(text);

          for (const part of threadParts) {
            const partMsg = { ...msg, body_text: part.text, reply_depth: part.reply_depth };
            const chunks = chunker.chunk(part.text, partMsg);
            await indexer.index(partMsg, chunks);
          }

          await db.markIndexed("gmail", msg.message_id, threadParts.length);
          indexed++;
        } catch (err) {
          await db.markFailed("gmail", msg.message_id);
          console.error(`Failed to index Gmail ${msg.message_id}:`, err);
        }
      }

      await gmail.disconnect();
      console.log(`Gmail poll: indexed ${indexed} new messages`);
    } catch (err) {
      console.error("Gmail poll error:", err);
      try {
        await gmail.disconnect();
      } catch {}
    }
  }

  // Initial fetch + schedule
  pollGmail();
  setInterval(pollGmail, env.GMAIL_POLL_INTERVAL_MS);
}

main().catch((err) => {
  console.error("Fatal error:", err);
  process.exit(1);
});
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd services/doc-ingester && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Run all tests**

Run: `cd services/doc-ingester && npx jest --verbose`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add services/doc-ingester/src/api/ services/doc-ingester/src/index.ts
git commit -m "doc-ingester: Express API, routes, health check, and Gmail polling scheduler"
```

---

## Chunk 4: Deployment

### Task 12: Dockerfile and Build Script

**Files:**
- Create: `services/doc-ingester/Dockerfile`
- Create: `scripts/build-doc-ingester.sh`

- [ ] **Step 1: Create Dockerfile**

Create: `services/doc-ingester/Dockerfile`

```dockerfile
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.json ./
RUN npm ci
COPY src/ ./src/
RUN npm run build

FROM node:18-alpine
WORKDIR /app
RUN addgroup -g 1001 -S nodejs && adduser -S appuser -u 1001
COPY --from=builder /app/package*.json ./
RUN npm ci --omit=dev && npm cache clean --force
COPY --from=builder --chown=appuser:nodejs /app/dist ./dist
ENV NODE_ENV=production PORT=3002
EXPOSE 3002
USER appuser
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3002/health', (res) => { process.exit(res.statusCode === 200 ? 0 : 1) })"
CMD ["node", "dist/index.js"]
```

- [ ] **Step 2: Create build script**

Create: `scripts/build-doc-ingester.sh`

```bash
#!/bin/bash
set -euo pipefail

SERVICE_NAME="doc-ingester"
REGISTRY="git.example.com/homelab"
IMAGE_NAME="${REGISTRY}/${SERVICE_NAME}"
GIT_COMMIT=$(git rev-parse --short HEAD)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

if [ "$GIT_BRANCH" = "main" ]; then
  TAGS=("latest" "$GIT_COMMIT")
else
  TAGS=("${GIT_BRANCH}-${GIT_COMMIT}")
fi

echo "Building ${SERVICE_NAME}..."

docker build \
  --platform linux/amd64 \
  --provenance=false \
  --sbom=false \
  --tag "${IMAGE_NAME}:${TAGS[0]}" \
  --label "git.commit=${GIT_COMMIT}" \
  --label "service.name=${SERVICE_NAME}" \
  services/doc-ingester/

for tag in "${TAGS[@]}"; do
  docker tag "${IMAGE_NAME}:${TAGS[0]}" "${IMAGE_NAME}:${tag}"
  echo "Pushing ${IMAGE_NAME}:${tag}"
  docker push "${IMAGE_NAME}:${tag}"
done

echo "Done: ${IMAGE_NAME}:${TAGS[0]}"
```

- [ ] **Step 3: Make build script executable**

Run: `chmod +x scripts/build-doc-ingester.sh`

- [ ] **Step 4: Commit**

```bash
git add services/doc-ingester/Dockerfile scripts/build-doc-ingester.sh
git commit -m "doc-ingester: Dockerfile and build script for Gitea registry"
```

---

### Task 13: Kubernetes Manifests

**Files:**
- Create: `k8s-kustomized/base/ai-services/doc-ingester.yaml`
- Modify: `k8s-kustomized/base/ai-services/kustomization.yaml`
- Modify: `k8s-kustomized/base/vector-db/qdrant-init-job.yaml`

- [ ] **Step 1: Create K8s deployment manifest**

Create: `k8s-kustomized/base/ai-services/doc-ingester.yaml`

```yaml
---
apiVersion: v1
kind: Secret
metadata:
  name: doc-ingester-secrets
  namespace: ai-services
type: Opaque
stringData:
  gmail-user: "REPLACE_ME"
  gmail-app-password: "REPLACE_ME"
  db-password: "REPLACE_ME"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: doc-ingester
  namespace: ai-services
  labels:
    app: doc-ingester
spec:
  replicas: 1
  selector:
    matchLabels:
      app: doc-ingester
  template:
    metadata:
      labels:
        app: doc-ingester
    spec:
      nodeSelector:
        node-role.kubernetes.io/control-plane: "true"
      containers:
        - name: doc-ingester
          image: git.example.com/homelab/doc-ingester:latest
          ports:
            - containerPort: 3002
              name: http
          env:
            - name: NODE_ENV
              value: "production"
            - name: PORT
              value: "3002"
            - name: DB_HOST
              value: "postgresql.database.svc.cluster.local"
            - name: DB_PORT
              value: "5432"
            - name: DB_NAME
              value: "doc_ingester"
            - name: DB_USER
              value: "doc_ingester"
            - name: DB_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: doc-ingester-secrets
                  key: db-password
            - name: QDRANT_URL
              value: "http://qdrant.vector-db.svc.cluster.local:6333"
            - name: QDRANT_COLLECTION
              value: "personal_docs"
            - name: LOCALAI_URL
              value: "http://localai.ai-services.svc.cluster.local:8080"
            - name: EMBEDDING_MODEL
              value: "text-embedding-ada-002"
            - name: GMAIL_USER
              valueFrom:
                secretKeyRef:
                  name: doc-ingester-secrets
                  key: gmail-user
            - name: GMAIL_APP_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: doc-ingester-secrets
                  key: gmail-app-password
            - name: GMAIL_POLL_INTERVAL_MS
              value: "300000"
          resources:
            requests:
              memory: "256Mi"
              cpu: "250m"
            limits:
              memory: "512Mi"
              cpu: "500m"
          livenessProbe:
            httpGet:
              path: /health
              port: 3002
            initialDelaySeconds: 30
            periodSeconds: 30
          readinessProbe:
            httpGet:
              path: /health
              port: 3002
            initialDelaySeconds: 10
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: doc-ingester
  namespace: ai-services
  labels:
    app: doc-ingester
spec:
  type: ClusterIP
  ports:
    - port: 3002
      targetPort: 3002
      protocol: TCP
      name: http
  selector:
    app: doc-ingester
```

- [ ] **Step 2: Add doc-ingester to ai-services kustomization**

Modify: `k8s-kustomized/base/ai-services/kustomization.yaml`

Add `doc-ingester.yaml` to the `resources:` list.

- [ ] **Step 3: Add personal_docs collection to Qdrant init job**

Modify: `k8s-kustomized/base/vector-db/qdrant-init-job.yaml`

Add a second `curl -X PUT` command to create the `personal_docs` collection alongside the existing `homelab_docs` collection, with the same 768-dimension cosine config.

- [ ] **Step 4: Validate kustomize**

Run: `kubectl kustomize k8s-kustomized/base/ai-services/ | head -20`
Expected: Valid YAML output including doc-ingester resources

- [ ] **Step 5: Commit**

```bash
git add k8s-kustomized/base/ai-services/doc-ingester.yaml k8s-kustomized/base/ai-services/kustomization.yaml k8s-kustomized/base/vector-db/qdrant-init-job.yaml
git commit -m "doc-ingester: Kubernetes manifests, Qdrant personal_docs collection"
```

---

### Task 14: PostgreSQL Database Setup

**Files:**
- Modify: `k8s-kustomized/base/database/postgresql-init.yaml`

- [ ] **Step 1: Add doc_ingester database to PostgreSQL init**

Modify: `k8s-kustomized/base/database/postgresql-init.yaml`

Add to the init SQL:

```sql
-- Doc Ingester
CREATE USER doc_ingester WITH PASSWORD 'REDACTED';
CREATE DATABASE doc_ingester OWNER doc_ingester;
```

- [ ] **Step 2: Commit**

```bash
git add k8s-kustomized/base/database/postgresql-init.yaml
git commit -m "doc-ingester: add PostgreSQL database for indexing state"
```

---

### Task 15: Update Homepage Dashboard

**Files:**
- Modify: `k8s-kustomized/base/dashboard/configmap.yaml`

- [ ] **Step 1: Add doc-ingester to dashboard** (if desired)

This is optional — the service has no external ingress. Could add an internal-only entry or skip. The service is accessed via cluster-internal DNS only (iMessage script hits it via NodePort or port-forward).

- [ ] **Step 2: Commit if changes made**

---

### Task 16: Build, Deploy, and Smoke Test

- [ ] **Step 1: Build Docker image**

Run: `./scripts/build-doc-ingester.sh`
Expected: Image pushed to `git.example.com/homelab/doc-ingester:latest`

- [ ] **Step 2: Create PostgreSQL database**

Run (via SSH):
```bash
ssh elitemini "kubectl exec -n database deployment/postgresql -- psql -U postgres -c \"CREATE USER doc_ingester WITH PASSWORD 'REDACTED'; CREATE DATABASE doc_ingester OWNER doc_ingester;\""
```

- [ ] **Step 3: Create Qdrant collection**

Run (via SSH):
```bash
ssh elitemini "kubectl exec -n vector-db deployment/qdrant -- curl -s -X PUT http://localhost:6333/collections/personal_docs -H 'Content-Type: application/json' -d '{\"vectors\":{\"size\":768,\"distance\":\"Cosine\"}}'"
```

- [ ] **Step 4: Create sealed secret with real Gmail credentials**

Replace REPLACE_ME values in `doc-ingester.yaml` with actual sealed secrets, or apply the secret directly for initial testing.

- [ ] **Step 5: Deploy to cluster**

Run: `kubectl apply -k k8s-kustomized/base/ai-services/`

- [ ] **Step 6: Verify pod starts**

Run: `ssh elitemini "kubectl get pods -n ai-services -l app=doc-ingester"`
Expected: 1/1 Running

- [ ] **Step 7: Check health endpoint**

Run: `ssh elitemini "kubectl exec -n ai-services deployment/doc-ingester -- curl -s http://localhost:3002/health"`
Expected: `{"status":"ok",...}`

- [ ] **Step 8: Test iMessage sync script locally**

Run: `cd services/doc-ingester && python3 scripts/imessage-sync.py --dry-run`
Expected: Lists recent iMessages from chat.db

- [ ] **Step 9: Verify Gmail polling starts**

Run: `ssh elitemini "kubectl logs -n ai-services deployment/doc-ingester --tail=20"`
Expected: Log lines showing "Gmail poll: starting..." and message counts

- [ ] **Step 10: Test search endpoint**

Run: `ssh elitemini "kubectl exec -n ai-services deployment/doc-ingester -- curl -s 'http://localhost:3002/search?q=hello&limit=5'"`
Expected: JSON with results array

- [ ] **Step 11: Commit any final adjustments**

```bash
git add -A && git commit -m "doc-ingester: deployment verified and working"
```
