FROM node:20-alpine

RUN apk add --no-cache curl

WORKDIR /app

COPY package.json ./
RUN npm install --production

COPY server.js ./

ENV PORT=3001
ENV MODELS_PATH=/models
ENV LOCALAI_URL=http://localhost:8080

EXPOSE 3001

CMD ["node", "server.js"]

