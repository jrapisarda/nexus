-- NEXUS PostgreSQL extensions initialization
-- This runs automatically on first docker-compose up via initdb.d

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Create test database for integration tests
SELECT 'CREATE DATABASE nexus_test OWNER claudeai'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'nexus_test')\gexec

-- Enable extensions on test database too
\c nexus_test
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
\c nexus
