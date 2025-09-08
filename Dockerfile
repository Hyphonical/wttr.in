# Minimal “self-contained” builder that does NOT require local source except this Dockerfile
FROM python:3.11-alpine AS base
RUN apk add --no-cache git build-base jpeg-dev zlib-dev libtool supervisor autoconf automake pkgconfig jq jq-dev oniguruma-dev m4 py3-scipy py3-numpy-dev

WORKDIR /app
# Fetch source (shallow clone)
ARG WTTR_REPO=https://github.com/chubin/wttr.in.git
ARG WTTR_REF=master
RUN git clone --depth 1 --branch "$WTTR_REF" "$WTTR_REPO" src && \
    cp -r src/bin src/lib src/share ./ && \
    cp src/requirements.txt ./ && \
    rm -rf src/.git

# Remove numba (and implicit llvmlite) as it's unused in codebase to avoid heavy LLVM build
RUN grep -v '^numba$' requirements.txt > requirements.filtered && mv requirements.filtered requirements.txt

# Create virtual environment and install Python deps
RUN python -m venv /app/venv
ENV JQ_INCLUDE_DIR=/usr/include JQ_LIBRARY=/usr/lib
RUN /app/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    apk del build-base autoconf automake pkgconfig jq-dev m4

FROM base AS runtime
# Copy venv and code from build stage
COPY --from=base /app/venv /app/venv
COPY --from=base /app/bin /app/bin
COPY --from=base /app/lib /app/lib
COPY --from=base /app/share /app/share
COPY --from=base /app/requirements.txt /app/requirements.txt

# Create needed dirs
RUN mkdir -p /app/cache /var/log/supervisor /etc/supervisor/conf.d && \
    chmod -R o+rw /var/log/supervisor /var/run

# Supervisor config (already in repo if fetched; fallback simple)
RUN printf '[supervisord]\nnodaemon=true\n[program:wttr]\ncommand=/app/venv/bin/python /app/bin/srv.py\n' > /etc/supervisor/supervisord.conf

ENV WTTR_MYDIR=/app \
    WTTR_GEOLITE=/app/GeoLite2-City.mmdb \
    WTTR_LISTEN_HOST=0.0.0.0 \
    WTTR_LISTEN_PORT=8002 \
    OPENWEATHERMAP_API_KEY=${OPENWEATHERMAP_API_KEY:-} \
    WEATHERAPI_KEY=${WEATHERAPI_KEY:-} \
    ACCUWEATHER_API_KEY=${ACCUWEATHER_API_KEY:-}

EXPOSE 8002
VOLUME ["/app/cache"]
# GeoLite2-City.mmdb will be mounted at runtime
CMD ["/usr/bin/supervisord","-c","/etc/supervisor/supervisord.conf"]