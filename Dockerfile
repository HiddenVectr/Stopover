FROM python:3.12-slim@sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1 BATON_DATA_DIR=/data
WORKDIR /app
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home baton && mkdir /data && chown baton:baton /data && chmod 700 /data
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "baton", "serve", "--host", "0.0.0.0"]
