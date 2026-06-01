import os
from contextlib import contextmanager

import pandas as pd
import psycopg2
import streamlit as st

from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv()


def get_database_url():
    return os.getenv("DATABASE_URL")


@st.cache_resource
def get_cached_connection():
    database_url = get_database_url()

    if not database_url:
        raise RuntimeError(
            "DATABASE_URL is not configured."
        )

    return psycopg2.connect(database_url)


@contextmanager
def get_connection():
    connection = get_cached_connection()

    try:
        yield connection
    except Exception:
        connection.rollback()
        raise


def authenticate(username, password):
    query = """
        SELECT user_id, username, role
        FROM users
        WHERE lower(username) = lower(%s)
          AND active = TRUE
          AND password_hash = crypt(%s, password_hash)
        LIMIT 1;
    """

    with get_connection() as connection:
        with connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

            cursor.execute(
                query,
                (username, password)
            )

            row = cursor.fetchone()

    if row is None:
        return None

    return {
        "user_id": str(row["user_id"]),
        "username": row["username"],
        "role": row["role"],
    }


def fetch_dataframe(query, params=None):
    with get_connection() as connection:
        return pd.read_sql_query(
            query,
            connection,
            params=params
        )