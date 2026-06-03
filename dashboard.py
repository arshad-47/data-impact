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
        "years": fetch_dataframe(
            """
            SELECT DISTINCT extract(year from project_start_date_user)::int AS year
            FROM project_statuses
            WHERE project_start_date_user IS NOT NULL
            ORDER BY year DESC;
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
    year_values = [int(y) for y in options["years"]["year"].tolist() if pd.notna(y)]
    filters = {
        "vam": vam,
        "year": selectbox_with_all("Year", year_values),
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

    if filters.get("year"):
        where_parts.append("extract(year from project_start_date_user) = %s")
        params.append(filters["year"])
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

    selected_year = filters.get("year") or 2026
    month_data = fetch_dataframe(
        f"""
        SELECT
            date_trunc('month', project_start_date_user)::date AS month,
            program_name,
            project_status,
            count(*) AS triggered_count
        FROM project_statuses
        {base_clause}
        {'AND' if base_clause else 'WHERE'} extract(year from project_start_date_user) = %s
        GROUP BY month, program_name, project_status
        ORDER BY month, program_name, project_status;
        """,
        params + [selected_year],
    )
    st.write(f"Month wise cumulative MI triggered for {selected_year} programs")
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
                COUNT(*) AS triggered_count,
                COUNT(*) FILTER (
                    WHERE lower(project_status) = 'submitted'
                ) AS submitted_count
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
            ROUND((pc.triggered_count::numeric / NULLIF(tn.target_value, 0)) * 100, 2) AS adoption_rate,
            ROUND((pc.submitted_count::numeric / NULLIF(tn.target_value, 0)) * 100, 2) AS completion_rate
        FROM project_counts pc
        LEFT JOIN target_numbers tn
            ON LOWER(pc.state_name) = LOWER(tn.state_name)
           AND LOWER(pc.program_name) = LOWER(tn.program_name)
           AND LOWER(TRIM(pc.project_title)) = LOWER(TRIM(tn.project_title))
        ORDER BY
            pc.state_name,
            pc.program_name,
            pc.project_title;
        """,
        rate_params,
    )
    st.write("Project/Cycle/Program adoption and completion rate")
    st.dataframe(rates, use_container_width=True, hide_index=True)

    if not rates.empty:
        import plotly.express as px
        import plotly.graph_objects as go

        # Replace None/NaN with 0 for target_value so we can aggregate and plot safely
        rates["target_value"] = rates["target_value"].fillna(0)

        BRAND_COLORS = {
            "primary": "#4F46E5",
            "secondary": "#06B6D4",
            "accent": "#F97316",
            "success": "#10B981",
            "danger": "#EF4444",
            "muted": "#94A3B8",
        }
        CHART_FONT = dict(family="Inter, sans-serif", size=13, color="#1E293B")
        LAYOUT_BASE = dict(
            font=CHART_FONT,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(248,250,252,0.6)",
            margin=dict(l=20, r=20, t=50, b=20),
            legend=dict(
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#E2E8F0",
                borderwidth=1,
                font=dict(size=12),
            ),
        )

        # ── Chart 1: Horizontal bar – Adoption vs Completion by Project ──────────
        st.markdown("#### 📊 Adoption vs Completion Rate by Project")
        plot_rates = rates.dropna(subset=["project_title"]).copy()
        # Only keep rows where at least one rate has a real value
        plot_rates = plot_rates[
            plot_rates["adoption_rate"].fillna(0).gt(0) |
            plot_rates["completion_rate"].fillna(0).gt(0)
        ]
        plot_rates = plot_rates.sort_values("adoption_rate", ascending=True)
        # Truncate long titles for display
        # Prefix with cycle so same-title projects in different cycles get unique labels
        cycle_prefix = plot_rates["cycle"].apply(lambda c: f"[{c}] " if pd.notna(c) else "")
        plot_rates["short_title"] = cycle_prefix + plot_rates["project_title"].str.slice(0, 40) + plot_rates["project_title"].apply(lambda x: "…" if len(str(x)) > 40 else "")

        fig1 = go.Figure()
        fig1.add_trace(go.Bar(
            y=plot_rates["short_title"],
            x=plot_rates["adoption_rate"],
            name="Adoption Rate",
            orientation="h",
            marker_color=BRAND_COLORS["primary"],
            marker_line_width=0,
            hovertemplate="<b>%{customdata}</b><br>Adoption: %{x:.1f}%<extra></extra>",
            customdata=plot_rates["project_title"],
        ))
        fig1.add_trace(go.Bar(
            y=plot_rates["short_title"],
            x=plot_rates["completion_rate"],
            name="Completion Rate",
            orientation="h",
            marker_color=BRAND_COLORS["success"],
            marker_line_width=0,
            hovertemplate="<b>%{customdata}</b><br>Completion: %{x:.1f}%<extra></extra>",
            customdata=plot_rates["project_title"],
        ))
        fig1_layout = {**LAYOUT_BASE, "legend": {**LAYOUT_BASE["legend"], "orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "right", "x": 1}}
        fig1.update_layout(
            **fig1_layout,
            barmode="group",
            height=max(350, len(plot_rates) * 28),
            xaxis=dict(
                title="Rate (%)",
                showgrid=True,
                gridcolor="#E2E8F0",
                zeroline=False,
                ticksuffix="%",
            ),
            yaxis=dict(showgrid=False, automargin=True),
        )
        st.plotly_chart(fig1, use_container_width=True)





    overall_active_users = fetch_dataframe(
        f"""
        WITH user_project_counts AS (
            SELECT
                declared_state AS state_name,
                user_uuid,
                COUNT(DISTINCT project_id) AS projects_consumed
            FROM project_statuses
            {base_clause}
            {'AND' if base_clause else 'WHERE'} user_uuid IS NOT NULL
            GROUP BY declared_state, user_uuid
        ),
        active_users AS (
            SELECT *
            FROM user_project_counts
            WHERE projects_consumed >= 4
        ),
        state_totals AS (
            SELECT
                state_name,
                'Overall Active Users' AS projects_consumed,
                COUNT(*) AS count_of_users,
                0 AS sort_order,
                NULL::bigint AS project_sort
            FROM active_users
            GROUP BY state_name
        ),
        project_breakdown AS (
            SELECT
                state_name,
                projects_consumed::text,
                COUNT(*) AS count_of_users,
                1 AS sort_order,
                projects_consumed AS project_sort
            FROM active_users
            GROUP BY state_name, projects_consumed
        )
        SELECT
            state_name,
            projects_consumed,
            count_of_users
        FROM (
            SELECT * FROM state_totals
            UNION ALL
            SELECT * FROM project_breakdown
        ) x
        ORDER BY state_name, sort_order, project_sort;
        """,
        params,
    )
    st.write("Overall Users")
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
        WHERE projects_consumed >= 4
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
