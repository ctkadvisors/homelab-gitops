# Chris Voice TTS Service
# Extends the working qwen-tts:jetson image
FROM qwen-tts:jetson

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV MODEL_PATH=/models/1.7B-Base
ENV REFERENCE_AUDIO=/reference/chris_voice.wav

# Reset pip index to standard PyPI for additional installs
ENV PIP_INDEX_URL=https://pypi.org/simple

# Install FastAPI dependencies
RUN pip3 install --no-cache-dir \
    fastapi \
    uvicorn[standard]

# Create app directory
WORKDIR /app

# Copy application code
COPY main.py .

# Create mount points for models and reference audio
RUN mkdir -p /models /reference

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the service
CMD ["python3", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
