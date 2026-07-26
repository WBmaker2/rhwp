FROM rust:1.93-bookworm AS rust-build
WORKDIR /src
COPY Cargo.toml Cargo.lock rust-toolchain.toml ./
COPY src ./src
RUN cargo build --release --no-default-features --bin rhwp-collaboration-worker

FROM node:22-bookworm-slim AS node-build
WORKDIR /app
COPY services/document-worker/package.json ./
RUN npm install --ignore-scripts --no-audit --no-fund
COPY services/document-worker/tsconfig.json ./
COPY services/document-worker/src ./src
RUN npm run build && npm prune --omit=dev

FROM node:22-bookworm-slim AS runtime
ENV NODE_ENV=production \
    PORT=8080 \
    RHWP_COLLABORATION_WORKER_BIN=/usr/local/bin/rhwp-collaboration-worker
WORKDIR /app
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=rust-build /src/target/release/rhwp-collaboration-worker /usr/local/bin/rhwp-collaboration-worker
COPY --from=node-build /app/package.json ./package.json
COPY --from=node-build /app/node_modules ./node_modules
COPY --from=node-build /app/dist ./dist
RUN chown -R node:node /app /usr/local/bin/rhwp-collaboration-worker
USER node
EXPOSE 8080
CMD ["node", "dist/main.js"]
