import express from "express";
import cors from "cors";
import helmet from "helmet";
import morgan from "morgan";
import { v4 as uuidv4 } from "uuid";
import { OpenRouterService } from "./services/openRouterService";
import { GenerateProjectRequestSchema, ApiResponse } from "./types";

const app = express();
const port = process.env.PORT || 3000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(morgan("combined"));
app.use(express.json({ limit: "10mb" }));

// Initialize OpenRouter service
const openRouterApiKey = process.env.OPENROUTER_API_KEY;
if (!openRouterApiKey) {
  console.error("❌ OPENROUTER_API_KEY environment variable is required");
  process.exit(1);
}

const openRouterService = new OpenRouterService(openRouterApiKey);

// Health check endpoint
app.get("/health", (req, res) => {
  res.json({
    status: "healthy",
    service: "codegen-service",
    timestamp: new Date().toISOString(),
    version: "1.0.0",
  });
});

// Main code generation endpoint
app.post("/generate", async (req, res) => {
  const requestId = uuidv4();
  const startTime = Date.now();

  console.log(`🚀 [${requestId}] New code generation request`);

  try {
    // Validate request
    const validationResult = GenerateProjectRequestSchema.safeParse(req.body);
    if (!validationResult.success) {
      const response: ApiResponse = {
        success: false,
        error: `Invalid request: ${validationResult.error.message}`,
        requestId,
        timestamp: new Date().toISOString(),
      };
      return res.status(400).json(response);
    }

    const request = validationResult.data;
    console.log(`📝 [${requestId}] Generating: ${request.projectName}`);
    console.log(
      `🎯 [${requestId}] Framework: ${
        request.framework
      }, Features: ${request.features.join(", ")}`
    );

    // Generate project using OpenRouter
    const result = await openRouterService.generateProject(request);

    const duration = Date.now() - startTime;
    console.log(`✅ [${requestId}] Generation completed in ${duration}ms`);

    const response: ApiResponse = {
      success: true,
      data: result,
      requestId,
      timestamp: new Date().toISOString(),
      model: "openrouter",
    };

    res.json(response);
  } catch (error) {
    const duration = Date.now() - startTime;
    console.error(
      `❌ [${requestId}] Generation failed after ${duration}ms:`,
      error
    );

    const response: ApiResponse = {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error occurred",
      requestId,
      timestamp: new Date().toISOString(),
    };

    res.status(500).json(response);
  }
});

// Model information endpoint
app.get("/models", (req, res) => {
  res.json({
    available_models: {
      free: [
        { id: "gpt-oss-20b", name: "GPT-OSS 20B", provider: "OpenAI" },
        { id: "kimi-k2", name: "Moonshot Kimi K2", provider: "Moonshot AI" },
        { id: "llama-3.2-3b", name: "Llama 3.2 3B", provider: "Meta" },
        { id: "phi-3-mini", name: "Phi-3 Mini", provider: "Microsoft" },
      ],
      paid: [
        {
          id: "claude-3.5-sonnet",
          name: "Claude 3.5 Sonnet",
          provider: "Anthropic",
        },
        { id: "gpt-4o-mini", name: "GPT-4o Mini", provider: "OpenAI" },
        { id: "llama-3.1-70b", name: "Llama 3.1 70B", provider: "Meta" },
      ],
    },
    default_model: "gpt-oss-20b",
  });
});

// Generate with specific model endpoint
app.post("/generate/:model", async (req, res) => {
  const requestId = uuidv4();
  const startTime = Date.now();
  const model = req.params.model;

  console.log(
    `🚀 [${requestId}] New code generation request with model: ${model}`
  );

  try {
    const validationResult = GenerateProjectRequestSchema.safeParse(req.body);
    if (!validationResult.success) {
      const response: ApiResponse = {
        success: false,
        error: `Invalid request: ${validationResult.error.message}`,
        requestId,
        timestamp: new Date().toISOString(),
      };
      return res.status(400).json(response);
    }

    const request = validationResult.data;
    const result = await openRouterService.generateProject(request, model);

    const duration = Date.now() - startTime;
    console.log(`✅ [${requestId}] Generation completed in ${duration}ms`);

    const response: ApiResponse = {
      success: true,
      data: result,
      requestId,
      timestamp: new Date().toISOString(),
      model: model,
    };

    res.json(response);
  } catch (error) {
    const duration = Date.now() - startTime;
    console.error(
      `❌ [${requestId}] Generation failed after ${duration}ms:`,
      error
    );

    const response: ApiResponse = {
      success: false,
      error: error instanceof Error ? error.message : "Unknown error occurred",
      requestId,
      timestamp: new Date().toISOString(),
    };

    res.status(500).json(response);
  }
});

// Error handling middleware
app.use(
  (
    err: Error,
    req: express.Request,
    res: express.Response,
    next: express.NextFunction
  ) => {
    console.error("Unhandled error:", err);
    res.status(500).json({
      success: false,
      error: "Internal server error",
      requestId: uuidv4(),
      timestamp: new Date().toISOString(),
    });
  }
);

// 404 handler
app.use((req, res) => {
  res.status(404).json({
    success: false,
    error: "Endpoint not found",
    requestId: uuidv4(),
    timestamp: new Date().toISOString(),
  });
});

app.listen(port, () => {
  console.log(`🚀 CodeGen Service running on port ${port}`);
  console.log(
    `🔑 OpenRouter API Key: ${openRouterApiKey ? "Configured" : "Missing"}`
  );
  console.log(`📊 Health check: http://localhost:${port}/health`);
  console.log(`🤖 Generate endpoint: http://localhost:${port}/generate`);
});

export default app;
