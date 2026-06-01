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