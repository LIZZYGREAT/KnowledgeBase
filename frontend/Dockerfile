FROM node:24-alpine AS build

ARG NPM_REGISTRY=https://registry.npmjs.org

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./

RUN npm config set registry "$NPM_REGISTRY" \
    && npm ci

COPY frontend/index.html frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/src ./src

RUN npm run build

COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
