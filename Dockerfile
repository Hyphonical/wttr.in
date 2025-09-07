# Minimal “self-contained” builder that does NOT require local source except this Dockerfile
FROM alpine:3.21.1 AS base
RUN apk add --no-cache git python3 py3-pip py3-gevent py3-wheel py3-scipy py3-numpy-dev python3-dev build-base jpeg-dev zlib-dev llvm17 llvm17-dev llvm17-static libtool supervisor autoconf automake pkgconfig jq-dev oniguruma-dev m4

WORKDIR /app
# Fetch source (shallow clone)
ARG WTTR_REPO=https://github.com/chubin/wttr.in.git
ARG WTTR_REF=master
RUN git clone --depth 1 --branch "$WTTR_REF" "$WTTR_REPO" src && \
    cp -r src/bin src/lib src/share ./ && \
    cp src/requirements.txt ./ && \
    rm -rf src/.git

# Create virtual environment and install Python deps
RUN ln -sf /usr/lib/llvm17/bin/llvm-config /usr/bin/llvm-config || true
RUN python3 -m venv /app/venv
ENV LLVM_CONFIG=/usr/bin/llvm-config
RUN export PATH=$PATH:/usr/lib/llvm17/bin && /app/venv/bin/pip install --no-cache-dir -r requirements.txt && \
    apk del build-base llvm17-dev llvm17-static python3-dev autoconf automake pkgconfig jq-dev m4

# Build wego substitute (Go part) from included share/we-lang (if still needed)
FROM golang:1-alpine AS gobuild
WORKDIR /goapp
COPY --from=base /app/share/we-lang/ /goapp/
RUN apk add --no-cache git && CGO_ENABLED=0 go build -o wttr.in .

FROM base AS runtime
# Copy compiled Go binary (acts as WTTR_WEGO helper)
COPY --from=gobuild /goapp/wttr.in /app/bin/wttr.in

# Create needed dirs
RUN mkdir -p /app/cache /var/log/supervisor /etc/supervisor/conf.d && \
    chmod -R o+rw /var/log/supervisor /var/run

# Supervisor config (already in repo if fetched; fallback simple)
RUN printf '[supervisord]\nnodaemon=true\n[program:wttr]\ncommand=/app/venv/bin/python3 /app/bin/srv.py\n' > /etc/supervisor/supervisord.conf

ENV WTTR_MYDIR=/app \
    WTTR_GEOLITE=/app/GeoLite2-City.mmdb \
    WTTR_WEGO=/app/bin/wttr.in \
    WTTR_LISTEN_HOST=0.0.0.0 \
    WTTR_LISTEN_PORT=8002

EXPOSE 8002
VOLUME ["/app/cache"]
# GeoLite2-City.mmdb will be mounted at runtime
CMD ["/usr/bin/supervisord","-c","/etc/supervisor/supervisord.conf"]