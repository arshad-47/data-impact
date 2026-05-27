-- PostgreSQL Database Schema definition
-- Created for: Program & Impact Analytics
-- Designed for: PostgreSQL 12+

-- Drop existing tables to ensure clean slate
DROP TABLE IF EXISTS upload_history CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS target_numbers CASCADE;
DROP TABLE IF EXISTS program_data CASCADE;
DROP TABLE IF EXISTS project_statuses CASCADE;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ==========================================
-- 1. Table: project_statuses
-- ==========================================
-- Stores high-resolution individual record updates from the program dashboards
-- for the master states (Bihar, Karnataka, and Nagaland).
CREATE TABLE project_statuses (
    id VARCHAR(24) PRIMARY KEY DEFAULT lower(substr(replace(gen_random_uuid()::text, '-', ''), 1, 24)),
    CONSTRAINT project_statuses_id_format CHECK (id ~ '^[0-9a-f]{24}$'),
    user_uuid UUID,                               -- User identifier (can be duplicate if user takes multiple projects)
    user_type VARCHAR(100),
    user_sub_type TEXT,
    declared_state VARCHAR(100) NOT NULL,
    district VARCHAR(100),
    block VARCHAR(100),
    school_name TEXT,
    school_id VARCHAR(50),
    declared_board VARCHAR(100),
    org_name VARCHAR(255),
    program_name VARCHAR(255),
    program_id VARCHAR(100),
    project_id VARCHAR(100),
    project_title TEXT,
    project_objective TEXT,
    project_start_date_user TIMESTAMPTZ,
    project_completion_date_user TIMESTAMPTZ,
    project_duration VARCHAR(50),
    project_last_synced_date TIMESTAMPTZ,
    project_status VARCHAR(50),
    certificate_status VARCHAR(50)
);

-- Indexes for performance optimization on common reporting queries
CREATE INDEX idx_project_statuses_user_uuid ON project_statuses (user_uuid);
CREATE INDEX idx_project_statuses_state_district ON project_statuses (declared_state, district);
CREATE INDEX idx_project_statuses_program_project ON project_statuses (program_id, project_id);
CREATE INDEX idx_project_statuses_status ON project_statuses (project_status);


-- ==========================================
-- 2. Table: program_data
-- ==========================================
-- A generalized repository designed to hold both historical datasets 
-- and future live/operational program metric sets.
CREATE TABLE program_data (
    program_id UUID PRIMARY KEY DEFAULT gen_random_uuid(), -- System-generated program primary key
    program_name VARCHAR(255) NOT NULL,
    state_name VARCHAR(100) NOT NULL,
    district_name VARCHAR(100) NULL,             -- Nullable: Only populated for district-level records
    started INTEGER DEFAULT 0,
    in_progress INTEGER DEFAULT 0,
    submitted INTEGER DEFAULT 0,
    submitted_with_evidence INTEGER NULL,        -- Nullable: Only populated for specific historical metrics
    total_triggered INTEGER NULL,                -- Nullable: Only populated for specific historical metrics
    historical_program BOOLEAN NOT NULL DEFAULT TRUE -- TRUE for historical records, FALSE for future live metric sets
);

-- Indexes to enable high-speed metrics aggregation
CREATE INDEX idx_program_data_state_district ON program_data (state_name, district_name);
CREATE INDEX idx_program_data_name ON program_data (program_name);
CREATE INDEX idx_program_data_historical ON program_data (historical_program);
CREATE UNIQUE INDEX idx_program_data_unique_program_scope
ON program_data (
    lower(program_name),
    lower(state_name),
    lower(coalesce(district_name, '')),
    historical_program
);


-- ==========================================
-- 3. Table: target_numbers
-- ==========================================
-- Stores target quotas for different states, programs, cycles, and projects
-- to facilitate Target vs. Actual analysis.
CREATE TABLE target_numbers (
    id SERIAL PRIMARY KEY,
    state_name VARCHAR(100) NOT NULL,
    program_type VARCHAR(100),
    program_name VARCHAR(255) NOT NULL,
    cycle VARCHAR(50),
    project_title TEXT,
    target_value INTEGER NOT NULL                -- Standardized clean target integer count
);

-- Indexes for analytical reporting
CREATE INDEX idx_targets_state_program ON target_numbers (state_name, program_name);
CREATE UNIQUE INDEX idx_target_numbers_unique_program_cycle
ON target_numbers (
    lower(program_name),
    lower(coalesce(cycle, '')),
    lower(coalesce(project_title, '')),
    lower(state_name)
);


-- ==========================================
-- 4. Table: users
-- ==========================================
-- Maintains application users and their access roles.
CREATE TABLE users (
    user_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username VARCHAR(100) NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role VARCHAR(50) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT users_role_check CHECK (
        role IN ('upload_master', 'state_data_uploader', 'report_viewer')
    )
);

CREATE INDEX idx_users_username ON users (username);
CREATE INDEX idx_users_role ON users (role);

INSERT INTO users (username, password_hash, role) VALUES
    ('admin', crypt('admin', gen_salt('bf')), 'upload_master'),
    ('munna', crypt('munna', gen_salt('bf')), 'state_data_uploader'),
    ('Aishwarya', crypt('Aishwarya', gen_salt('bf')), 'report_viewer');


-- ==========================================
-- 5. Table: upload_history
-- ==========================================
-- Tracks CSV uploads, uploader, processing status, stats, and failed rows.
CREATE TABLE upload_history (
    upload_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    uploaded_by UUID REFERENCES users(user_id),
    username VARCHAR(100) NOT NULL,
    upload_type VARCHAR(50) NOT NULL,
    file_name TEXT NOT NULL,
    status VARCHAR(30) NOT NULL,
    stats JSONB NOT NULL DEFAULT '{}'::jsonb,
    failed_rows JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    CONSTRAINT upload_history_type_check CHECK (
        upload_type IN (
            'historical_data_before_VAM',
            'historical_data_after_VAM',
            'state_project_status',
            'target_numbers'
        )
    ),
    CONSTRAINT upload_history_status_check CHECK (
        status IN ('processing', 'completed', 'completed_with_errors', 'failed')
    )
);

CREATE INDEX idx_upload_history_uploaded_by ON upload_history (uploaded_by);
CREATE INDEX idx_upload_history_upload_type ON upload_history (upload_type);
CREATE INDEX idx_upload_history_created_at ON upload_history (created_at);
