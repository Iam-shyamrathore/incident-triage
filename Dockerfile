FROM ghcr.io/astral-sh/uv:0.12.2 AS uv
FROM ghcr.io/hydra-db/hydradb@sha256:ab71d651fefee13ebb23eb56d72316065bdca563ff7587442e07be663f2bf880

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -o 10001 -g 10001 /app /data/graph
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY --chown=10001:10001 pyproject.toml uv.lock ./
USER 10001:10001
ENV UV_NO_CACHE=1 UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
RUN uv sync --locked --no-dev --no-install-project --python /usr/bin/python3
COPY --chown=10001:10001 triage/ triage/
COPY --chown=10001:10001 data/ data/
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8080
ENTRYPOINT []
CMD ["python", "-m", "triage.serve"]
