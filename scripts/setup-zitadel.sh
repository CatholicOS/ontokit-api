#!/bin/bash
# Zitadel Setup Script for Axigraph
# This script automates the creation of OIDC applications in Zitadel
# Run this after a fresh `docker compose up -d` with clean volumes

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ZITADEL_URL="${ZITADEL_URL:-http://localhost:8080}"
ZITADEL_DATA_VOLUME="${ZITADEL_DATA_VOLUME:-axigraph-api_zitadel_data}"
MAX_RETRIES=30
RETRY_INTERVAL=5

# Output files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_ENV_FILE="${SCRIPT_DIR}/../.env"
WEB_ENV_FILE="${SCRIPT_DIR}/../../axigraph-web/.env.local"

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  Axigraph Zitadel Setup Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo

# Function to wait for Zitadel to be ready
wait_for_zitadel() {
    echo -e "${YELLOW}Waiting for Zitadel to be ready...${NC}"
    for i in $(seq 1 $MAX_RETRIES); do
        if curl -s "${ZITADEL_URL}/debug/healthz" > /dev/null 2>&1; then
            echo -e "${GREEN}Zitadel is ready!${NC}"
            return 0
        fi
        echo "  Attempt $i/$MAX_RETRIES - Zitadel not ready yet..."
        sleep $RETRY_INTERVAL
    done
    echo -e "${RED}Zitadel did not become ready in time${NC}"
    exit 1
}

# Function to get the admin PAT from the Docker volume
get_admin_pat() {
    echo -e "${YELLOW}Getting admin PAT from Zitadel...${NC}" >&2

    # Wait for the PAT file to be created
    for i in $(seq 1 $MAX_RETRIES); do
        PAT=$(docker run --rm -v "${ZITADEL_DATA_VOLUME}:/data" alpine cat /data/admin.pat 2>/dev/null || true)
        if [ -n "$PAT" ] && [ ${#PAT} -gt 10 ]; then
            echo -e "${GREEN}Admin PAT retrieved successfully${NC}" >&2
            echo "$PAT"
            return 0
        fi
        echo "  Attempt $i/$MAX_RETRIES - PAT not available yet..." >&2
        sleep $RETRY_INTERVAL
    done
    echo -e "${RED}Failed to get admin PAT${NC}" >&2
    exit 1
}

# Function to create Axigraph project
create_project() {
    local pat="$1"
    echo -e "${YELLOW}Creating Axigraph project...${NC}" >&2

    # Check if project already exists
    existing=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects/_search" \
        -H "Authorization: Bearer $pat" \
        -H "Content-Type: application/json" \
        -d '{"queries": [{"nameQuery": {"name": "Axigraph", "method": "TEXT_QUERY_METHOD_EQUALS"}}]}')

    existing_id=$(echo "$existing" | jq -r '.result[0].id // empty')

    if [ -n "$existing_id" ]; then
        echo -e "${GREEN}Project already exists with ID: $existing_id${NC}" >&2
        echo "$existing_id"
        return 0
    fi

    # Create new project
    result=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects" \
        -H "Authorization: Bearer $pat" \
        -H "Content-Type: application/json" \
        -d '{"name": "Axigraph"}')

    project_id=$(echo "$result" | jq -r '.id // empty')

    if [ -n "$project_id" ]; then
        echo -e "${GREEN}Project created with ID: $project_id${NC}" >&2
        echo "$project_id"
    else
        echo -e "${RED}Failed to create project: $result${NC}" >&2
        exit 1
    fi
}

# Function to create OIDC application
create_oidc_app() {
    local pat="$1"
    local project_id="$2"
    local app_name="$3"
    local redirect_uri="$4"
    local post_logout_uri="$5"

    echo -e "${YELLOW}Creating OIDC app: $app_name...${NC}" >&2

    # Check if app already exists
    existing=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects/${project_id}/apps/_search" \
        -H "Authorization: Bearer $pat" \
        -H "Content-Type: application/json" \
        -d '{}')

    existing_id=$(echo "$existing" | jq -r --arg name "$app_name" '.result[] | select(.name == $name) | .id // empty')

    if [ -n "$existing_id" ]; then
        echo -e "${YELLOW}App already exists, getting client ID...${NC}" >&2
        client_id=$(echo "$existing" | jq -r --arg name "$app_name" '.result[] | select(.name == $name) | .oidcConfig.clientId // empty')

        # Generate new client secret
        secret_result=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects/${project_id}/apps/${existing_id}/oidc_config/_generate_client_secret" \
            -H "Authorization: Bearer $pat" \
            -H "Content-Type: application/json")

        client_secret=$(echo "$secret_result" | jq -r '.clientSecret // empty')

        # Update config to ensure idTokenUserinfoAssertion is enabled
        curl -s -X PUT "${ZITADEL_URL}/management/v1/projects/${project_id}/apps/${existing_id}/oidc_config" \
            -H "Authorization: Bearer $pat" \
            -H "Content-Type: application/json" \
            -d "{
                \"redirectUris\": [\"$redirect_uri\"],
                \"postLogoutRedirectUris\": [\"$post_logout_uri\"],
                \"responseTypes\": [\"OIDC_RESPONSE_TYPE_CODE\"],
                \"grantTypes\": [\"OIDC_GRANT_TYPE_AUTHORIZATION_CODE\", \"OIDC_GRANT_TYPE_REFRESH_TOKEN\"],
                \"appType\": \"OIDC_APP_TYPE_WEB\",
                \"authMethodType\": \"OIDC_AUTH_METHOD_TYPE_BASIC\",
                \"accessTokenType\": \"OIDC_TOKEN_TYPE_BEARER\",
                \"devMode\": true,
                \"idTokenRoleAssertion\": true,
                \"idTokenUserinfoAssertion\": true
            }" > /dev/null

        echo "${client_id}:${client_secret}"
        return 0
    fi

    # Create new app
    result=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects/${project_id}/apps/oidc" \
        -H "Authorization: Bearer $pat" \
        -H "Content-Type: application/json" \
        -d "{
            \"name\": \"$app_name\",
            \"redirectUris\": [\"$redirect_uri\"],
            \"postLogoutRedirectUris\": [\"$post_logout_uri\"],
            \"responseTypes\": [\"OIDC_RESPONSE_TYPE_CODE\"],
            \"grantTypes\": [\"OIDC_GRANT_TYPE_AUTHORIZATION_CODE\", \"OIDC_GRANT_TYPE_REFRESH_TOKEN\"],
            \"appType\": \"OIDC_APP_TYPE_WEB\",
            \"authMethodType\": \"OIDC_AUTH_METHOD_TYPE_BASIC\",
            \"accessTokenType\": \"OIDC_TOKEN_TYPE_BEARER\",
            \"devMode\": true,
            \"idTokenRoleAssertion\": true,
            \"idTokenUserinfoAssertion\": true
        }")

    client_id=$(echo "$result" | jq -r '.clientId // empty')
    client_secret=$(echo "$result" | jq -r '.clientSecret // empty')
    app_id=$(echo "$result" | jq -r '.appId // empty')

    if [ -n "$client_id" ] && [ -n "$client_secret" ]; then
        echo -e "${GREEN}App created successfully${NC}" >&2
        echo "${client_id}:${client_secret}"
    else
        echo -e "${RED}Failed to create app: $result${NC}" >&2
        exit 1
    fi
}

# Function to get admin user ID
get_admin_user_id() {
    local pat="$1"
    echo -e "${YELLOW}Getting admin user ID...${NC}" >&2

    # Search for the admin user
    result=$(curl -s -X POST "${ZITADEL_URL}/management/v1/users/_search" \
        -H "Authorization: Bearer $pat" \
        -H "Content-Type: application/json" \
        -d '{"queries": [{"userNameQuery": {"userName": "admin@axigraph.localhost", "method": "TEXT_QUERY_METHOD_EQUALS"}}]}')

    admin_id=$(echo "$result" | jq -r '.result[0].id // empty')

    if [ -n "$admin_id" ]; then
        echo -e "${GREEN}Admin user ID: $admin_id${NC}" >&2
        echo "$admin_id"
    else
        echo -e "${YELLOW}Admin user not found (may not be created yet)${NC}" >&2
        echo ""
    fi
}

# Function to update .env file
update_env_file() {
    local file="$1"
    local key="$2"
    local value="$3"

    if [ ! -f "$file" ]; then
        echo -e "${YELLOW}Creating $file${NC}"
        touch "$file"
    fi

    # Check if key exists in file
    if grep -q "^${key}=" "$file" 2>/dev/null; then
        # Update existing key (works on both Linux and macOS)
        if [[ "$OSTYPE" == "darwin"* ]]; then
            sed -i '' "s|^${key}=.*|${key}=${value}|" "$file"
        else
            sed -i "s|^${key}=.*|${key}=${value}|" "$file"
        fi
    else
        # Add new key
        echo "${key}=${value}" >> "$file"
    fi
}

# Main execution
main() {
    # Wait for Zitadel
    wait_for_zitadel

    # Get admin PAT
    PAT=$(get_admin_pat)

    # Create project
    PROJECT_ID=$(create_project "$PAT")

    # Create Axigraph Web app
    echo
    WEB_CREDS=$(create_oidc_app "$PAT" "$PROJECT_ID" "Axigraph Web" \
        "http://localhost:3000/api/auth/callback/zitadel" \
        "http://localhost:3000")
    WEB_CLIENT_ID=$(echo "$WEB_CREDS" | cut -d: -f1)
    WEB_CLIENT_SECRET=$(echo "$WEB_CREDS" | cut -d: -f2)

    # Get admin user ID for superadmin
    echo
    ADMIN_USER_ID=$(get_admin_user_id "$PAT")

    echo
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}  Configuration Complete!${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo
    echo -e "${GREEN}Zitadel Credentials:${NC}"
    echo -e "  Client ID:       ${WEB_CLIENT_ID}"
    echo -e "  Client Secret:   ${WEB_CLIENT_SECRET}"
    echo -e "  Service Token:   ${PAT}"
    if [ -n "$ADMIN_USER_ID" ]; then
        echo -e "  Admin User ID:   ${ADMIN_USER_ID}"
    fi
    echo

    # Update .env files if they exist or if --update-env flag is passed
    if [[ "$1" == "--update-env" ]] || [[ "$UPDATE_ENV" == "true" ]]; then
        echo -e "${YELLOW}Updating environment files...${NC}"

        # Update API .env
        if [ -f "$API_ENV_FILE" ]; then
            update_env_file "$API_ENV_FILE" "ZITADEL_CLIENT_ID" "$WEB_CLIENT_ID"
            update_env_file "$API_ENV_FILE" "ZITADEL_CLIENT_SECRET" "$WEB_CLIENT_SECRET"
            update_env_file "$API_ENV_FILE" "ZITADEL_SERVICE_TOKEN" "$PAT"
            if [ -n "$ADMIN_USER_ID" ]; then
                update_env_file "$API_ENV_FILE" "SUPERADMIN_USER_IDS" "$ADMIN_USER_ID"
            fi
            echo -e "${GREEN}Updated: $API_ENV_FILE${NC}"
        else
            echo -e "${YELLOW}Skipped (not found): $API_ENV_FILE${NC}"
        fi

        # Update Web .env.local
        if [ -f "$WEB_ENV_FILE" ]; then
            update_env_file "$WEB_ENV_FILE" "ZITADEL_CLIENT_ID" "$WEB_CLIENT_ID"
            update_env_file "$WEB_ENV_FILE" "NEXT_PUBLIC_ZITADEL_CLIENT_ID" "$WEB_CLIENT_ID"
            update_env_file "$WEB_ENV_FILE" "ZITADEL_CLIENT_SECRET" "$WEB_CLIENT_SECRET"
            echo -e "${GREEN}Updated: $WEB_ENV_FILE${NC}"
        else
            echo -e "${YELLOW}Skipped (not found): $WEB_ENV_FILE${NC}"
        fi

        echo
        echo -e "${GREEN}Environment files updated!${NC}"
        echo -e "${YELLOW}Remember to restart your services to pick up the new credentials.${NC}"
    else
        echo -e "${YELLOW}To automatically update .env files, run with --update-env flag${NC}"
        echo
        echo -e "Manual configuration:"
        echo -e "  1. Add these to axigraph-api/.env:"
        echo -e "     ZITADEL_CLIENT_ID=${WEB_CLIENT_ID}"
        echo -e "     ZITADEL_CLIENT_SECRET=${WEB_CLIENT_SECRET}"
        echo -e "     ZITADEL_SERVICE_TOKEN=${PAT}"
        if [ -n "$ADMIN_USER_ID" ]; then
            echo -e "     SUPERADMIN_USER_IDS=${ADMIN_USER_ID}"
        fi
        echo
        echo -e "  2. Add these to axigraph-web/.env.local:"
        echo -e "     ZITADEL_CLIENT_ID=${WEB_CLIENT_ID}"
        echo -e "     NEXT_PUBLIC_ZITADEL_CLIENT_ID=${WEB_CLIENT_ID}"
        echo -e "     ZITADEL_CLIENT_SECRET=${WEB_CLIENT_SECRET}"
    fi

    echo
    echo -e "${GREEN}Zitadel Admin Login:${NC}"
    echo -e "  URL:      ${ZITADEL_URL}/ui/console"
    echo -e "  Username: admin@axigraph.localhost"
    echo -e "  Password: Admin123!"
    echo
    echo -e "${GREEN}Mailpit (Email Testing):${NC}"
    echo -e "  URL: http://localhost:8025"
    echo
}

main "$@"
