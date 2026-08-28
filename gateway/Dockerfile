FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY server.js tracing.js ./

EXPOSE 3000

CMD ["npm", "start"]
