FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/__init__.py ./backend/__init__.py
COPY backend/app ./backend/app
COPY backend/entrypoint.sh ./backend/entrypoint.sh
RUN sed -i 's/\r$//' ./backend/entrypoint.sh \
    && chmod +x ./backend/entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
