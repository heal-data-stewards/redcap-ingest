# Devcontainer base with non-root "vscode" user baked in
FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# OS packages that make pip installs smoother (numpy/pandas wheels usually
# work, but this keeps you safe when a source build is needed)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    build-essential curl git ca-certificates \
    locales tzdata \
    && rm -rf /var/lib/apt/lists/*

# UTF-8 locale (useful for spreadsheet + LLM text handling)
RUN sed -i 's/# en_US.UTF-8/en_US.UTF-8/' /etc/locale.gen && locale-gen
ENV LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8

# Set workdir to what VS Code expects
WORKDIR /workspaces/redcap-ingest

# (Optional) Pre-cache wheels when building the image if you want reproducible
# image builds. Commented out because the repo isn’t copied at build time by default.
# COPY requirements.txt .
# RUN pip install -U pip && pip install -r requirements.txt
