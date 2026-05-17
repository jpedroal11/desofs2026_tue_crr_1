# Database Module

This folder contains database setup scripts and configuration files for the Marketplace API.

## Purpose

The `database` module manages database initialization, schema creation, and development fixtures. It provides the infrastructure needed for database operations across the application.

## Files Overview

### `script.sql`
- **Purpose**: Database schema definition and initialization script
- **Key Contents**:
  - CREATE TABLE statements for all entities (users, products, orders, etc.)
  - Index definitions for performance optimization
  - Foreign key constraints for data integrity
  - Default data seeds (optional)
- **Usage**: 
  - Used in production deployments instead of SQLAlchemy's auto-create
  - Executed manually or via database migration tools
  - Ensures database schema is consistent across environments
- **AI Context**: When modifying data models, update both this script and `models/models.py` to keep them in sync

### `docker-compose.yml`
- **Purpose**: Docker Compose configuration for local development
- **Key Features**:
  - PostgreSQL database container setup
  - Environment variables for database connection
  - Volume mounts for data persistence
  - Network configuration for service communication
- **Usage**: 
  ```bash
  docker-compose up -d  # Start PostgreSQL
  ```
- **AI Context**: Use this to understand the development database setup and connection parameters

## Integration with the Application

1. **Development Mode**: 
   - `main.py` calls `Base.metadata.create_all(bind=engine)` on startup
   - SQLAlchemy models in `models/models.py` define the schema
   - This auto-creates tables from model definitions

2. **Production Mode**:
   - `script.sql` is executed to create the schema
   - Alembic migrations (future enhancement) will manage schema changes
   - Ensures controlled, versioned database changes

3. **Database Connection**:
   - `core/dependencies.py` creates the database engine
   - Uses `DATABASE_URL` environment variable
   - Supports SQLite (default) and PostgreSQL

## Common Tasks

### Setting Up Local PostgreSQL

```bash
# Start the database container
cd database/
docker-compose up -d

# Verify connection
psql -h localhost -U postgres -d marketplace
```

### Running SQL Scripts

```bash
# Execute the schema script manually
psql -h localhost -U postgres -d marketplace < script.sql
```

### Checking Schema

```bash
# Connect to the database and view tables
psql -h localhost -U postgres -d marketplace -c "\dt"
```

## Modification Guidelines

- **Schema changes**: 
  1. Update the SQLAlchemy model in `models/models.py`
  2. Update `script.sql` to match
  3. Run `Base.metadata.create_all()` in dev or execute `script.sql` in production
  
- **Adding fixtures**:
  1. Add seed data to `script.sql` as INSERT statements
  2. Or use a separate migration/seeding tool

- **Environment changes**:
  1. Update `docker-compose.yml` if changing service configuration
  2. Update environment variables in `core/config.py`
