# this part dynamically builds react files
# Pinned to 22 LTS: Vite 8 / rolldown require Node ^20.19.0 || >=22.12.0. The old
# floating `node:20-alpine` tag could resolve to a cached pre-20.19 Node on some
# machines, crashing `vite build` with "node:util has no export 'styleText'".
FROM node:22-alpine AS build

# create and copy working folder inside container
WORKDIR /frontend_container
# copy package list first so Docker can cache npm install
COPY package.json .

# copy exact dependency versions into the container
COPY package-lock.json .

# install react/ vite dependencies
RUN npm install

# copy the rest of the react files in
COPY . .

# build react app into static files (created in 'dist' folder)
RUN npm run build

# ------------------------------------------------------------------------------------------------------------

# this part runs once docker is up to serve pages
FROM nginx:alpine

# copy finished website files from first part into nginx's default website folder
COPY --from=build /frontend_container/dist /usr/share/nginx/html

# use our nginx config so client-side routes (e.g. /connection-test) fall back to
# index.html instead of 404ing — see react/nginx.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf

# tell docker this uses port 80 for web traffic
EXPOSE 80


# Start nginx and keep it running
# Docker containers stop if nothing is actively running
CMD ["nginx", "-g", "daemon off;"]