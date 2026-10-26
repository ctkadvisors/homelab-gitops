const express = require('express');
const { exec, spawn } = require('child_process');
const { promisify } = require('util');
const fs = require('fs').promises;
const path = require('path');
const os = require('os');

const execAsync = promisify(exec);
const app = express();
app.use(express.json());

const MODELS_PATH = process.env.MODELS_PATH || '/models';
const LOCALAI_URL = process.env.LOCALAI_URL || 'http://localhost:8080';
const NODE_NAME = process.env.NODE_NAME || os.hostname();

// Curated list of recommended GGUF models (fallback if HF API fails)
const CURATED_MODELS = [
  { id: 'tinyllama-1.1b', name: 'TinyLlama 1.1B', size: '637MB', sizeBytes: 637000000, layers: 22,
    url: 'https://huggingface.co/TheBloke/TinyLlama-1.1B-Chat-v1.0-GGUF/resolve/main/tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf',
    filename: 'tinyllama-1.1b-chat-v1.0.Q4_K_M.gguf', description: 'Tiny but capable chat model' },
  { id: 'phi-2', name: 'Phi-2 2.7B', size: '1.6GB', sizeBytes: 1600000000, layers: 32,
    url: 'https://huggingface.co/TheBloke/phi-2-GGUF/resolve/main/phi-2.Q4_K_M.gguf',
    filename: 'phi-2.Q4_K_M.gguf', description: 'Microsoft small but powerful model' },
  { id: 'mistral-7b', name: 'Mistral 7B Instruct', size: '4.1GB', sizeBytes: 4100000000, layers: 32,
    url: 'https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF/resolve/main/mistral-7b-instruct-v0.2.Q4_K_M.gguf',
    filename: 'mistral-7b-instruct-v0.2.Q4_K_M.gguf', description: 'High quality instruction-following' },
  { id: 'codellama-7b', name: 'CodeLlama 7B', size: '4.1GB', sizeBytes: 4100000000, layers: 32,
    url: 'https://huggingface.co/TheBloke/CodeLlama-7B-Instruct-GGUF/resolve/main/codellama-7b-instruct.Q4_K_M.gguf',
    filename: 'codellama-7b-instruct.Q4_K_M.gguf', description: 'Specialized for code generation' },
  { id: 'llama3.2-3b', name: 'Llama 3.2 3B', size: '2.0GB', sizeBytes: 2000000000, layers: 28,
    url: 'https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf',
    filename: 'Llama-3.2-3B-Instruct-Q4_K_M.gguf', description: 'Latest Llama, small and fast' },
  { id: 'qwen2.5-3b', name: 'Qwen 2.5 3B', size: '2.1GB', sizeBytes: 2100000000, layers: 28,
    url: 'https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf',
    filename: 'qwen2.5-3b-instruct-q4_k_m.gguf', description: 'Alibaba Qwen 2.5, excellent multilingual' },
  { id: 'deepseek-coder-1.3b', name: 'DeepSeek Coder 1.3B', size: '800MB', sizeBytes: 800000000, layers: 24,
    url: 'https://huggingface.co/TheBloke/deepseek-coder-1.3b-instruct-GGUF/resolve/main/deepseek-coder-1.3b-instruct.Q4_K_M.gguf',
    filename: 'deepseek-coder-1.3b-instruct.Q4_K_M.gguf', description: 'Compact code model' },
];

// Track downloads in progress with detailed status
const downloads = {};

// Cache for HuggingFace search results
let hfSearchCache = { data: null, timestamp: 0 };
const CACHE_TTL = 5 * 60 * 1000; // 5 minutes

// Health check
app.get('/health', (req, res) => res.json({ status: 'ok', node: NODE_NAME }));

// Get node status
app.get('/status', async (req, res) => {
  try {
    const [memInfo, gpuLoad, diskInfo, nvidiaSmi] = await Promise.all([
      execAsync("free -m | grep Mem | awk '{print $3\"/\"$2\"MB\"}'").catch(() => ({ stdout: 'N/A' })),
      fs.readFile('/sys/devices/gpu.0/load', 'utf8').catch(() => '0'),
      execAsync(`df -h ${MODELS_PATH} | tail -1 | awk '{print $4\" free of \"$2}'`).catch(() => ({ stdout: 'N/A' })),
      execAsync('nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader 2>/dev/null || tegrastats --interval 100 --count 1 2>/dev/null || echo "N/A"').catch(() => ({ stdout: 'N/A' })),
    ]);

    // Check LocalAI health
    let localaiStatus = 'unknown';
    try {
      const resp = await fetch(`${LOCALAI_URL}/readyz`, { timeout: 2000 });
      localaiStatus = resp.ok ? 'healthy' : 'unhealthy';
    } catch { localaiStatus = 'unavailable'; }

    res.json({
      node: NODE_NAME,
      memory: memInfo.stdout?.trim() || 'N/A',
      gpuLoad: (parseInt(gpuLoad) / 10).toFixed(1) + '%',
      disk: diskInfo.stdout?.trim() || 'N/A',
      gpu: nvidiaSmi.stdout?.trim() || 'N/A',
      localaiStatus,
      modelsPath: MODELS_PATH,
    });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// List installed models
app.get('/models', async (req, res) => {
  try {
    const files = await fs.readdir(MODELS_PATH);
    const models = [];
    for (const file of files) {
      if (file.endsWith('.gguf')) {
        const stat = await fs.stat(path.join(MODELS_PATH, file));
        models.push({ filename: file, size: (stat.size / 1e9).toFixed(2) + 'GB' });
      }
    }
    const configs = files.filter(f => f.endsWith('.yaml'));
    res.json({ models, configs, node: NODE_NAME });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Get curated available models for download
app.get('/models/available', (req, res) => res.json(CURATED_MODELS));

// Search HuggingFace for GGUF models
app.get('/models/search', async (req, res) => {
  try {
    const query = req.query.q || 'gguf';
    const limit = Math.min(parseInt(req.query.limit) || 20, 50);

    // Use cache if fresh
    const cacheKey = `${query}-${limit}`;
    if (hfSearchCache.data && hfSearchCache.key === cacheKey &&
        Date.now() - hfSearchCache.timestamp < CACHE_TTL) {
      return res.json({ cached: true, models: hfSearchCache.data });
    }

    // Search HuggingFace API for GGUF models
    const hfUrl = `https://huggingface.co/api/models?search=${encodeURIComponent(query + ' gguf')}&filter=gguf&sort=downloads&direction=-1&limit=${limit}`;
    const response = await fetch(hfUrl);
    if (!response.ok) throw new Error('HuggingFace API error');

    const repos = await response.json();
    const models = [];

    for (const repo of repos.slice(0, 10)) { // Limit to 10 for performance
      try {
        // Fetch repo files to find Q4_K_M GGUF files
        const filesUrl = `https://huggingface.co/api/models/${repo.id}/tree/main`;
        const filesResp = await fetch(filesUrl);
        if (!filesResp.ok) continue;

        const files = await filesResp.json();
        const ggufFiles = files.filter(f =>
          f.path.endsWith('.gguf') &&
          (f.path.includes('Q4_K_M') || f.path.includes('q4_k_m'))
        );

        for (const file of ggufFiles.slice(0, 2)) { // Max 2 files per repo
          const sizeGB = (file.size / 1e9).toFixed(2);
          models.push({
            id: `${repo.id.replace('/', '-')}-${file.path.replace('.gguf', '')}`,
            name: repo.id.split('/').pop() + ' (' + file.path.split('/').pop().replace('.gguf', '') + ')',
            size: `${sizeGB}GB`,
            sizeBytes: file.size,
            layers: 32, // Default, user can adjust
            url: `https://huggingface.co/${repo.id}/resolve/main/${file.path}`,
            filename: file.path.split('/').pop(),
            description: repo.id,
            downloads: repo.downloads || 0,
            likes: repo.likes || 0,
          });
        }
      } catch (e) { /* skip problematic repos */ }
    }

    // Cache results
    hfSearchCache = { data: models, key: cacheKey, timestamp: Date.now() };
    res.json({ cached: false, models });
  } catch (e) {
    console.error('HuggingFace search error:', e);
    // Fall back to curated list
    res.json({ cached: false, fallback: true, models: CURATED_MODELS });
  }
});

// Get all active downloads
app.get('/models/downloads', (req, res) => {
  res.json(downloads);
});

// Download a model (supports both curated and custom URLs)
app.post('/models/download', async (req, res) => {
  const { modelId, url, filename, sizeBytes } = req.body;

  // Find model from curated list or use custom URL
  let model = CURATED_MODELS.find(m => m.id === modelId);
  if (!model && url && filename) {
    // Custom model from HuggingFace search
    model = { id: modelId, url, filename, sizeBytes: sizeBytes || 0 };
  }
  if (!model) return res.status(400).json({ error: 'Unknown model and no URL provided' });

  const downloadKey = modelId || filename;
  if (downloads[downloadKey]) {
    return res.json({ status: 'already_downloading', ...downloads[downloadKey] });
  }

  const dest = path.join(MODELS_PATH, model.filename);
  const expectedSize = model.sizeBytes || 0;

  downloads[downloadKey] = {
    status: 'downloading',
    progress: 0,
    started: Date.now(),
    filename: model.filename,
    expectedSize,
    currentSize: 0,
  };

  // Spawn curl in background with progress
  const curl = spawn('curl', ['-L', '-o', dest, '--progress-bar', model.url], {
    detached: true,
    stdio: ['ignore', 'ignore', 'ignore']
  });
  curl.unref();

  // Track file size for progress (more frequent updates)
  const checkProgress = setInterval(async () => {
    try {
      const stat = await fs.stat(dest);
      downloads[downloadKey].currentSize = stat.size;
      if (expectedSize > 0) {
        downloads[downloadKey].progress = Math.min(99, Math.round((stat.size / expectedSize) * 100));
      } else {
        // No expected size, just show we're downloading
        downloads[downloadKey].progress = -1; // Indeterminate
      }
    } catch {}
  }, 2000); // Check every 2 seconds

  curl.on('close', (code) => {
    clearInterval(checkProgress);
    if (code === 0) {
      downloads[downloadKey] = {
        status: 'complete',
        progress: 100,
        filename: model.filename,
        completed: Date.now(),
      };
    } else {
      downloads[downloadKey] = {
        status: 'failed',
        error: `curl exited with code ${code}`,
        filename: model.filename,
      };
    }
    // Keep status for 5 minutes so UI can show completion
    setTimeout(() => delete downloads[downloadKey], 5 * 60 * 1000);
  });

  res.json({ status: 'started', modelId: downloadKey, filename: model.filename });
});

// Get download status for specific model
app.get('/models/download/:modelId', (req, res) => {
  const status = downloads[req.params.modelId] || { status: 'not_found' };
  res.json(status);
});

// Create model config (supports curated and custom models)
app.post('/models/config', async (req, res) => {
  try {
    const { modelId, filename, name, contextSize = 2048, gpuLayers = 32, temperature = 0.7 } = req.body;

    // Find model from curated list or use provided filename
    const model = CURATED_MODELS.find(m => m.id === modelId);
    const modelFilename = model?.filename || filename;

    if (!modelFilename) {
      return res.status(400).json({ error: 'No model filename provided' });
    }

    const configName = name || modelId || modelFilename.replace('.gguf', '');
    const config = `name: ${configName}
backend: llama-cpp
parameters:
  model: ${modelFilename}
  temperature: ${temperature}
  context_size: ${contextSize}
gpu_layers: ${gpuLayers}`;

    await fs.writeFile(path.join(MODELS_PATH, `${configName}.yaml`), config);
    res.json({ success: true, config: `${configName}.yaml` });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Delete a model
app.delete('/models/:filename', async (req, res) => {
  try {
    await fs.unlink(path.join(MODELS_PATH, req.params.filename));
    res.json({ success: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Get loaded models from LocalAI
app.get('/localai/models', async (req, res) => {
  try {
    const resp = await fetch(`${LOCALAI_URL}/v1/models`);
    res.json(await resp.json());
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// Load a model into GPU memory (preload via a minimal inference)
app.post('/localai/load', async (req, res) => {
  try {
    const { model } = req.body;
    if (!model) return res.status(400).json({ error: 'Model name required' });

    console.log(`Loading model: ${model}`);
    const startTime = Date.now();

    // Make a minimal inference call to trigger model loading
    const resp = await fetch(`${LOCALAI_URL}/v1/chat/completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model,
        messages: [{ role: 'user', content: 'Hi' }],
        max_tokens: 1
      }),
    });

    const result = await resp.json();
    const loadTime = Date.now() - startTime;

    if (result.error) {
      return res.status(400).json({ success: false, error: result.error });
    }

    res.json({
      success: true,
      model,
      loadTimeMs: loadTime,
      message: `Model ${model} loaded in ${(loadTime / 1000).toFixed(1)}s`
    });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Unload a model from GPU memory
// LocalAI doesn't have a direct unload API, so we:
// 1. Rename/remove the config file temporarily
// 2. Call the backend endpoint to clear the model from memory
// Note: This requires LocalAI to be running with --debug for some endpoints
app.post('/localai/unload', async (req, res) => {
  try {
    const { model } = req.body;
    if (!model) return res.status(400).json({ error: 'Model name required' });

    console.log(`Unloading model: ${model}`);

    // Try LocalAI's internal model unload endpoint (may not be available in all versions)
    try {
      const resp = await fetch(`${LOCALAI_URL}/models/${model}`, {
        method: 'DELETE',
      });
      if (resp.ok) {
        return res.json({ success: true, model, message: `Model ${model} unloaded` });
      }
    } catch (e) {
      // Endpoint might not exist, try alternative
    }

    // Alternative: Temporarily rename the config file to prevent reloading
    const configFile = path.join(MODELS_PATH, `${model}.yaml`);
    const backupFile = path.join(MODELS_PATH, `${model}.yaml.disabled`);

    try {
      await fs.access(configFile);
      await fs.rename(configFile, backupFile);
      res.json({
        success: true,
        model,
        message: `Model ${model} config disabled. Model will be unloaded on next request timeout or restart.`,
        note: 'For immediate unload, restart LocalAI'
      });
    } catch (e) {
      res.json({
        success: false,
        model,
        error: 'Could not find model config to disable',
        note: 'Model may still be in memory until LocalAI is restarted'
      });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Re-enable a disabled model config
app.post('/localai/enable', async (req, res) => {
  try {
    const { model } = req.body;
    if (!model) return res.status(400).json({ error: 'Model name required' });

    const backupFile = path.join(MODELS_PATH, `${model}.yaml.disabled`);
    const configFile = path.join(MODELS_PATH, `${model}.yaml`);

    try {
      await fs.access(backupFile);
      await fs.rename(backupFile, configFile);
      res.json({ success: true, model, message: `Model ${model} config re-enabled` });
    } catch (e) {
      res.status(400).json({ error: `No disabled config found for ${model}` });
    }
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// Get GPU memory status (Jetson-specific)
app.get('/gpu/status', async (req, res) => {
  try {
    // Try tegrastats for Jetson
    const { stdout } = await execAsync('tegrastats --interval 100 --count 1 2>/dev/null || echo "N/A"');

    // Parse tegrastats output for RAM and GPU info
    let gpuInfo = { available: false };
    if (stdout && stdout !== 'N/A\n') {
      // Example: RAM 3456/7620MB (lfb 1x512kB) SWAP 0/3810MB ... GR3D_FREQ 0%
      const ramMatch = stdout.match(/RAM (\d+)\/(\d+)MB/);
      const gr3dMatch = stdout.match(/GR3D_FREQ (\d+)%/);

      gpuInfo = {
        available: true,
        ramUsed: ramMatch ? parseInt(ramMatch[1]) : null,
        ramTotal: ramMatch ? parseInt(ramMatch[2]) : null,
        gpuFreq: gr3dMatch ? parseInt(gr3dMatch[1]) : null,
        raw: stdout.trim(),
      };
    }

    res.json(gpuInfo);
  } catch (e) {
    res.json({ available: false, error: e.message });
  }
});

// Test model inference
app.post('/localai/test', async (req, res) => {
  try {
    const { model, prompt = 'Hello' } = req.body;
    const resp = await fetch(`${LOCALAI_URL}/v1/chat/completions`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model, messages: [{ role: 'user', content: prompt }], max_tokens: 50 }),
    });
    res.json(await resp.json());
  } catch (e) { res.status(500).json({ error: e.message }); }
});

const PORT = process.env.PORT || 3001;
app.listen(PORT, '0.0.0.0', () => console.log(`Model Manager running on port ${PORT} for ${NODE_NAME}`));

