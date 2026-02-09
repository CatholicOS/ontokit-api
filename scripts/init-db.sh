#!/bin/bash
# Initialize PostgreSQL with multiple databases for Axigraph stack
# This script runs as the postgres superuser during container startup

set -e

# Create Zitadel database and user
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create Zitadel user and database
    CREATE USER zitadel WITH PASSWORD 'zitadel';
    CREATE DATABASE zitadel OWNER zitadel;
    GRANT ALL PRIVILEGES ON DATABASE zitadel TO zitadel;

    -- Create Axigraph user and database
    CREATE USER axigraph WITH PASSWORD 'axigraph';
    CREATE DATABASE axigraph OWNER axigraph;
    GRANT ALL PRIVILEGES ON DATABASE axigraph TO axigraph;
EOSQL

echo "Databases initialized: zitadel, axigraph"
