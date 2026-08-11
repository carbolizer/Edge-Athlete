# this part dynamically builds react files
# Pinned to 22 LTS: Vite 8 / rolldown require Node ^20.19.0 || >=22.12.0. The old
# floating `node:20-alpine` tag could resolve to a cached pre-20.19 Node on some
# machines, crashing `vite build` with "node:util has no export 'styleText'".
FROM node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32 AS build

ARG VITE_DEPLOYMENT_PROFILE=local
ENV VITE_DEPLOYMENT_PROFILE=$VITE_DEPLOYMENT_PROFILE

# create and copy working folder inside container
WORKDIR /frontend_container
# copy package list first so Docker can cache npm install
COPY package.json .

# copy exact dependency versions into the container
COPY package-lock.json .

# install react/ vite dependencies
RUN npm ci

# copy the rest of the react files in
COPY . .

# build react app into static files (created in 'dist' folder)
RUN npm run build

# ------------------------------------------------------------------------------------------------------------

# this part runs once docker is up to serve pages
FROM nginx:alpine@sha256:dc48b7a872a79fb541ba5081d320b11b549231bc63ba465a7495afaa7d2ebcb8

ARG VITE_DEPLOYMENT_PROFILE=local

# copy finished website files from first part into nginx's default website folder
COPY --from=build /frontend_container/dist /usr/share/nginx/html
RUN if [ "$VITE_DEPLOYMENT_PROFILE" = "hosted" ]; then rm /usr/share/nginx/html/service-worker.js; fi

# use our nginx config so client-side routes (e.g. /connection-test) fall back to
# index.html instead of 404ing — see react/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# tell docker this uses port 80 for web traffic
EXPOSE 80


# Start nginx and keep it running
# Docker containers stop if nothing is actively running
CMD ["nginx", "-g", "daemon off;"]
