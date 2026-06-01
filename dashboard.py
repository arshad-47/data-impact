import pandas as pd
import streamlit as st

from db import fetch_dataframe


def add_optional_filters(where_parts, params, filters, table_alias=""):
    prefix = f"{table_alias}." if table_alias else ""

    if filters.get("vam") == "Pre VAM":
        where_parts.append(f"{prefix}historical_program = TRUE")
    elif filters.get("vam") == "Post VAM":
        where_parts.append(f"{prefix}historical_program = FALSE")

    if filters.get("program_name"):
        where_parts.append(f"{prefix}program_name = %s")
        params.append(filters["program_name"])

    if filters.get("state"):
        where_parts.append(f"{prefix}state_name = %s")
        params.append(filters["state"])

    if filters.get("district"):
        where_parts.append(f"{prefix}district_name = %s")
        params.append(filters["district"])


def where_clause(where_parts):
    if not where_parts:
        return ""
    return "WHERE " + " AND ".join(where_parts)


def load_filter_options():
    return {
        "programs": fetch_dataframe(
            """
            SELECT DISTINCT program_name
            FROM program_data
            WHERE program_name IS NOT NULL
            ORDER BY program_name;
            """
        ),
        "states": fetch_dataframe(
            """
            SELECT DISTINCT state_name
            FROM program_data
            WHERE state_name IS NOT NULL
            ORDER BY state_name;
            """
        ),
        "districts": fetch_dataframe(
            """
            SELECT DISTINCT district_name
            FROM program_data
            WHERE district_name IS NOT NULL
            ORDER BY district_name;
            """
        ),
        "project_statuses": fetch_dataframe(
            """
            SELECT DISTINCT project_status
            FROM project_statuses
            WHERE project_status IS NOT NULL
            ORDER BY project_status;
            """
        ),
    }


def selectbox_with_all(label, values):
    options = ["All"] + [value for value in values if pd.notna(value)]
    selected = st.sidebar.selectbox(label, options)
    return None if selected == "All" else selected


def render_dashboard():
    st.title("Dashboard")

    try:
        options = load_filter_options()
    except Exception as exc:
        st.error(f"Could not load dashboard filters: {exc}")
        return

    st.sidebar.header("Filters")
    vam = st.sidebar.selectbox("Pre/Post VAM", ["All", "Pre VAM", "Post VAM"])
    filters = {
        "vam": vam,
        "program_name": selectbox_with_all("Program Name", options["programs"]["program_name"].tolist()),
        "state": selectbox_with_all("State", options["states"]["state_name"].tolist()),
        "district": selectbox_with_all("District", options["districts"]["district_name"].tolist()),
        "project_status": selectbox_with_all(
            "Project Status", options["project_statuses"]["project_status"].tolist()
        ),
    }

    render_metric_cards(filters)
    render_program_data_tables(filters)
    render_project_status_tables(filters)
    render_upload_history()


def render_metric_cards(filters):
    where_parts = []
    params = []
    add_optional_filters(where_parts, params, filters)
    clause = where_clause(where_parts)

    data = fetch_dataframe(
        f"""
        SELECT
            coalesce(sum(coalesce(total_triggered, started + in_progress + submitted)), 0) AS total_triggered,
            coalesce(sum(started), 0) AS started,
            coalesce(sum(in_progress), 0) AS in_progress,
            coalesce(sum(submitted), 0) AS submitted
        FROM program_data
        {clause};
        """,
        params,
    )

    row = data.iloc[0]
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total MI Triggered", int(row["total_triggered"]))
    col2.metric("Started", int(row["started"]))
    col3.metric("In Progress", int(row["in_progress"]))
    col4.metric("Submitted", int(row["submitted"]))


def render_program_data_tables(filters):
    st.subheader("Cumulative MI Triggered")

    where_parts = []
    params = []
    add_optional_filters(where_parts, params, filters)
    clause = where_clause(where_parts)

    state_data = fetch_dataframe(
        f"""
        SELECT
            state_name, sum(started) AS started, sum(in_progress) AS in_progress, sum(submitted) AS submitted,
            sum(coalesce(total_triggered, started + in_progress + submitted)) AS total_triggered
        FROM program_data
        {clause}
        GROUP BY state_name
        ORDER BY total_triggered DESC;
        """,
        params,
    )
    st.write("State wise overall cumulative MI triggered")
    st.dataframe(state_data, use_container_width=True, hide_index=True)

    program_state_data = fetch_dataframe(
        f"""
        SELECT
            state_name,
            program_name, sum(started) AS started, sum(in_progress) AS in_progress, sum(submitted) AS submitted,
            sum(coalesce(total_triggered, started + in_progress + submitted)) AS total_triggered
        FROM program_data
        {clause}
        GROUP BY state_name, program_name
        ORDER BY state_name, total_triggered DESC;
        """,
        params,
    )
    st.write("Program wise cumulative MI triggered at state level")
    st.dataframe(program_state_data, use_container_width=True, hide_index=True)

    district_data = fetch_dataframe(
        f"""
        SELECT
            state_name,
            district_name,
            sum(started) AS started,
            sum(in_progress) AS in_progress,
            sum(submitted) AS submitted,
            sum(coalesce(total_triggered, started + in_progress + submitted)) AS total_triggered
        FROM program_data
        {clause}
        GROUP BY state_name, district_name
        ORDER BY state_name, total_triggered DESC;
        """,
        params,
    )
    st.write("District wise overall cumulative MI triggered")
    st.dataframe(district_data, use_container_width=True, hide_index=True)

    program_district_data = fetch_dataframe(
        f"""
        SELECT
            state_name,
            district_name,
            program_name, sum(started) AS started, sum(in_progress) AS in_progress, sum(submitted) AS submitted,
            sum(coalesce(total_triggered, started + in_progress + submitted)) AS total_triggered
        FROM program_data
        {clause}
        GROUP BY state_name, district_name, program_name
        ORDER BY state_name, district_name, total_triggered DESC;
        """,
        params,
    )
    st.write("Program wise cumulative MI triggered at district level")
    st.dataframe(program_district_data, use_container_width=True, hide_index=True)


def render_project_status_tables(filters):
    st.subheader("Project Status Metrics")

    where_parts = []
    params = []

    if filters.get("program_name"):
        where_parts.append("program_name = %s")
        params.append(filters["program_name"])
    if filters.get("state"):
        where_parts.append("declared_state = %s")
        params.append(filters["state"])
    if filters.get("district"):
        where_parts.append("district = %s")
        params.append(filters["district"])
    if filters.get("project_status"):
        where_parts.append("project_status = %s")
        params.append(filters["project_status"])

    base_clause = where_clause(where_parts)

    month_data = fetch_dataframe(
        f"""
        SELECT
            date_trunc('month', project_start_date_user)::date AS month,
            program_name,
            project_status,
            count(*) AS triggered_count
        FROM project_statuses
        {base_clause}
        {'AND' if base_clause else 'WHERE'} extract(year from project_start_date_user) = 2026
        GROUP BY month, program_name, project_status
        ORDER BY month, program_name, project_status;
        """,
        params,
    )
    st.write("Month wise cumulative MI triggered for 2026 programs")
    st.dataframe(month_data, use_container_width=True, hide_index=True)

    rate_filters = list(where_parts)
    rate_params = list(params)
    rate_clause = where_clause(rate_filters)
    rates = fetch_dataframe(
        f"""
        WITH project_counts AS (
            SELECT
                declared_state AS state_name,
                program_name,
                project_title,
                count(*) AS triggered_count,
                count(*) FILTER (WHERE project_status = 'submitted') AS submitted_count
            FROM project_statuses
            {rate_clause}
            GROUP BY declared_state, program_name, project_title
        )
        SELECT
            pc.state_name,
            pc.program_name,
            tn.cycle,
            pc.project_title,
            pc.triggered_count,
            pc.submitted_count,
            tn.target_value,
            round((pc.triggered_count::numeric / nullif(tn.target_value, 0)) * 100, 2) AS adoption_rate,
            round((pc.submitted_count::numeric / nullif(pc.triggered_count, 0)) * 100, 2) AS completion_rate
        FROM project_counts pc
        LEFT JOIN target_numbers tn
          ON lower(pc.state_name)=lower(tn.state_name)
         AND lower(pc.program_name)=lower(tn.program_name)
         AND lower(trim(pc.project_title)) = lower(trim(tn.project_title))
        ORDER BY pc.state_name, pc.program_name, pc.project_title;
        """,
        rate_params,
    )
    st.write("Project/Cycle/Program adoption and completion rate")
    st.dataframe(rates, use_container_width=True, hide_index=True)

    overall_active_users = fetch_dataframe(
        f"""
        WITH user_project_counts AS (
            SELECT
                declared_state AS state_name,
                user_uuid,
                count(DISTINCT project_id) AS projects_consumed
            FROM project_statuses
            {base_clause}
            {'AND' if base_clause else 'WHERE'} user_uuid IS NOT NULL
            GROUP BY declared_state, user_uuid
        ),
        state_totals AS (
            SELECT
                state_name,
                'Overall' AS projects_consumed,
                count(*) AS count_of_uuid,
                0 AS sort_order,
                NULL::bigint AS project_sort
            FROM user_project_counts
            GROUP BY state_name
        ),
        consumption_counts AS (
            SELECT
                state_name,
                projects_consumed::text AS projects_consumed,
                count(*) AS count_of_uuid,
                1 AS sort_order,
                projects_consumed AS project_sort
            FROM user_project_counts
            GROUP BY state_name, projects_consumed
        )
        SELECT
            state_name,
            projects_consumed,
            count_of_uuid
        FROM (
            SELECT * FROM state_totals
            UNION ALL
            SELECT * FROM consumption_counts
        ) active_users
        ORDER BY state_name, sort_order, project_sort;
        """,
        params,
    )
    st.write("Overall Active users")
    st.dataframe(overall_active_users, use_container_width=True, hide_index=True)

    active_leaders = fetch_dataframe(
        f"""
        WITH user_project_counts AS (
            SELECT
                extract(year from project_start_date_user)::int AS year,
                extract(quarter from project_start_date_user)::int AS quarter,
                user_uuid,
                count(DISTINCT project_id) AS projects_consumed
            FROM project_statuses
            {base_clause}
            {'AND' if base_clause else 'WHERE'} project_start_date_user IS NOT NULL
            GROUP BY
                extract(year from project_start_date_user),
                extract(quarter from project_start_date_user),
                user_uuid
        )
        SELECT
            year,
            quarter,
            count(*) AS active_leaders
        FROM user_project_counts
        WHERE projects_consumed >= 2
        GROUP BY
            year,
            quarter
        ORDER BY
            year,
            quarter;
        """,
        params,
    )
    st.write("Number of active leaders quarterly")
    st.dataframe(active_leaders, use_container_width=True, hide_index=True)


def render_upload_history():
    st.subheader("Recent Uploads")
    history = fetch_dataframe(
        """
        SELECT username, upload_type, file_name, status, stats, created_at, completed_at
        FROM upload_history
        ORDER BY created_at DESC
        LIMIT 20;
        """
    )
    st.dataframe(history, use_container_width=True, hide_index=True)
