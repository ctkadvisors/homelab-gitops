FROM node:24-bookworm-slim

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY server.mjs ./
COPY src ./src

ENV NODE_ENV=production
ENV PORT=8080

USER node

EXPOSE 8080
CMD ["node", "server.mjs"]
