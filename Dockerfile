# Badminton CV pipeline — reproducible Linux environment for the Python chain
# (fetch / detect / shuttle / hits / pipeline / export + the badminton.doubles modules).
#
# ── IMPORTANT: no Apple MPS inside Docker ────────────────────────────────────────
# Containers can't reach the Mac's MPS GPU (Docker runs a Linux VM), so torch here is
# CPU-only by default. The CV commands default to `--device mps`; pass `--device cpu`
# in the container. CPU is fine for export/analytics/doubles role checks, but a full
# detect/shuttle parse of a 90-min match on CPU is slow — do heavy parses on the host
# (MPS) or on a CUDA box (see the CUDA note below) and just mount the resulting DB.
#
# ── What's NOT baked in (mount at runtime; see .dockerignore) ─────────────────────
#   data/   videos + DuckDB        -v "$PWD/data:/app/data"
#   config/ matches.yaml           -v "$PWD/config:/app/config"   (also COPYed for standalone use)
#   *.pt    YOLO weights           auto-download on first use, or mount them
#   third_party/TrackNetV3/ckpts   only needed for shuttle tracking (clone + gdown separately)
#
# Build:  docker build -t badminton .
# Shell:  docker run --rm -it -v "$PWD/data:/app/data" -v "$PWD/config:/app/config" badminton
# One-off: docker run --rm -v "$PWD/data:/app/data" -v "$PWD/config:/app/config" badminton \
#            python -m badminton.doubles.roles wtf_2024_md_sf

FROM python:3.12-slim

# ffmpeg: fetch_video / clip cutting. libgl1 + libglib2.0-0: opencv-python runtime.
# git: vendored TrackNetV3. build-essential: safety net for any sdist (trim if unneeded).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git libgl1 libglib2.0-0 build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU torch first, pinned to the CPU wheel index, so ultralytics doesn't drag in a
# multi-GB CUDA build. CUDA hosts: delete this line, base off an nvidia/cuda image,
# install a cuda torch wheel, run with `--gpus all`, and pass `--device cuda`.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Source + config only. Data, weights and the web app stay out (volumes / separate build).
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY schema/ ./schema/
COPY config/ ./config/

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1

CMD ["bash"]
