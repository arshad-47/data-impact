import re
from uuid import UUID


HEX_24_RE = re.compile(r"^[0-9a-f]{24}$")


def clean_string(value):
    if value is None:
        return None

    text = str(value).strip()
    if text.lower() in {"", "null", "nan", "none"}:
        return None

    return text


def clean_int(value):
    text = clean_string(value)
    if text is None:
        return 0

    try:
        return int(float(text.replace(",", "").replace(" ", "")))
    except ValueError:
        return 0


def clean_uuid(value):
    text = clean_string(value)
    if text is None:
        return None

    try:
        return str(UUID(text))
    except ValueError:
        return None


def clean_project_id(value):
    text = clean_string(value)
    if text is None:
        return None

    text = text.lower()
    if not HEX_24_RE.fullmatch(text):
        return None

    return text


def normalize_status(value):
    text = clean_string(value)
    if text is None:
        return None

    text = text.lower().replace("-", "_").replace(" ", "_")
    if text == "inprogress":
        return "in_progress"

    return text


def normalize_columns(dataframe):
    dataframe = dataframe.copy()
    dataframe.columns = [str(column).strip() for column in dataframe.columns]
    return dataframe


def missing_columns(dataframe, required_columns):
    return [column for column in required_columns if column not in dataframe.columns]
