FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install
COPY . .
ARG VITE_API_URL=
ENV VITE_API_URL=$VITE_API_URL
ARG VITE_CAPTURE_HTTPS_ORIGIN=
ENV VITE_CAPTURE_HTTPS_ORIGIN=$VITE_CAPTURE_HTTPS_ORIGIN
ARG VITE_CAPTURE_HTTPS_PORT=8443
ENV VITE_CAPTURE_HTTPS_PORT=$VITE_CAPTURE_HTTPS_PORT
RUN npm run build

FROM nginx:1.27-alpine
RUN apk add --no-cache openssl
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY docker-entrypoint.d/40-generate-self-signed-cert.sh /docker-entrypoint.d/40-generate-self-signed-cert.sh
RUN chmod +x /docker-entrypoint.d/40-generate-self-signed-cert.sh
EXPOSE 80
EXPOSE 443
CMD ["nginx", "-g", "daemon off;"]
