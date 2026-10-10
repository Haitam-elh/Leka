# The nightly backup (LEKA-408): the API's own image — leka.ops.backup, its
# settings, its Python — with the PostgreSQL client tools of the server's
# major version. Debian's may be older, and pg_dump refuses a newer server; these
# come from PostgreSQL's own repository. Built on the box, from the image
# running there:
#
#   docker build -f backup.Dockerfile --build-arg API_IMAGE=ghcr.io/<owner>/leka/api:<sha> \
#     -t leka-backup .
#
# PG_MAJOR must be RDS's major version (`SELECT version()`).
ARG API_IMAGE
FROM ${API_IMAGE}

ARG PG_MAJOR=16
USER root
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
       https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install --no-install-recommends -y "postgresql-client-${PG_MAJOR}" \
    && rm -rf /var/lib/apt/lists/*
USER leka
