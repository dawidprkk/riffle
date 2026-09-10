# Development server. A production build would be `npm run build` served by nginx;
# for the demo the dev server is the point — it hot-reloads while you explore.
FROM node:24-alpine

WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install

COPY . .

EXPOSE 5173
CMD ["npm", "run", "dev"]
