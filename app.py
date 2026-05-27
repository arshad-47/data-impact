import pandas as pd
import streamlit as st

from dashboard import render_dashboard
from db import authenticate
from upload_handlers import ROLE_UPLOAD_TYPES, UPLOAD_TYPES, process_upload, read_upload, validate_upload


st.set_page_config(
    page_title="Program & Impact Analytics",
    layout="wide",
)


def login_page():
    st.title("Program & Impact Analytics")
    st.subheader("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", use_container_width=True)

    if not submitted:
        return

    if not username or not password:
        st.warning("Enter username and password.")
        return

    try:
        user = authenticate(username, password)
    except Exception as exc:
        st.error(f"Login failed: {exc}")
        return

    if user is None:
        st.error("Invalid username or password.")
        return

    st.session_state["user"] = user
    st.rerun()


def sidebar():
    user = st.session_state["user"]
    st.sidebar.write(f"Signed in as **{user['username']}**")
    st.sidebar.write(f"Role: `{user['role']}`")

    pages = ["Dashboard"]
    if ROLE_UPLOAD_TYPES.get(user["role"]):
        pages.insert(0, "Upload Portal")

    selected_page = st.sidebar.radio("Navigation", pages)

    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state.clear()
        st.rerun()

    return selected_page


def upload_portal():
    user = st.session_state["user"]
    allowed_types = ROLE_UPLOAD_TYPES.get(user["role"], [])

    st.title("Upload Portal")

    if not allowed_types:
        st.warning("You do not have upload access.")
        return

    upload_type = st.selectbox(
        "CSV type",
        allowed_types,
        format_func=lambda value: UPLOAD_TYPES[value],
    )
    uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

    if uploaded_file is None:
        return

    try:
        preview_df = read_upload(uploaded_file)
    except Exception as exc:
        st.error(f"Could not read CSV: {exc}")
        return
    finally:
        uploaded_file.seek(0)

    missing = validate_upload(preview_df, upload_type)
    if missing:
        st.error(f"Missing required columns: {', '.join(missing)}")
    else:
        st.success("CSV structure looks valid.")

    st.write("Preview")
    st.dataframe(preview_df.head(10), use_container_width=True, hide_index=True)

    if not st.button("Process Upload", type="primary", disabled=bool(missing)):
        return

    with st.spinner("Processing upload..."):
        try:
            stats, failed_rows = process_upload(uploaded_file, upload_type, user)
        except Exception as exc:
            st.error(f"Upload failed: {exc}")
            return

    st.success("Upload processed.")
    render_upload_stats(stats)

    if failed_rows:
        st.subheader("Failed Rows")
        st.dataframe(pd.DataFrame(failed_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No failed rows.")


def render_upload_stats(stats):
    st.subheader("Upload Stats")

    columns = st.columns(len(stats))
    for index, (label, value) in enumerate(stats.items()):
        columns[index].metric(label, value)


def main():
    if "user" not in st.session_state:
        login_page()
        return

    page = sidebar()
    if page == "Upload Portal":
        upload_portal()
    else:
        render_dashboard()


if __name__ == "__main__":
    main()
