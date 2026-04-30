FROM node:20-alpine
WORKDIR /web

# Just the manifest — leverage layer cache
COPY package.json package-lock.json* ./
RUN npm install

EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]