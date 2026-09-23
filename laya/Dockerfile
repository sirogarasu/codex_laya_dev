FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/models/huggingface

WORKDIR /app

# Install the CUDA 12.8 build of PyTorch for NVIDIA GPU inference.
RUN python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cu128 torch==2.9.1 \
    && python -m pip install --no-cache-dir \
      laya==0.3.4 \
      "fastapi>=0.115,<1" \
      "uvicorn[standard]>=0.34,<1" \
      httpx

COPY api.py /app/api.py

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
