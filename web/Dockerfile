FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json ./
RUN npm install --no-audit --no-fund
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1 DFO_API_URL=http://api:8000
RUN npm run build
CMD ["npm","start","--","--hostname","0.0.0.0"]
