# Streamlit Upload Portal and Dashboard Implementation Plan

## Goal

Build a Streamlit app with login, role-based access, CSV upload workflows, upload tracking, and a dashboard over `project_statuses`, `program_data`, and `target_numbers`.

## Current Project Structure

- `schema.sql`: PostgreSQL schema.
- `app.py`: Streamlit app with login.
- `.env`: database connection config.
- `requirements.txt`: Python dependencies.
- `data/`: reference CSV files.

## Reference CSV Types

### `state_project_status`

Reference files:

- `data/master-data/Bihar/MIP1.csv`
- `data/master-data/Bihar/MIP2.csv`
- `data/master-data/Karnataka/Digital Nagrik Program.csv`
- `data/master-data/Nagaland/*.csv`

Detected columns:

- `UUID`
- `User Type`
- `User sub type`
- `Declared State`
- `District`
- `Block`
- `School Name`
- `School ID`
- `Declared Board`
- `Org Name`
- `Program Name`
- `Program ID`
- `Project ID`
- `Project Title`
- `Project Objective`
- `Project start date of the user`
- `Project completion date of the user`
- `Project Duration`
- `Project last Synced date`
- `Project Status`
- optional `Certificate Status`

Important mapping:

- `project_statuses.id` should come from CSV `Project ID`.
- `project_statuses.project_id` can also store CSV `Project ID` unless we decide to remove duplication later.

### `historical_data_before_VAM`

Reference file:

- `data/Historical Data_Excluding_VAM and PreVAM Programs - Historical Data_Excluding_VAM and PreVAM Programs.csv`

Detected columns:

- `Program Name`
- `State Name`
- `District Name`
- `Started`
- `In-Progress`
- `Submitted`

Insert target:

- `program_data`
- `historical_program = TRUE`
- `program_id` system-generated UUID

### `historical_data_after_VAM`

Reference file:

- `data/Historical Data _Till the Data_Including VAM - Historical Data _Till the Data_Including VAM.csv`

Detected columns:

- `Program Name`
- `State Name`
- `Started`
- `In-Progress`
- `Submitted`
- `Submitted projects with evidence`
- `Total Triggered`

Insert target:

- `program_data`
- `historical_program = FALSE`
- `program_id` system-generated UUID

### `target_numbers`

Reference file:

- `data/Target Numbers - Sheet1.csv`

Detected columns:

- `State Name`
- `Program Type`
- `Program Name`
- `Cycle`
- `Project Title`
- `Target Name`

Insert target:

- `target_numbers`
- `target_numbers.id` remains `SERIAL`

## Schema Changes

### Add upload tracking table

Create a table to track every CSV upload:

```sql
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
    completed_at TIMESTAMPTZ
);
```

Allowed `upload_type` values:

- `historical_data_before_VAM`
- `historical_data_after_VAM`
- `state_project_status`
- `target_numbers`

Allowed `status` values:

- `processing`
- `completed`
- `completed_with_errors`
- `failed`

### Add dedupe constraints or indexes

Recommended database-level safeguards:

- `project_statuses.id` primary key already prevents duplicate project IDs.
- Add a unique index for `program_data` dedupe:

```sql
CREATE UNIQUE INDEX idx_program_data_unique_program_scope
ON program_data (
    lower(program_name),
    lower(state_name),
    lower(coalesce(district_name, '')),
    historical_program
);
```

- Add a unique index for `target_numbers` dedupe:

```sql
CREATE UNIQUE INDEX idx_target_numbers_unique_program_cycle
ON target_numbers (
    lower(program_name),
    lower(coalesce(cycle, '')),
    lower(coalesce(project_title, '')),
    lower(state_name)
);
```

## App Structure

Keep the first implementation simple:

- `app.py`: Streamlit routing, login, sidebar, page selection.
- `db.py`: database connection and shared query helpers.
- `upload_handlers.py`: CSV validation, cleaning, dedupe checks, inserts.
- `dashboard.py`: dashboard queries and charts.
- `utils.py`: shared cleaning functions.

## Login and Roles

Existing users:

- `admin`: `upload_master`
- `munna`: `state_data_uploader`
- `Aishwarya`: `report_viewer`

Access rules:

- `upload_master`: can upload all CSV types and view dashboard.
- `state_data_uploader`: can upload only `state_project_status` and view dashboard.
- `report_viewer`: can only view dashboard.

## Upload Portal

### Shared UI flow

1. User selects upload type.
2. User uploads a CSV file.
3. App validates required columns for that upload type.
4. App previews first few rows.
5. User clicks `Process Upload`.
6. App inserts valid non-duplicate records.
7. App writes one row into `upload_history`.
8. App displays upload stats and failed rows.

### Shared stats format

All upload handlers should return:

```json
{
  "total_rows_in_csv": 0,
  "successfully_inserted": 0,
  "repeated_records_skipped": 0,
  "failed_insertion": 0
}
```

For UI labels, map `repeated_records_skipped` to:

- `repeteed_projectids_skipped` for `state_project_status`
- `repeteed_programs_skipped` for historical uploads
- `repeteed_programs_skipped` for target uploads

Failed rows should include:

- CSV row number
- row data
- failure reason

## Upload Behavior

### `state_project_status`

For each CSV row:

1. Extract and clean the row.
2. Use CSV `Project ID` as `project_statuses.id`.
3. Check if `project_statuses.id` already exists.
4. If exists, skip and increment `repeteed_projectids_skipped`.
5. If not exists, insert into `project_statuses`.
6. If insert fails, add row to failed rows with reason.

After processing `project_statuses`, update `program_data`:

1. Group newly inserted project status rows by:
   - `program_name`
   - `declared_state`
   - `district`
2. Aggregate counts from `project_status`:
   - `started`
   - `in_progress`
   - `submitted`
3. Check `program_data` for existing matching `program_name`, state, district, and `historical_program = FALSE`.
4. If no matching entry exists, insert a new `program_data` row.
5. If matching entry exists, update aggregate counters by adding the new upload counts.

Default values:

- `historical_program = FALSE`
- `submitted_with_evidence = NULL`
- `total_triggered = started + in_progress + submitted`

### `historical_data_before_VAM`

For each CSV row:

1. Extract:
   - `Program Name`
   - `State Name`
   - `District Name`
   - `Started`
   - `In-Progress`
   - `Submitted`
2. Check for existing `program_data` entry with same:
   - `program_name`
   - `state_name`
   - `district_name`
   - `historical_program = TRUE`
3. If exists, skip and increment `repeteed_programs_skipped`.
4. If not exists, insert into `program_data`.
5. Set:
   - `historical_program = TRUE`
   - `program_id = DEFAULT`
   - `submitted_with_evidence = NULL`
   - `total_triggered = started + in_progress + submitted`

### `historical_data_after_VAM`

For each CSV row:

1. Extract:
   - `Program Name`
   - `State Name`
   - `Started`
   - `In-Progress`
   - `Submitted`
   - `Submitted projects with evidence`
   - `Total Triggered`
2. Check for existing `program_data` entry with same:
   - `program_name`
   - `state_name`
   - `district_name IS NULL`
   - `historical_program = FALSE`
3. If exists, skip and increment `repeteed_programs_skipped`.
4. If not exists, insert into `program_data`.
5. Set:
   - `historical_program = FALSE`
   - `program_id = DEFAULT`

### `target_numbers`

For each CSV row:

1. Extract:
   - `State Name`
   - `Program Type`
   - `Program Name`
   - `Cycle`
   - `Project Title`
   - `Target Name`
2. Check if a record exists with same:
   - `program_name`
   - `cycle`
   - `project_title`
   - `state_name`
3. If exists, skip and increment `repeteed_programs_skipped`.
4. If not exists, insert into `target_numbers`.
5. Let `target_numbers.id` auto-generate via `SERIAL`.

## Dashboard Requirements

### Filters

Add filters at the top/sidebar:

- Pre/Post VAM:
  - Pre VAM: `historical_program = TRUE`
  - Post VAM: `historical_program = FALSE`
  - All
- Program Name
- State
- District
- Project Status
- Year
- Month
- Quarter

### Metrics and queries

#### State wise overall cumulative MI triggered number till date

Source:

- `program_data.total_triggered`
- fallback calculation: `started + in_progress + submitted`

Group by:

- `state_name`

#### Program wise cumulative MI triggered at state level

Source:

- `program_data`

Group by:

- `state_name`
- `program_name`

#### District wise overall cumulative MI triggered number

Source:

- `program_data`

Group by:

- `state_name`
- `district_name`

#### Program wise cumulative MI triggers at district level

Source:

- `program_data`

Group by:

- `state_name`
- `district_name`
- `program_name`

#### Month wise overall cumulative MI triggered numbers for year 2026 programs

Source:

- `project_statuses.project_start_date_user`
- `project_statuses.project_status`

Filter:

- year = `2026`

Group by:

- month
- program_name
- project_status

#### Project/Cycle/Program wise Adoption Rate

Source:

- numerator: triggered/adopted count from `project_statuses`
- denominator: `target_numbers.target_value`

Join keys:

- `program_name`
- `project_title`
- optionally `state_name`

Formula:

```text
adoption_rate = triggered_count / target_value * 100
```

#### Project/Cycle/Program wise Completion Rate

Source:

- `project_statuses`

Formula:

```text
completion_rate = submitted_count / triggered_count * 100
```

Group by:

- `program_name`
- `project_title`
- cycle if available from target sheet join

#### Number of Active Leaders

Source:

- `project_statuses.user_uuid`

Quarterly:

- count distinct `user_uuid` by quarter from `project_start_date_user`

Annually:

- count distinct `user_uuid` by year from `project_start_date_user`

## Implementation Phases

### Phase 1: Schema

1. Add `upload_history`.
2. Add dedupe indexes.
3. Confirm users table exists.
4. Re-run `schema.sql` in PostgreSQL.

### Phase 2: App foundation

1. Split DB helpers into `db.py`.
2. Keep login in `app.py`.
3. Add role-based navigation.
4. Add protected pages for upload and dashboard.

### Phase 3: Upload portal

1. Build CSV type selector.
2. Add required-column validation.
3. Add row cleaning helpers.
4. Add upload handlers for all four CSV types.
5. Add upload history writes.
6. Display stats and failed rows in UI.

### Phase 4: Dashboard

1. Add filters.
2. Add summary metric cards.
3. Add state/program/district tables.
4. Add month-wise chart for 2026 project statuses.
5. Add adoption and completion rate tables/charts.
6. Add active leaders quarterly and annual charts.

### Phase 5: Verification

1. Test login for all three users.
2. Test each upload type with reference CSV files.
3. Test duplicate upload behavior by uploading the same file twice.
4. Verify upload stats match inserted/skipped/failed counts.
5. Verify dashboard numbers against direct SQL queries.

## Open Questions Before Implementation

1. Should `historical_data_before_VAM` map to the existing `Excluding_VAM and PreVAM` file, and `historical_data_after_VAM` map to the existing `Including VAM` file?
2. Should duplicate `program_data` checks use only `program_name`, or should they use `program_name + state_name + district_name + historical_program`?
3. Should the default passwords remain the same as usernames for now?
4. Should `state_project_status` updates to existing `program_data` add to existing counters, or recompute counters from all rows in `project_statuses` each time?
