# TODO: once building inside the company network, point these at the
# internal registry mirror's copies instead of Docker Hub directly -
# exact hostname/path unconfirmed, ask IT.
#
# TODO: `npm ci` below needs to reach the npm registry. Confirmed so far:
# the internal Docker image registry/mirror exists, but an internal
# npm/PyPI mirror is NOT confirmed - if there isn't one, this image needs
# to be built somewhere with internet access (e.g. at home) and pushed to
# the internal registry, rather than built inside the company network.
# Same applies to the backend's `pip install`.
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
