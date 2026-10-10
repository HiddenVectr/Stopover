FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 STOPOVER_DATA_DIR=/data
WORKDIR /app
LABEL org.opencontainers.image.title="Stopover" \
      org.opencontainers.image.description="A shared MCP inbox for handing work and memory between AI agents" \
      org.opencontainers.image.source="https://github.com/HiddenVectr/Stopover" \
      org.opencontainers.image.licenses="Apache-2.0"
# LICENSE and README.md are package inputs (license-files, readme) and are shipped in the image.
COPY --chmod=644 requirements.lock pyproject.toml LICENSE README.md ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home stopover && mkdir /data && chown stopover:stopover /data && chmod 700 /data
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "stopover", "serve", "--host", "0.0.0.0"]
