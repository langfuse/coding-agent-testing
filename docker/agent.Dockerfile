FROM python:3.11-slim

ARG CLAUDE_PLUGIN_REV
ARG CODEX_PLUGIN_REV

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
RUN npm install -g @anthropic-ai/claude-code @openai/codex

RUN pip install --no-cache-dir \
    "langfuse>=4.0,<5" \
    "flask>=3.0" \
    "fastapi>=0.110" \
    "uvicorn>=0.29" \
    "openai>=1.40" \
    "langchain>=0.3" \
    "langchain-core>=0.3" \
    "langchain-openai>=0.2" \
    "langsmith>=0.1.80" \
    "pytest>=8"

RUN git clone https://github.com/langfuse/Claude-Observability-Plugin \
        /opt/claude-langfuse-plugin \
    && git -C /opt/claude-langfuse-plugin checkout "$CLAUDE_PLUGIN_REV"

RUN mkdir -p /root/.claude /root/.codex /root/.agents/skills
COPY docker/claude-settings.json /root/.claude/settings.json
COPY docker/codex-config.toml /root/.codex/config.toml
RUN printf '%s\n' '{"hasCompletedOnboarding": true}' > /root/.claude.json

# marketplace add installs the current plugin. The revision argument is the
# same explicit cache-buster used by the Modal image.
RUN echo "codex plugin rev $CODEX_PLUGIN_REV" \
    && codex plugin marketplace add langfuse/codex-observability-plugin

WORKDIR /workspace
