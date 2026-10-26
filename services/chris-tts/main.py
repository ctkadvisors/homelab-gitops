"""
Chris Voice TTS Service
FastAPI service for text-to-speech using Qwen3-TTS with Chris's voice clone.
"""
import io
import os
import time
import logging
from typing import Optional
from contextlib import asynccontextmanager

import torch
import numpy as np
import soundfile as sf
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global model reference
model = None
reference_audio = None
reference_sr = None


class TTSRequest(BaseModel):
    """Request model for TTS generation."""
    text: str = Field(..., min_length=1, max_length=2000, description="Text to synthesize")
    format: str = Field(default="ogg", description="Output format: ogg, wav, or mp3")
    

class TTSResponse(BaseModel):
    """Response model for TTS metadata."""
    duration_seconds: float
    format: str
    sample_rate: int


def load_model():
    """Load the Qwen3-TTS model."""
    global model
    
    from qwen_tts import Qwen3TTSModel
    
    model_path = os.environ.get("MODEL_PATH", "/models/1.7B-Base")
    logger.info(f"Loading model from {model_path}...")
    
    model = Qwen3TTSModel.from_pretrained(
        model_path,
        device_map="cuda:0",
        dtype=torch.float16,
    )
    
    logger.info(f"Model loaded! GPU memory: {torch.cuda.memory_allocated()/1024**3:.2f} GB")
    return model


def load_reference_audio():
    """Load Chris's voice reference audio."""
    global reference_audio, reference_sr
    
    ref_path = os.environ.get("REFERENCE_AUDIO", "/reference/chris_voice.wav")
    logger.info(f"Loading reference audio from {ref_path}...")
    
    audio, sr = sf.read(ref_path)
    # Normalize audio
    reference_audio = audio / (np.abs(audio).max() + 1e-6) * 0.95
    reference_sr = sr
    
    logger.info(f"Reference audio loaded: {len(audio)/sr:.2f} seconds at {sr}Hz")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup
    logger.info("Starting Chris Voice TTS Service...")
    load_model()
    load_reference_audio()
    logger.info("Service ready!")
    yield
    # Shutdown
    logger.info("Shutting down...")


app = FastAPI(
    title="Chris Voice TTS",
    description="Text-to-speech service using Qwen3-TTS with Chris's voice clone",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "model_loaded": model is not None,
        "reference_loaded": reference_audio is not None,
        "gpu_memory_gb": torch.cuda.memory_allocated()/1024**3 if torch.cuda.is_available() else 0,
    }


@app.get("/")
async def root():
    """Root endpoint with service info."""
    return {
        "service": "Chris Voice TTS",
        "version": "1.0.0",
        "endpoints": {
            "POST /synthesize": "Generate speech from text",
            "GET /health": "Health check",
        }
    }


@app.post("/synthesize")
async def synthesize(request: TTSRequest):
    """
    Synthesize speech from text using Chris's voice.
    
    Returns audio file in requested format (ogg, wav, or mp3).
    """
    if model is None:
        raise HTTPException(status_code=503, detail="Model not loaded")
    
    if reference_audio is None:
        raise HTTPException(status_code=503, detail="Reference audio not loaded")
    
    start_time = time.time()
    logger.info(f"Generating speech for: {request.text[:50]}...")
    
    try:
        # Generate audio
        wavs, sr_out = model.generate_voice_clone(
            text=request.text,
            language="English",
            ref_audio=(reference_audio, reference_sr),
            ref_text="",
            x_vector_only_mode=True,
        )
        
        audio_data = wavs[0]
        duration = len(audio_data) / sr_out
        
        logger.info(f"Generated {duration:.2f}s audio in {time.time() - start_time:.2f}s")
        
        # Convert to requested format
        buffer = io.BytesIO()
        
        if request.format == "wav":
            sf.write(buffer, audio_data, sr_out, format="WAV")
            media_type = "audio/wav"
            filename = "speech.wav"
        elif request.format == "ogg":
            sf.write(buffer, audio_data, sr_out, format="OGG", subtype="OPUS")
            media_type = "audio/ogg"
            filename = "speech.ogg"
        else:
            # Default to OGG for WhatsApp compatibility
            sf.write(buffer, audio_data, sr_out, format="OGG", subtype="OPUS")
            media_type = "audio/ogg"
            filename = "speech.ogg"
        
        buffer.seek(0)
        
        return StreamingResponse(
            buffer,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Audio-Duration": str(duration),
                "X-Sample-Rate": str(sr_out),
            }
        )
        
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
