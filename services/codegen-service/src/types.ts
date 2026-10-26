import { z } from "zod";

// Request schemas
export const GenerateProjectRequestSchema = z.object({
  projectName: z.string().min(1).max(50),
  description: z.string().min(1).max(1000),
  framework: z.string().default("nextjs"),
  features: z.array(z.string()).default(["typescript", "tailwind"]),
  styling: z.string().default("tailwind"),
  database: z.string().optional(),
  userId: z.string().optional(),
  isUpdate: z.boolean().default(false),
});

export type GenerateProjectRequest = z.infer<
  typeof GenerateProjectRequestSchema
>;

// Response schemas
export const ProjectFileSchema = z.object({
  path: z.string(),
  content: z.string(),
});

export const GenerateProjectResponseSchema = z.object({
  files: z.array(ProjectFileSchema),
  instructions: z.string(),
  buildCommand: z.string(),
  startCommand: z.string(),
  dependencies: z.array(z.string()).optional(),
  devDependencies: z.array(z.string()).optional(),
});

export type ProjectFile = z.infer<typeof ProjectFileSchema>;
export type GenerateProjectResponse = z.infer<
  typeof GenerateProjectResponseSchema
>;

// API Response wrapper
export const ApiResponseSchema = z.object({
  success: z.boolean(),
  data: z.any().optional(),
  error: z.string().optional(),
  requestId: z.string(),
  timestamp: z.string(),
  model: z.string().optional(),
  tokensUsed: z.number().optional(),
});

export type ApiResponse<T = any> = {
  success: boolean;
  data?: T;
  error?: string;
  requestId: string;
  timestamp: string;
  model?: string;
  tokensUsed?: number;
};

// OpenRouter models
export const AVAILABLE_MODELS = {
  FREE: {
    "gpt-oss-20b": "openai/gpt-oss-20b:free",
    "kimi-k2": "moonshotai/kimi-k2:free",
    "llama-3.2-3b": "meta-llama/llama-3.2-3b-instruct:free",
    "phi-3-mini": "microsoft/phi-3-mini-128k-instruct:free",
  },
  PAID: {
    "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
    "gpt-4o-mini": "openai/gpt-4o-mini",
    "llama-3.1-70b": "meta-llama/llama-3.1-70b-instruct",
  },
} as const;

export type ModelType =
  | keyof typeof AVAILABLE_MODELS.FREE
  | keyof typeof AVAILABLE_MODELS.PAID;
