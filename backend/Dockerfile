FROM python:3.12-slim

ARG APT_MIRROR=
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=

RUN if [ -n "$APT_MIRROR" ]; then \
      for source_file in \
        /etc/apt/sources.list.d/debian.sources \
        /etc/apt/sources.list; do \
        if [ -f "$source_file" ]; then \
          sed -i \
            -e "s|https://deb.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|http://deb.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|https://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|http://deb.debian.org/debian|${APT_MIRROR}/debian|g" \
            -e "s|https://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            -e "s|http://security.debian.org/debian-security|${APT_MIRROR}/debian-security|g" \
            "$source_file"; \
        fi; \
      done; \
    fi \
    && apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt

RUN if [ -n "$PIP_TRUSTED_HOST" ]; then \
      pip install --no-cache-dir \
        --index-url "$PIP_INDEX_URL" \
        --trusted-host "$PIP_TRUSTED_HOST" \
        -r requirements.txt; \
    else \
      pip install --no-cache-dir \
        --index-url "$PIP_INDEX_URL" \
        -r requirements.txt; \
    fi
COPY backend/__init__.py ./backend/__init__.py
COPY backend/app ./backend/app
COPY backend/entrypoint.sh ./backend/entrypoint.sh
RUN sed -i 's/\r$//' ./backend/entrypoint.sh \
    && chmod +x ./backend/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
