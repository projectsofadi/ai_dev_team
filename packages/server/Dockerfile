FROM node:22-slim AS build

WORKDIR /app/packages/server
COPY packages/server/package.json packages/server/tsconfig.json ./
RUN npm install

COPY packages/server/src ./src
RUN npx tsc

FROM node:22-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 python3-pip python3-venv ripgrep git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY packages/core /app/packages/core
RUN python3 -m venv /app/.venv \
    && /app/.venv/bin/pip install --no-cache-dir /app/packages/core

COPY --from=build /app/packages/server/dist /app/packages/server/dist
COPY --from=build /app/packages/server/node_modules /app/packages/server/node_modules
COPY --from=build /app/packages/server/package.json /app/packages/server/package.json

ENV PATH="/app/.venv/bin:$PATH"
ENV NODE_ENV=production

WORKDIR /app/packages/server
EXPOSE 8080
CMD ["node", "dist/index.js"]
