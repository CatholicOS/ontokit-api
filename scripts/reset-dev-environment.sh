#!/bin/bash
# Axigraph Development Environment Reset Script
# This script completely resets the development environment to a clean state
# WARNING: This will delete all data including databases, users, and projects!

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="${SCRIPT_DIR}/.."

echo -e "${RED}========================================${NC}"
echo -e "${RED}  Axigraph Development Environment Reset${NC}"
echo -e "${RED}========================================${NC}"
echo
echo -e "${YELLOW}WARNING: This will delete ALL data including:${NC}"
echo -e "  - PostgreSQL databases (axigraph and zitadel)"
echo -e "  - Redis cache"
echo -e "  - MinIO object storage"
echo -e "  - Zitadel users and applications"
echo -e "  - Git repositories"
echo

# Confirm unless --yes flag is passed
if [[ "$1" != "--yes" ]] && [[ "$1" != "-y" ]]; then
    read -p "Are you sure you want to continue? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo -e "${YELLOW}Aborted.${NC}"
        exit 0
    fi
fi

cd "$API_DIR"

echo
echo -e "${BLUE}Step 1: Stopping containers...${NC}"
docker compose down

echo
echo -e "${BLUE}Step 2: Removing Docker volumes...${NC}"
# Get the compose project name (usually directory name)
PROJECT_NAME=$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]/-/g')

# Remove volumes (try both naming conventions)
for volume in postgres_data redis_data minio_data zitadel_data git_repos; do
    docker volume rm "${PROJECT_NAME}_${volume}" 2>/dev/null && echo "  Removed ${PROJECT_NAME}_${volume}" || true
    docker volume rm "axigraph-api_${volume}" 2>/dev/null && echo "  Removed axigraph-api_${volume}" || true
done

echo
echo -e "${BLUE}Step 3: Cleaning local git repos directory...${NC}"
if [ -d "./data/repos" ]; then
    rm -rf ./data/repos
    echo "  Removed ./data/repos"
fi

echo
echo -e "${BLUE}Step 4: Starting fresh containers...${NC}"
docker compose up -d

echo
echo -e "${BLUE}Step 5: Waiting for services to be healthy...${NC}"
# Wait for postgres
echo -n "  Waiting for PostgreSQL..."
until docker compose exec -T postgres pg_isready -U postgres > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e " ${GREEN}ready${NC}"

# Wait for Zitadel
echo -n "  Waiting for Zitadel..."
until curl -s "http://localhost:8080/debug/healthz" > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e " ${GREEN}ready${NC}"

# Wait for Zitadel login
echo -n "  Waiting for Zitadel Login UI..."
until curl -s "http://localhost:8081/ui/v2/login" > /dev/null 2>&1; do
    echo -n "."
    sleep 2
done
echo -e " ${GREEN}ready${NC}"

echo
echo -e "${BLUE}Step 6: Running database migrations...${NC}"
docker compose exec -T api alembic upgrade head

echo
echo -e "${BLUE}Step 7: Setting up Zitadel applications...${NC}"
UPDATE_ENV=true "${SCRIPT_DIR}/setup-zitadel.sh"

echo
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Reset Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo
echo -e "Next steps:"
echo -e "  1. Restart axigraph-web to pick up new credentials"
echo -e "  2. Sign in with admin@axigraph.localhost / Admin123!"
echo -e "  3. Create your user account through the login flow"
echo
