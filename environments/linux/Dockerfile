FROM eclipse-temurin:8-jdk-jammy
ARG DEBIAN_FRONTEND=noninteractive
ARG PIP_INDEX_URL=https://pypi.org/simple
ENV MCBENCH_ROOT=/workspace/mc-bench
ENV VENV=/opt/mcbench-venv
ENV JAVA_HOME=/opt/java/openjdk
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PATH="${VENV}/bin:${JAVA_HOME}/bin:${PATH}"
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash build-essential ca-certificates curl ffmpeg git \
    libasound2 libfontconfig1 libfreetype6 libgl1 libgl1-mesa-dri libglu1-mesa \
    libx11-6 libxcursor1 libxext6 libxinerama1 libxi6 libxrandr2 libxrender1 \
    libxtst6 libxxf86vm1 mesa-utils python3.10 python3.10-dev python3.10-venv \
    unzip wget x11-xserver-utils xauth xvfb \
    && rm -rf /var/lib/apt/lists/*
WORKDIR ${MCBENCH_ROOT}
COPY . .
RUN python3.10 -m venv "${VENV}" \
    && python -m pip install 'setuptools==65.5.0' 'wheel==0.38.4' \
    && python -m pip install --no-build-isolation -e . \
    && python -m pip install -r environments/linux/requirements.txt \
    && python -m scripts.linux.fetch_runtime /opt/minerl-source \
    && python -m pip install --no-deps --no-build-isolation /opt/minerl-source \
    && python -m scripts.linux.patch_runtime "${VENV}/lib/python3.10/site-packages/minerl/MCP-Reborn" \
    && cd "${VENV}/lib/python3.10/site-packages/minerl/MCP-Reborn" \
    && ./gradlew --no-daemon compileJava
ENTRYPOINT ["/workspace/mc-bench/environments/linux/entrypoint.sh"]
CMD ["python", "-m", "mcbench.cli", "doctor"]
