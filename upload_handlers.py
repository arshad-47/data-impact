import pandas as pd
from psycopg2.extras import Json, execute_values

from db import get_connection
from utils import (
    clean_int,
    clean_project_id,
    clean_string,
    clean_uuid,
    missing_columns,
    normalize_columns,
    normalize_status,
)


UPLOAD_TYPES = {
    "historical_data_before_VAM": "Historical Data Before VAM",
    "historical_data_after_VAM": "Historical Data After VAM",
    "state_project_status": "State Project Status",
    "target_numbers": "Target Numbers",
}

ROLE_UPLOAD_TYPES = {
    "upload_master": list(UPLOAD_TYPES.keys()),
    "state_data_uploader": ["state_project_status"],
    "report_viewer": [],
}

PROJECT_STATUS_REQUIRED_COLUMNS = [
    "UUID",
    "User Type",
    "User sub type",
    "Declared State",
    "District",
    "Block",
    "School Name",
    "School ID",
    "Declared Board",
    "Org Name",
    "Program Name",
    "Program ID",
    "Project ID",
    "Project Title",
    "Project Objective",
    "Project start date of the user",
    "Project completion date of the user",
    "Project Duration",
    "Project last Synced date",
    "Project Status",
]

HISTORICAL_BEFORE_REQUIRED_COLUMNS = [
    "Program Name",
    "State Name",
    "District Name",
    "Started",
    "In-Progress",
    "Submitted",
]

HISTORICAL_AFTER_REQUIRED_COLUMNS = [
    "Program Name",
    "State Name",
    "Started",
    "In-Progress",
    "Submitted",
    "Total Triggered",
]

TARGET_REQUIRED_COLUMNS = [
    "State Name",
    "Program Type",
    "Program Name",
    "Cycle",
    "Project Title",
    "Target Name",
]


def read_upload(uploaded_file):
    dataframe = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
    return normalize_columns(dataframe)


def validate_upload(dataframe, upload_type):
    required_columns = {
        "state_project_status": PROJECT_STATUS_REQUIRED_COLUMNS,
        "historical_data_before_VAM": HISTORICAL_BEFORE_REQUIRED_COLUMNS,
        "historical_data_after_VAM": HISTORICAL_AFTER_REQUIRED_COLUMNS,
        "target_numbers": TARGET_REQUIRED_COLUMNS,
    }[upload_type]

    return missing_columns(dataframe, required_columns)


def base_stats(repeated_key):
    return {
        "total_rows_in_csv": 0,
        "sucessfully_insereted": 0,
        repeated_key: 0,
        "failed_insertion": 0,
    }


def record_upload(cursor, user, upload_type, file_name, status, stats, failed_rows):
    cursor.execute(
        """
        INSERT INTO upload_history (
            uploaded_by, username, upload_type, file_name, status, stats,
            failed_rows, created_at, completed_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW());
        """,
        (
            user["user_id"],
            user["username"],
            upload_type,
            file_name,
            status,
            Json(stats),
            Json(failed_rows),
        ),
    )


def upload_status(failed_rows):
    return "completed_with_errors" if failed_rows else "completed"


def begin_row_savepoint(cursor):
    cursor.execute("SAVEPOINT row_insert;")


def release_row_savepoint(cursor):
    cursor.execute("RELEASE SAVEPOINT row_insert;")


def rollback_row_savepoint(cursor):
    cursor.execute("ROLLBACK TO SAVEPOINT row_insert;")
    cursor.execute("RELEASE SAVEPOINT row_insert;")


def process_upload(uploaded_file, upload_type, user):
    dataframe = read_upload(uploaded_file)
    missing = validate_upload(dataframe, upload_type)

    if missing:
        repeated_key = (
            "repeteed_projectids_skipped"
            if upload_type == "state_project_status"
            else "repeteed_programs_skipped"
        )
        stats = base_stats(repeated_key)
        stats["total_rows_in_csv"] = len(dataframe)
        failed_rows = [{"row_number": None, "row_data": {}, "reason": f"Missing columns: {', '.join(missing)}"}]
        with get_connection() as connection:
            with connection:
                with connection.cursor() as cursor:
                    record_upload(cursor, user, upload_type, uploaded_file.name, "failed", stats, failed_rows)
        return stats, failed_rows

    if upload_type == "state_project_status":
        return process_project_status_upload(dataframe, uploaded_file.name, upload_type, user)
    if upload_type == "historical_data_before_VAM":
        return process_historical_before_upload(dataframe, uploaded_file.name, upload_type, user)
    if upload_type == "historical_data_after_VAM":
        return process_historical_after_upload(dataframe, uploaded_file.name, upload_type, user)
    if upload_type == "target_numbers":
        return process_target_numbers_upload(dataframe, uploaded_file.name, upload_type, user)

    raise ValueError(f"Unsupported upload type: {upload_type}")


def process_project_status_upload(dataframe, file_name, upload_type, user):
    stats = base_stats("repeteed_projectids_skipped")
    stats["total_rows_in_csv"] = len(dataframe)

    failed_rows = []
    inserted_groups = {}
    seen_project_ids = set()
    rows_to_insert = []

    with get_connection() as connection:
        with connection:
            with connection.cursor() as cursor:
                csv_project_ids = []

                for _, row in dataframe.iterrows():
                    project_id = clean_project_id(row.get("Project ID"))

                    if project_id:
                        csv_project_ids.append(project_id)

                cursor.execute(
                    """
                    SELECT id
                    FROM project_statuses
                    WHERE id = ANY(%s)
                    """,
                    (csv_project_ids,),
                )

                existing_project_ids = {row[0] for row in cursor.fetchall()}

                for index, row in dataframe.iterrows():

                    row_number = index + 2
                    project_id = clean_project_id(row.get("Project ID"))
                    user_uuid = clean_uuid( row.get("UUID"))

                    program_name = clean_string(row.get("Program Name"))
                    state = clean_string(row.get("Declared State"))
                    district = clean_string(row.get("District"))
                    status = normalize_status(row.get("Project Status"))

                    if project_id is None:
                        failed_rows.append(
                            {
                                "row_number": row_number,
                                "row_data": row.to_dict(),
                                "reason": "Invalid or missing Project ID",
                            }
                        )
                        stats["failed_insertion"] += 1
                        continue

                    if not program_name or not state:
                        failed_rows.append(
                            {
                                "row_number": row_number,
                                "row_data": row.to_dict(),
                                "reason": "Program Name and Declared State are required",
                            }
                        )
                        stats["failed_insertion"] += 1
                        continue

                    if project_id in seen_project_ids:
                        stats["repeteed_projectids_skipped"] += 1
                        continue

                    seen_project_ids.add(project_id)

                    if project_id in existing_project_ids:
                        stats["repeteed_projectids_skipped"] += 1
                        continue

                    rows_to_insert.append(
                        (
                            project_id,
                            user_uuid,
                            clean_string(row.get("User Type")),
                            clean_string(row.get("User sub type")),
                            state,
                            district,
                            clean_string(row.get("Block")),
                            clean_string(row.get("School Name")),
                            clean_string(row.get("School ID")),
                            clean_string(row.get("Declared Board")),
                            clean_string(row.get("Org Name")),
                            program_name,
                            clean_string(row.get("Program ID")),
                            project_id,
                            clean_string(row.get("Project Title")),
                            clean_string(row.get("Project Objective")),
                            clean_string(row.get("Project start date of the user")),
                            clean_string(row.get("Project completion date of the user")),
                            clean_string(row.get("Project Duration")),
                            clean_string(row.get("Project last Synced date")),
                            status,
                            clean_string(row.get("Certificate Status")),
                        )
                    )

                    stats["sucessfully_insereted"] += 1

                    group_key = (
                        program_name,
                        state,
                        district,
                    )

                    if group_key not in inserted_groups:
                        inserted_groups[group_key] = {
                            "started": 0,
                            "in_progress": 0,
                            "submitted": 0,
                        }

                    if status in inserted_groups[group_key]:
                        inserted_groups[group_key][status] += 1

                if rows_to_insert:
                    execute_values(
                        cursor,
                        """
                        INSERT INTO project_statuses (
                            id,
                            user_uuid,
                            user_type,
                            user_sub_type,
                            declared_state,
                            district,
                            block,
                            school_name,
                            school_id,
                            declared_board,
                            org_name,
                            program_name,
                            program_id,
                            project_id,
                            project_title,
                            project_objective,
                            project_start_date_user,
                            project_completion_date_user,
                            project_duration,
                            project_last_synced_date,
                            project_status,
                            certificate_status
                        )
                        VALUES %s
                        """,
                        rows_to_insert,
                        page_size=1000,
                    )

                upsert_program_aggregates(
                    cursor,
                    inserted_groups
                )
                
                record_upload( cursor, user, upload_type, file_name, upload_status(failed_rows), stats, failed_rows,)

    return stats, failed_rows


def upsert_program_aggregates(cursor, inserted_groups):
    for (program_name, state, district), counts in inserted_groups.items():
        total = counts["started"] + counts["in_progress"] + counts["submitted"]
        cursor.execute(
            """
            SELECT program_id
            FROM program_data
            WHERE lower(program_name) = lower(%s)
              AND lower(state_name) = lower(%s)
              AND lower(coalesce(district_name, '')) = lower(coalesce(%s, ''))
              AND historical_program = FALSE
            LIMIT 1;
            """,
            (program_name, state, district),
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE program_data
                SET started = coalesce(started, 0) + %s,
                    in_progress = coalesce(in_progress, 0) + %s,
                    submitted = coalesce(submitted, 0) + %s,
                    total_triggered = coalesce(total_triggered, 0) + %s
                WHERE program_id = %s;
                """,
                (counts["started"], counts["in_progress"], counts["submitted"], total, existing[0]),
            )
        else:
            cursor.execute(
                """
                INSERT INTO program_data (
                    program_name, state_name, district_name, started, in_progress,
                    submitted, submitted_with_evidence, total_triggered,
                    historical_program
                )
                VALUES (%s, %s, %s, %s, %s, %s, NULL, %s, FALSE);
                """,
                (
                    program_name,
                    state,
                    district,
                    counts["started"],
                    counts["in_progress"],
                    counts["submitted"],
                    total,
                ),
            )

from pathlib import Path


def update_historical_program_flags(cursor):
    """
    Updates historical_program flag based on
    fixed_program/only_VAM_PreVAM.csv
    """

    csv_path = (
        Path(__file__).resolve().parent
        / "fixed_program"
        / "only_VAM_PreVAM.csv"
    )

    if not csv_path.exists():
        return

    historical_df = pd.read_csv(csv_path)

    historical_programs = {
        str(program).strip().lower()
        for program in historical_df["Program Name"].dropna()
    }

    cursor.execute(
        """
        UPDATE program_data
        SET historical_program = FALSE
        """
    )

    cursor.execute(
        """
        UPDATE program_data
        SET historical_program = TRUE
        WHERE lower(trim(program_name)) = ANY(%s)
        """,
        (list(historical_programs),)
    )

def process_historical_before_upload(dataframe, file_name, upload_type, user):
    stats = base_stats("repeteed_programs_skipped")
    stats["total_rows_in_csv"] = len(dataframe)

    failed_rows = []
    rows_to_insert = []

    with get_connection() as connection:
        with connection:
            with connection.cursor() as cursor:

                cursor.execute(
                    """
                    SELECT
                        lower(program_name),
                        lower(state_name),
                        lower(coalesce(district_name, ''))
                    FROM program_data
                    """
                )

                existing_programs = {
                    (
                        row[0],
                        row[1],
                        row[2]
                    )
                    for row in cursor.fetchall()
                }

                for index, row in dataframe.iterrows():
                    row_number = index + 2
                    program_name = clean_string(row.get("Program Name"))
                    state = clean_string(row.get("State Name"))
                    district = clean_string(row.get("District Name"))
                    started = clean_int(row.get("Started"))
                    in_progress = clean_int(row.get("In-Progress"))
                    submitted = clean_int(row.get("Submitted"))

                    if not program_name or not state:
                        failed_rows.append(
                            {
                                "row_number": row_number,
                                "row_data": row.to_dict(),
                                "reason": (
                                    "Program Name and State Name are required"
                                ),
                            }
                        )

                        stats["failed_insertion"] += 1
                        continue

                    lookup_key = (
                        program_name.lower(),
                        state.lower(),
                        (district or "").lower()
                    )

                    if lookup_key in existing_programs:
                        stats["repeteed_programs_skipped"] += 1
                        continue

                    existing_programs.add(lookup_key)

                    rows_to_insert.append(
                        (
                            program_name,state,district,
                            started,in_progress, submitted,
                            started + in_progress + submitted,
                        )
                    )

                    stats["sucessfully_insereted"] += 1

                # Bulk insert
                if rows_to_insert:
                    execute_values(
                        cursor,
                        """
                        INSERT INTO program_data (
                            program_name,
                            state_name,
                            district_name,
                            started,
                            in_progress,
                            submitted,
                            submitted_with_evidence,
                            total_triggered,
                            historical_program
                        )
                        VALUES %s
                        """,
                        [
                            (
                                row[0],   # program_name
                                row[1],   # state
                                row[2],   # district
                                row[3],   # started
                                row[4],   # in_progress
                                row[5],   # submitted
                                None,
                                row[6],   # total_triggered
                                True
                            )
                            for row in rows_to_insert
                        ],
                        page_size=1000,
                    )

                update_historical_program_flags(cursor)

                record_upload(
                    cursor,
                    user,
                    upload_type,
                    file_name,
                    upload_status(failed_rows),
                    stats,
                    failed_rows,
                )

    return stats, failed_rows


def process_historical_after_upload(dataframe, file_name, upload_type, user):
    stats = base_stats("repeteed_programs_skipped")
    stats["total_rows_in_csv"] = len(dataframe)
    failed_rows = []
    rows_to_insert = []

    with get_connection() as connection:
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        lower(program_name),
                        lower(state_name),
                        lower(coalesce(district_name, ''))
                    FROM program_data
                    """
                )
                
                existing_programs_district = {
                    (row[0], row[1], row[2])
                    for row in cursor.fetchall()
                }
                
                existing_programs_state = {
                    (k[0], k[1]) for k in existing_programs_district
                }

                for index, row in dataframe.iterrows():
                    row_number = index + 2
                    program_name = clean_string(row.get("Program Name"))
                    state = clean_string(row.get("State Name"))
                    district = clean_string(row.get("District Name"))
                    started = clean_int(row.get("Started"))
                    in_progress = clean_int(row.get("In-Progress"))
                    submitted = clean_int(row.get("Submitted"))
                    submitted_with_evidence = clean_int(row.get("Submitted projects with evidence"))
                    total_triggered = clean_int(row.get("Total Triggered"))

                    if not program_name or not state:
                        failed_rows.append(
                            {
                                "row_number": row_number,
                                "row_data": row.to_dict(),
                                "reason": "Program Name and State Name are required",
                            }
                        )
                        stats["failed_insertion"] += 1
                        continue

                    # Smarter duplicate check to avoid double-counting
                    if district:
                        lookup_key = (program_name.lower(), state.lower(), district.lower())
                        if lookup_key in existing_programs_district:
                            stats["repeteed_programs_skipped"] += 1
                            continue
                        existing_programs_district.add(lookup_key)
                        existing_programs_state.add((program_name.lower(), state.lower()))
                    else:
                        # If row has NO district (it's a state rollup), skip if WE HAVE ANY DATA 
                        # for this program+state (either district data from 'Before VAM' or a previous state rollup)
                        lookup_key = (program_name.lower(), state.lower())
                        if lookup_key in existing_programs_state:
                            stats["repeteed_programs_skipped"] += 1
                            continue
                        existing_programs_district.add((program_name.lower(), state.lower(), ""))
                        existing_programs_state.add(lookup_key)

                    rows_to_insert.append(
                        (
                            program_name,
                            state,
                            district,
                            started,
                            in_progress,
                            submitted,
                            submitted_with_evidence,
                            total_triggered,
                        )
                    )
                    stats["sucessfully_insereted"] += 1

                if rows_to_insert:
                    execute_values(
                        cursor,
                        """
                        INSERT INTO program_data (
                            program_name, state_name, district_name, started,
                            in_progress, submitted, submitted_with_evidence,
                            total_triggered, historical_program
                        )
                        VALUES %s
                        """,
                        [
                            (
                                r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], False
                            )
                            for r in rows_to_insert
                        ],
                        page_size=1000,
                    )

                update_historical_program_flags(cursor)
                record_upload(cursor, user, upload_type, file_name, upload_status(failed_rows), stats, failed_rows)

    return stats, failed_rows


def program_data_exists(cursor, program_name, state, district, historical_program):
    cursor.execute(
        """
        SELECT 1
        FROM program_data
        WHERE lower(program_name) = lower(%s)
          AND lower(state_name) = lower(%s)
          AND lower(coalesce(district_name, '')) = lower(coalesce(%s, ''))
          AND historical_program = %s
        LIMIT 1;
        """,
        (program_name, state, district, historical_program),
    )
    return cursor.fetchone() is not None


def process_target_numbers_upload(dataframe, file_name, upload_type, user):
    stats = base_stats("repeteed_programs_skipped")
    stats["total_rows_in_csv"] = len(dataframe)
    failed_rows = []

    with get_connection() as connection:
        with connection:
            with connection.cursor() as cursor:
                for index, row in dataframe.iterrows():
                    row_number = index + 2
                    state = clean_string(row.get("State Name"))
                    program_type = clean_string(row.get("Program Type"))
                    program_name = clean_string(row.get("Program Name"))
                    cycle = clean_string(row.get("Cycle"))
                    project_title = clean_string(row.get("Project Title"))
                    target_value = clean_int(row.get("Target Name"))

                    if not state or not program_name:
                        failed_rows.append(
                            {
                                "row_number": row_number,
                                "row_data": row.to_dict(),
                                "reason": "State Name and Program Name are required",
                            }
                        )
                        stats["failed_insertion"] += 1
                        continue

                    if target_number_exists(cursor, state, program_name, cycle, project_title):
                        stats["repeteed_programs_skipped"] += 1
                        continue

                    begin_row_savepoint(cursor)
                    try:
                        cursor.execute(
                            """
                            INSERT INTO target_numbers (
                                state_name, program_type, program_name, cycle,
                                project_title, target_value
                            )
                            VALUES (%s, %s, %s, %s, %s, %s);
                            """,
                            (state, program_type, program_name, cycle, project_title, target_value),
                        )
                    except Exception as exc:
                        rollback_row_savepoint(cursor)
                        failed_rows.append({"row_number": row_number, "row_data": row.to_dict(), "reason": str(exc)})
                        stats["failed_insertion"] += 1
                    else:
                        release_row_savepoint(cursor)
                        stats["sucessfully_insereted"] += 1

                record_upload(cursor, user, upload_type, file_name, upload_status(failed_rows), stats, failed_rows)

    return stats, failed_rows


def target_number_exists(cursor, state, program_name, cycle, project_title):
    cursor.execute(
        """
        SELECT 1
        FROM target_numbers
        WHERE lower(state_name) = lower(%s)
          AND lower(program_name) = lower(%s)
          AND lower(coalesce(cycle, '')) = lower(coalesce(%s, ''))
          AND lower(coalesce(project_title, '')) = lower(coalesce(%s, ''))
        LIMIT 1;
        """,
        (state, program_name, cycle, project_title),
    )
    return cursor.fetchone() is not None
