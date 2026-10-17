FROM mcr.microsoft.com/playwright:v1.64.0-noble AS dependencies
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
FROM dependencies AS tests
COPY packages/ /app/packages/
COPY apps/web/ ./
COPY scripts/e2e_loopback.cjs /app/e2e_loopback.cjs
CMD ["node", "/app/e2e_loopback.cjs"]
