# syntax=docker/dockerfile:1.7
#
# CARO's one image for the API and the workers (docs/REARCHITECTURE.md,
# phase 1), a role per command (webapp/role.py):
#
#   docker run <image>                         serves the API on :8000
#   docker run <image> catalog-load --verify   checks the catalog
#   docker run <image> worker                  the collection's daily runs
#   docker run <image> alerts                  the collection's alerts
#
# Every setting comes from the environment; nothing secret is built in. The
# corpora the API serves are the published ones, data/corpora/, copied as
# they are; nothing a collection writes (data/snapshots/) is in the context
# (.dockerignore).
FROM python:3.12-slim-bookworm AS api

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# The API's dependencies and numpy, the core's one. extra_ca is an optional
# certificate for a build behind a proxy that re-signs TLS; a build without
# it reads none.
COPY webapp/requirements.txt webapp/requirements.txt
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install numpy -r webapp/requirements.txt

COPY pyproject.toml ./
COPY caro/ caro/
COPY webapp/__init__.py webapp/role.py webapp/worker.py webapp/alerts.py webapp/
COPY webapp/api/ webapp/api/
COPY scripts/__init__.py scripts/catalog_load.py scripts/first_run.py scripts/edge_purge.py scripts/d56_measure.py scripts/
COPY data/corpora/ data/corpora/

# The commit the image was built from; /api/health says it.
ARG CARO_BUILD=
ENV CARO_BUILD=${CARO_BUILD}

# A user of its own, with nothing to write but the inbox where it is on, the
# worker's snapshots and transcripts, and the edge purge's last key.
RUN useradd --system --uid 10001 --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin caro \
 && mkdir -p data/inbox data/snapshots data/transcripts /var/lib/caro-purge \
 && chown caro data/inbox data/snapshots data/transcripts /var/lib/caro-purge
USER caro

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-m", "webapp.role", "healthcheck"]
ENTRYPOINT ["python", "-m", "webapp.role"]
CMD ["api"]

# The suites that speak for this image, run inside its environment: the
# contract suite (every endpoint, in every corpus state, against the site's
# types), the catalog, the seller store and the collection.
# `docker build --target test .` fails when one of them does; nothing of
# this stage is in the image the API runs, which is the stage above.
FROM api AS test
USER root
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install "httpx>=0.27,<1"
COPY --chown=caro . /src
WORKDIR /src
USER caro
RUN python tests/run_all.py contract && python tests/run_all.py catalog && python tests/run_all.py store \
 && python tests/run_all.py collection

# The image the API runs, named last so that a build with no target is it.
FROM api
