# Wuji Quartet: simulation, optimisation and hand control in one image.
# Builds unchanged for linux/amd64 (PCs) and linux/arm64 (D-Robotics RDK X5, Jetson, Docker on Apple-silicon Macs).
FROM python:3.13-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MUJOCO_GL=osmesa \
    PYOPENGL_PLATFORM=osmesa \
    WUJI_TELEMETRY_DISABLE=1 \
    HOME=/home/wq

# libosmesa6 + libgl1: software rendering for the videos (no GPU needed)   ffmpeg: video + audio encoding
# libudev1: Wuji SDK device discovery   iproute2 / iputils-ping / alsa-utils: network and MIDI checks on the robot computer
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libosmesa6 libgl1 libegl1 libglfw3 libudev1 \
        ffmpeg fonts-dejavu-core \
        iproute2 iputils-ping alsa-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# any host user id may run the container (./wq passes -u uid:gid so files in out/ stay yours)
RUN mkdir -p /home/wq/.wuji /work && chmod -R 1777 /home/wq
WORKDIR /work
CMD ["bash"]
