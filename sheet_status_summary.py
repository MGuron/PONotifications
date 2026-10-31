import json
import os
from collections import OrderedDict

import gspread
from slack_sdk import WebClient

STATUSES = [
    "Approved",
    "Denied",
    "Ordered",
    "Out of Stock",
    "Inventoried",
]
STATUS_LOOKUP = {status.casefold(): status for status in STATUSES}


def _read_sheet():
    credentials = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    sheets_client = gspread.service_account_from_dict(credentials)
    spreadsheet = sheets_client.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    worksheet = spreadsheet.worksheet(os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1"))
    return worksheet.get_all_values()


def _status_column_index(headers):
    for index, header in enumerate(headers):
        if header.strip().casefold() == "status":
            return index
    raise ValueError("The spreadsheet must include a Status column.")


def _canonical_status(value):
    normalized = (value or "").strip()
    if not normalized:
        return "Unspecified"
    return STATUS_LOOKUP.get(normalized.casefold(), normalized)


def _column_index(headers, accepted_names):
    matches = [
        index
        for index, header in enumerate(headers)
        if header.strip().casefold() in accepted_names
    ]
    return matches[0] if len(matches) == 1 else None


def _is_url(value):
    if not value:
        return False
    parsed = __import__("urllib.parse").parse.urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _find_link_value(row, headers):
    link_index = _column_index(headers, {"link", "url"})
    if link_index is not None and link_index < len(row):
        candidate = row[link_index].strip()
        if _is_url(candidate):
            return candidate

    for value in row:
        stripped = value.strip()
        if _is_url(stripped):
            return stripped
    return None


def _visible_headers(headers):
    link_index = _column_index(headers, {"link", "url"})
    if link_index is None:
        return list(headers)
    visible = []
    for index, header in enumerate(headers):
        if index == link_index:
            continue
        visible.append(header.strip())
    return visible


def _format_row_for_slack(row, headers):
    item_index = _column_index(headers, {"item"})
    link_index = _column_index(headers, {"link", "url"})
    if item_index is None or item_index >= len(row):
        return " | ".join(cell.strip() for cell in row if cell.strip())

    item_value = row[item_index].strip()
    if not item_value:
        return " | ".join(cell.strip() for cell in row if cell.strip())

    link_value = _find_link_value(row, headers)
    if not link_value:
        return " | ".join(cell.strip() for cell in row if cell.strip())

    formatted = []
    for index, cell in enumerate(row):
        value = cell.strip()
        if index == link_index:
            continue
        if index == item_index:
            formatted.append(f"<{link_value}|{item_value}>")
        elif value:
            formatted.append(value)
    return " | ".join(formatted)


def build_slack_message(sheet_values):
    if not sheet_values:
        return "No rows found in the sheet."

    headers = sheet_values[0]
    status_index = _status_column_index(headers)

    grouped = OrderedDict((status, []) for status in STATUSES)
    for row in sheet_values[1:]:
        if not row or not any(cell.strip() for cell in row):
            continue
        if status_index >= len(row):
            continue
        status = _canonical_status(row[status_index])
        if status not in STATUS_LOOKUP.values():
            continue
        grouped.setdefault(status, []).append(row)

    sections = []
    for status in STATUSES:
        rows = grouped.get(status, [])
        if not rows:
            continue
        sections.append(f"*{status}*")
        sections.append(" | ".join(cell.strip() for cell in _visible_headers(headers)))
        for row in rows:
            sections.append(_format_row_for_slack(row, headers))
        sections.append("")

    if not sections:
        return "No rows found with a recognized status."

    return "\n".join(sections).strip()


def main():
    sheet_values = _read_sheet()
    message = build_slack_message(sheet_values)
    print(message)

    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    channel_id = os.getenv("SLACK_NOTIFICATION_CHANNEL_ID", "").strip()
    if bot_token and channel_id:
        WebClient(token=bot_token).chat_postMessage(
            channel=channel_id,
            text=message,
            mrkdwn=True,
        )


if __name__ == "__main__":
    main()
