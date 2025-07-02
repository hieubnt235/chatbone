FROM python:3.12-slim-bookworm
LABEL authors="hieu"

WORKDIR /auth_app

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY src/auth ./src/auth
COPY src/utilities ./src/utilities
COPY src/auth/requirements.txt ./


RUN uv init --python 3.12 --build-backend setuptools

RUN uv add -r requirements.txt
RUN uv pip install .

#COPY deployments/auth/serve.yaml ./


#CMD ["uv","run", "serve", "run", "serve.yaml"]

# docker build -f deployments/auth/auth.Dockerfile -t auth-app .