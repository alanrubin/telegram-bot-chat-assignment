# --- Build stage: compile the React/TypeScript app to static assets ---
FROM node:20-alpine AS build

WORKDIR /app

# Install deps first (cached unless package files change).
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# --- Serve stage: nginx serves the static build and reverse-proxies /ws ---
FROM nginx:alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
