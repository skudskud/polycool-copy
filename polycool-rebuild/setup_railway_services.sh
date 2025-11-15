#!/bin/bash

# Script to setup Railway services for Polycool
echo "🚀 Setting up Railway services for Polycool..."

# Service configurations
SERVICES=(
    "polycool-api:API service for business logic"
    "polycool-bot:Telegram bot interface"
    "polycool-indexer:Subsquid indexer for trades"
    "polycool-streamer:WebSocket market data streamer"
    "polycool-poller:Market data polling service"
)

# Create services
for service_info in "${SERVICES[@]}"; do
    IFS=':' read -r service_name service_desc <<< "$service_info"
    echo "📦 Creating service: $service_name ($service_desc)"

    # Create empty service
    railway add --service "$service_name"

    # Link to repository
    if [ "$service_name" = "polycool-indexer" ]; then
        cd ../apps/subsquid-silo-tests/indexer-ts
        railway link -s "$service_name"
        cd -
    else
        railway link -s "$service_name"
    fi

    echo "✅ Created $service_name"
done

echo "🎉 All services created!"

# Configure environment variables
echo "🔧 Configuring environment variables..."

# Read .env.local if it exists
if [ -f ".env.local" ]; then
    echo "📄 Reading environment variables from .env.local..."

    # Parse .env.local and set variables for each service
    while IFS='=' read -r key value; do
        # Skip comments and empty lines
        [[ $key =~ ^#.*$ ]] && continue
        [[ -z $key ]] && continue

        echo "Setting $key for all services..."

        # Set for each service
        for service_info in "${SERVICES[@]}"; do
            IFS=':' read -r service_name service_desc <<< "$service_info"
            railway variables set "$key"="$value" --service "$service_name" 2>/dev/null || true
        done

    done < .env.local
fi

# Set specific Redis URL for all services
echo "🔗 Configuring Redis connection..."
REDIS_URL=$(railway variables get REDIS_URL 2>/dev/null || echo "redis://default:nAUqCeWhaVgoeAVoBpLJRNRSMyPMLWSG@redis.railway.internal:6379")

for service_info in "${SERVICES[@]}"; do
    IFS=':' read -r service_name service_desc <<< "$service_info"
    railway variables set REDIS_URL="$REDIS_URL" --service "$service_name" 2>/dev/null || true
done

# Set Supabase URL for all services
SUPABASE_URL="postgresql://polycool:polycool2025@aws-1-eu-north-1.pooler.supabase.com:5432/postgres"
for service_info in "${SERVICES[@]}"; do
    IFS=':' read -r service_name service_desc <<< "$service_info"
    railway variables set DATABASE_URL="$SUPABASE_URL" --service "$service_name" 2>/dev/null || true
done

echo "🎯 Railway services setup complete!"
echo ""
echo "📋 Services created:"
for service_info in "${SERVICES[@]}"; do
    IFS=':' read -r service_name service_desc <<< "$service_info"
    echo "  • $service_name: $service_desc"
done
echo ""
echo "🔄 Next steps:"
echo "  1. Configure railway.json for each service"
echo "  2. Deploy services: railway up --service <service-name>"
echo "  3. Test connections and health checks"
