import OpenAI from "openai";
import {
  GenerateProjectRequest,
  GenerateProjectResponse,
  AVAILABLE_MODELS,
} from "../types";

export class OpenRouterService {
  private client: OpenAI;
  private defaultModel: string;

  constructor(apiKey: string, defaultModel: string = "gpt-oss-20b") {
    this.client = new OpenAI({
      baseURL: "https://openrouter.ai/api/v1",
      apiKey: apiKey,
    });

    // Map friendly names to full model IDs
    this.defaultModel =
      AVAILABLE_MODELS.FREE[
        defaultModel as keyof typeof AVAILABLE_MODELS.FREE
      ] ||
      AVAILABLE_MODELS.PAID[
        defaultModel as keyof typeof AVAILABLE_MODELS.PAID
      ] ||
      AVAILABLE_MODELS.FREE["gpt-oss-20b"];
  }

  async generateProject(
    request: GenerateProjectRequest,
    model?: string
  ): Promise<GenerateProjectResponse> {
    const selectedModel = model || this.defaultModel;

    const prompt = this.buildPrompt(request);

    console.log(
      `🤖 [OpenRouter] Generating project with model: ${selectedModel}`
    );
    console.log(`📝 [OpenRouter] Project: ${request.projectName}`);

    try {
      const completion = await this.client.chat.completions.create({
        model: selectedModel,
        messages: [
          {
            role: "system",
            content:
              "You are an expert Next.js developer. Generate complete, production-ready code. Always return valid JSON in the exact format requested.",
          },
          {
            role: "user",
            content: prompt,
          },
        ],
        temperature: 0.7,
        max_tokens: 4000,
      });

      const response = completion.choices[0].message.content;
      if (!response) {
        throw new Error("No response from OpenRouter");
      }

      // Parse the JSON response
      const result = this.parseResponse(response);

      console.log(`✅ [OpenRouter] Generated ${result.files.length} files`);
      console.log(
        `🔧 [OpenRouter] Tokens used: ${
          completion.usage?.total_tokens || "unknown"
        }`
      );

      return result;
    } catch (error) {
      console.error(`❌ [OpenRouter] Error:`, error);
      throw new Error(
        `Code generation failed: ${
          error instanceof Error ? error.message : "Unknown error"
        }`
      );
    }
  }

  private buildPrompt(request: GenerateProjectRequest): string {
    const { projectName, description, framework, features, styling, isUpdate } =
      request;

    const action = isUpdate
      ? "Update the existing"
      : "Generate a complete, production-ready";
    const updateContext = isUpdate
      ? `\n\nThis is an UPDATE to an existing project. Modify the code based on this new requirement: ${description}`
      : "";

    return `${action} ${framework} project: ${description}${updateContext}

Project Requirements:
- Name: ${projectName}
- Framework: ${framework}
- Features: ${features.join(", ")}
- Styling: ${styling}
- Use TypeScript and modern React patterns
- Include proper error handling and loading states
- Make it production-ready with proper SEO and accessibility

Generate these essential files:
1. package.json - with all necessary dependencies
2. src/app/page.tsx - main page component
3. src/app/layout.tsx - root layout with metadata
4. src/app/globals.css - global styles with Tailwind
5. README.md - comprehensive setup and deployment guide
6. next.config.js - Next.js configuration
7. tailwind.config.js - Tailwind configuration
8. tsconfig.json - TypeScript configuration

Return your response as a JSON object with this EXACT structure:
{
  "files": [
    {"path": "package.json", "content": "..."},
    {"path": "src/app/page.tsx", "content": "..."},
    {"path": "src/app/layout.tsx", "content": "..."},
    {"path": "src/app/globals.css", "content": "..."},
    {"path": "README.md", "content": "..."},
    {"path": "next.config.js", "content": "..."},
    {"path": "tailwind.config.js", "content": "..."},
    {"path": "tsconfig.json", "content": "..."}
  ],
  "instructions": "Run: npm install && npm run dev",
  "buildCommand": "npm run build",
  "startCommand": "npm run dev"
}

Make the code functional, complete, and follow Next.js 15 best practices. Ensure all JSON is properly escaped.`;
  }

  private parseResponse(response: string): GenerateProjectResponse {
    try {
      // Find JSON in the response (AI might add explanatory text)
      const startIdx = response.indexOf("{");
      const endIdx = response.lastIndexOf("}") + 1;

      if (startIdx === -1 || endIdx <= startIdx) {
        throw new Error("No valid JSON found in response");
      }

      const jsonStr = response.substring(startIdx, endIdx);
      const parsed = JSON.parse(jsonStr);

      // Validate the structure
      if (!parsed.files || !Array.isArray(parsed.files)) {
        throw new Error("Invalid response structure: missing files array");
      }

      // Ensure required fields
      return {
        files: parsed.files,
        instructions: parsed.instructions || "Run: npm install && npm run dev",
        buildCommand: parsed.buildCommand || "npm run build",
        startCommand: parsed.startCommand || "npm run dev",
        dependencies: parsed.dependencies,
        devDependencies: parsed.devDependencies,
      };
    } catch (error) {
      console.error("❌ [OpenRouter] JSON parsing error:", error);
      console.error("Raw response:", response.substring(0, 500) + "...");

      // Return fallback structure
      return this.createFallbackProject(response);
    }
  }

  private createFallbackProject(
    originalResponse: string
  ): GenerateProjectResponse {
    console.log("⚠️ [OpenRouter] Using fallback project structure");

    return {
      files: [
        {
          path: "package.json",
          content: JSON.stringify(
            {
              name: "ai-generated-project",
              version: "0.1.0",
              private: true,
              scripts: {
                dev: "next dev",
                build: "next build",
                start: "next start",
                lint: "next lint",
              },
              dependencies: {
                next: "15.0.0",
                react: "^18.2.0",
                "react-dom": "^18.2.0",
              },
              devDependencies: {
                "@types/node": "^20.0.0",
                "@types/react": "^18.2.0",
                "@types/react-dom": "^18.2.0",
                typescript: "^5.0.0",
                tailwindcss: "^3.4.0",
                autoprefixer: "^10.4.0",
                postcss: "^8.4.0",
              },
            },
            null,
            2
          ),
        },
        {
          path: "src/app/page.tsx",
          content: `export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-between p-24">
      <div className="z-10 max-w-5xl w-full items-center justify-between font-mono text-sm">
        <h1 className="text-4xl font-bold">AI Generated Project</h1>
        <p className="mt-4">This project was generated by AI.</p>
      </div>
    </main>
  );
}`,
        },
        {
          path: "src/app/layout.tsx",
          content: `import type { Metadata } from 'next'
import './globals.css'

export const metadata: Metadata = {
  title: 'AI Generated App',
  description: 'Generated by AI',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}`,
        },
        {
          path: "src/app/globals.css",
          content: `@tailwind base;
@tailwind components;
@tailwind utilities;`,
        },
        {
          path: "README.md",
          content: `# AI Generated Project

This project was generated by AI using OpenRouter.

## Getting Started

\`\`\`bash
npm install
npm run dev
\`\`\`

Open [http://localhost:3000](http://localhost:3000) with your browser.`,
        },
      ],
      instructions: "Run: npm install && npm run dev",
      buildCommand: "npm run build",
      startCommand: "npm run dev",
    };
  }
}
