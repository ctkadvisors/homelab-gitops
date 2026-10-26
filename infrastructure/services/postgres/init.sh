#!/bin/bash
# PostgreSQL initialization script
# Creates users with proper permissions using environment variables

set -e

echo "Starting PostgreSQL initialization..."

# Wait for PostgreSQL to be ready
until pg_isready -U postgres; do
  echo "Waiting for PostgreSQL to be ready..."
  sleep 2
done

echo "Creating users with password from environment..."

# Create users with proper permissions using environment variable
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Create users with proper permissions
    CREATE USER openwebui WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD';
    CREATE USER mcpo WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD';
    CREATE USER n8n WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD';
    CREATE USER dockploy WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD';
    CREATE USER graphiti WITH ENCRYPTED PASSWORD '$POSTGRES_PASSWORD';

    -- Grant database permissions
    GRANT ALL PRIVILEGES ON DATABASE openwebui TO openwebui;
    GRANT ALL PRIVILEGES ON DATABASE mcpo TO mcpo;
    GRANT ALL PRIVILEGES ON DATABASE n8n TO n8n;
    GRANT ALL PRIVILEGES ON DATABASE dockploy TO dockploy;
    GRANT ALL PRIVILEGES ON DATABASE graphiti TO graphiti;
EOSQL

echo "Setting up database-specific permissions..."

# Connect to each database and set up permissions
databases=("openwebui" "mcpo" "n8n" "dockploy" "graphiti")
users=("openwebui" "mcpo" "n8n" "dockploy" "graphiti")

for i in "${!databases[@]}"; do
    db="${databases[$i]}"
    user="${users[$i]}"
    
    echo "Setting up permissions for $db database..."
    
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<-EOSQL
        -- Grant schema permissions (critical for Open WebUI)
        GRANT ALL ON SCHEMA public TO $user;
        GRANT ALL ON ALL TABLES IN SCHEMA public TO $user;
        GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO $user;
        GRANT ALL ON ALL FUNCTIONS IN SCHEMA public TO $user;
        
        -- Set default privileges for future objects
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO $user;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO $user;
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON FUNCTIONS TO $user;
EOSQL
done

# Set up extensions for specific databases
echo "Setting up extensions..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "openwebui" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "mcpo" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "graphiti" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
EOSQL

echo "PostgreSQL initialization completed successfully!"
