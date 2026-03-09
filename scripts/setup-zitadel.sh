#!/bin/bash
# Zitadel Setup Script for OntoKit
# This script automates the creation of OIDC applications in Zitadel
# Run this after a fresh `docker compose up -d` with clean volumes
#
# Usage:
#   ./setup-zitadel.sh                    # Display credentials only
#   ./setup-zitadel.sh --update-env       # Update .env files with credentials
#   ./setup-zitadel.sh --docker-init      # Start Docker stack and configure
#   ./setup-zitadel.sh --update-env --docker-init  # Full automated setup
#   ./setup-zitadel.sh --force-secrets    # Regenerate client secrets (invalidates sessions)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
ZITADEL_URL="${ZITADEL_URL:-http://localhost:8080}"
ZITADEL_DATA_VOLUME="${ZITADEL_DATA_VOLUME:-ontokit-api_zitadel_data}"
WEB_PORT="${WEB_PORT:-3000}"
MAX_RETRIES=30
RETRY_INTERVAL=5

# Output files
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_DIR="${SCRIPT_DIR}/.."
API_ENV_FILE="${API_DIR}/.env"
WEB_ENV_FILE="${SCRIPT_DIR}/../../ontokit-web/.env.local"

# Parse command line arguments
UPDATE_ENV="${UPDATE_ENV:-false}"
DOCKER_INIT="${DOCKER_INIT:-false}"
FORCE_SECRETS="${FORCE_SECRETS:-false}"
for arg in "$@"; do
    case $arg in
        --update-env)
            UPDATE_ENV="true"
            ;;
        --docker-init)
            DOCKER_INIT="true"
            ;;
        --force-secrets)
            FORCE_SECRETS="true"
            ;;
    esac
done

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}  OntoKit Zitadel Setup Script${NC}"
echo -e "${BLUE}========================================${NC}"
echo

# Function to check if API is running in Docker
is_api_running_in_docker() {
    docker compose ps --status running 2>/dev/null | grep -q "ontokit-api"
}

# Function to start Docker stack
start_docker_stack() {
    echo -e "${YELLOW}Starting Docker stack...${NC}" >&2
    cd "$API_DIR"
    docker compose up -d
    echo -e "${GREEN}Docker stack started${NC}" >&2
}

# Function to recreate API container to pick up new env vars
recreate_api_container() {
    echo -e "${YELLOW}Recreating API container to pick up new credentials...${NC}" >&2
    cd "$API_DIR"
    docker compose up -d --force-recreate api worker
    echo -e "${GREEN}API and worker containers recreated${NC}" >&2
}

# Function to prompt user for Docker action (interactive mode)
prompt_docker_action() {
    if is_api_running_in_docker; then
        echo -e "${YELLOW}API is running in Docker with stale credentials.${NC}"
        read -p "Recreate API container to pick up new credentials? (Y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Nn]$ ]]; then
            recreate_api_container
        fi
    else
        echo -e "${YELLOW}Docker stack is not running.${NC}"
        read -p "Start Docker stack now? (y/N) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            start_docker_stack
        fi
    fi
}

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

# Function to create OntoKit project
create_project() {
    local pat="$1"
    echo -e "${YELLOW}Creating OntoKit project...${NC}" >&2

    # Check if project already exists
    existing=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects/_search" \
        -H "Authorization: Bearer $pat" \
        -H "Content-Type: application/json" \
        -d '{"queries": [{"nameQuery": {"name": "OntoKit", "method": "TEXT_QUERY_METHOD_EQUALS"}}]}')

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
        -d '{"name": "OntoKit"}')

    project_id=$(echo "$result" | jq -r '.id // empty')

    if [ -n "$project_id" ]; then
        echo -e "${GREEN}Project created with ID: $project_id${NC}" >&2
        echo "$project_id"
    else
        echo -e "${RED}Failed to create project: $result${NC}" >&2
        exit 1
    fi
}

# Function to get existing client secret from .env file
get_existing_client_secret() {
    local client_id="$1"
    local existing_secret=""

    # Check API .env file first
    if [ -f "$API_ENV_FILE" ]; then
        local env_client_id=$(grep "^ZITADEL_CLIENT_ID=" "$API_ENV_FILE" 2>/dev/null | cut -d= -f2)
        if [ "$env_client_id" = "$client_id" ]; then
            existing_secret=$(grep "^ZITADEL_CLIENT_SECRET=" "$API_ENV_FILE" 2>/dev/null | cut -d= -f2)
        fi
    fi

    # Fall back to web .env.local if not found
    if [ -z "$existing_secret" ] && [ -f "$WEB_ENV_FILE" ]; then
        local env_client_id=$(grep "^ZITADEL_CLIENT_ID=" "$WEB_ENV_FILE" 2>/dev/null | cut -d= -f2)
        if [ "$env_client_id" = "$client_id" ]; then
            existing_secret=$(grep "^ZITADEL_CLIENT_SECRET=" "$WEB_ENV_FILE" 2>/dev/null | cut -d= -f2)
        fi
    fi

    echo "$existing_secret"
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

        # Check if we have an existing secret that matches this client ID
        existing_secret=$(get_existing_client_secret "$client_id")

        if [ -n "$existing_secret" ] && [ "$FORCE_SECRETS" != "true" ]; then
            echo -e "${GREEN}Using existing client secret (sessions preserved)${NC}" >&2
            client_secret="$existing_secret"
        else
            if [ "$FORCE_SECRETS" = "true" ]; then
                echo -e "${YELLOW}Regenerating client secret (--force-secrets)...${NC}" >&2
            else
                echo -e "${YELLOW}No existing secret found, generating new one...${NC}" >&2
            fi
            # Generate new client secret
            secret_result=$(curl -s -X POST "${ZITADEL_URL}/management/v1/projects/${project_id}/apps/${existing_id}/oidc_config/_generate_client_secret" \
                -H "Authorization: Bearer $pat" \
                -H "Content-Type: application/json")

            client_secret=$(echo "$secret_result" | jq -r '.clientSecret // empty')
        fi

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
                \"accessTokenType\": \"OIDC_TOKEN_TYPE_JWT\",
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
            \"accessTokenType\": \"OIDC_TOKEN_TYPE_JWT\",
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
        -d '{"queries": [{"userNameQuery": {"userName": "admin@ontokit.localhost", "method": "TEXT_QUERY_METHOD_EQUALS"}}]}')

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
    # Handle --docker-init: start Docker stack if not running
    if [[ "$DOCKER_INIT" == "true" ]]; then
        cd "$API_DIR"
        if ! docker compose ps --status running 2>/dev/null | grep -q "ontokit-zitadel"; then
            echo -e "${YELLOW}Starting Docker stack...${NC}"
            docker compose up -d
            echo -e "${GREEN}Docker stack started${NC}"
            echo
        fi
    fi

    # Wait for Zitadel
    wait_for_zitadel

    # Get admin PAT
    PAT=$(get_admin_pat)

    # Create project
    PROJECT_ID=$(create_project "$PAT")

    # Create OntoKit Web app
    echo
    WEB_CREDS=$(create_oidc_app "$PAT" "$PROJECT_ID" "OntoKit Web" \
        "http://localhost:${WEB_PORT}/api/auth/callback/zitadel" \
        "http://localhost:${WEB_PORT}")
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

        # Handle Docker container recreation
        if [[ "$DOCKER_INIT" == "true" ]]; then
            # Automatic mode: recreate containers without prompting
            if is_api_running_in_docker; then
                recreate_api_container
            fi
        elif [ -t 0 ]; then
            # Interactive mode: prompt user
            prompt_docker_action
        else
            # Non-interactive, non-docker-init: just remind user
            echo -e "${YELLOW}Remember to restart your services to pick up the new credentials.${NC}"
            if is_api_running_in_docker; then
                echo -e "${YELLOW}Run: docker compose up -d --force-recreate api worker${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}To automatically update .env files, run with --update-env flag${NC}"
        echo
        echo -e "Manual configuration:"
        echo -e "  1. Add these to ontokit-api/.env:"
        echo -e "     ZITADEL_CLIENT_ID=${WEB_CLIENT_ID}"
        echo -e "     ZITADEL_CLIENT_SECRET=${WEB_CLIENT_SECRET}"
        echo -e "     ZITADEL_SERVICE_TOKEN=${PAT}"
        if [ -n "$ADMIN_USER_ID" ]; then
            echo -e "     SUPERADMIN_USER_IDS=${ADMIN_USER_ID}"
        fi
        echo
        echo -e "  2. Add these to ontokit-web/.env.local:"
        echo -e "     ZITADEL_CLIENT_ID=${WEB_CLIENT_ID}"
        echo -e "     NEXT_PUBLIC_ZITADEL_CLIENT_ID=${WEB_CLIENT_ID}"
        echo -e "     ZITADEL_CLIENT_SECRET=${WEB_CLIENT_SECRET}"
    fi

    echo
    echo -e "${GREEN}Zitadel Admin Login:${NC}"
    echo -e "  URL:      ${ZITADEL_URL}/ui/console"
    echo -e "  Username: admin@ontokit.localhost"
    echo -e "  Password: Admin123!"
    echo
    echo -e "${GREEN}Mailpit (Email Testing):${NC}"
    echo -e "  URL: http://localhost:8025"
    echo
}

main "$@"
