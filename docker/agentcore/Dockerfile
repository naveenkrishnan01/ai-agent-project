# Multi-stage build: pull the JRE + server jar from agentspan's official
# image, then layer the Python agent app on top. AgentCore Runtime requires
# linux/arm64 — build with: docker buildx build --platform linux/arm64

# Confirmed: the jar lives at /app/*.jar in this image.
FROM --platform=linux/arm64 agentspan/server:latest AS agentspan-server

# The agentspan server jar is compiled for Java 21 (class file version 65).
# Debian bookworm's apt repos only carry OpenJDK 17 (verified: `apt-cache
# search openjdk` lists only openjdk-17-*), which fails at startup with
# UnsupportedClassVersionError. Pull a real JDK 21 from Temurin instead of
# apt-installing one.
FROM --platform=linux/arm64 eclipse-temurin:21-jre AS jre

FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=jre /opt/java/openjdk /opt/java/openjdk
ENV PATH="/opt/java/openjdk/bin:$PATH"

COPY --from=agentspan-server /app/*.jar /opt/agentspan/agentspan-runtime.jar

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY agent/agentcore_app.py agent/agentcore_app.py
COPY docker/agentcore/entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080

ENTRYPOINT ["./entrypoint.sh"]
