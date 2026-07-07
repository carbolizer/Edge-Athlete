# this part dynamically builds react files
FROM node:20-alpine AS build

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

# tell docker this uses port 80 for web traffic
EXPOSE 80


# Start nginx and keep it running
# Docker containers stop if nothing is actively running
CMD ["nginx", "-g", "daemon off;"]