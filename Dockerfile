FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir . \
    && groupadd --system fdp \
    && useradd --system --gid fdp --create-home fdp

RUN mkdir -p /work/output && chown -R fdp:fdp /work
USER fdp
WORKDIR /work

VOLUME ["/work/output"]
ENTRYPOINT ["fdp"]
CMD ["run-all", "--source", "synthetic", "--seed", "20270916", "--rows", "1000", "--output-dir", "/work/output"]
