FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# Force IPv4-first DNS resolution for both migration and app
ENV NODE_OPTIONS="--dns-result-order=ipv4first"

# Allow self-signed certificates from Supabase pooler
# This is safe because we're connecting to Supabase (not user-controlled sources)
ENV NODE_TLS_REJECT_UNAUTHORIZED=0

# Start the indexer with migration applied first
CMD ["sh", "-c", "npx squid-typeorm-migration apply && npm start"]
