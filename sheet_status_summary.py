import json
import os
from collections import OrderedDict

import gspread
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv():
        return False

STATUSES = [
    "Approved",
    "Ordered",
    "Out of Stock",
]

COLUMNS = [
    "Item", "Num", "Needed By", "Requested By", "Order Date", "Total"
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
    selected_indexes = []
    for column_name in COLUMNS:
        index = _column_index(headers, {column_name.casefold()})
        if index is not None:
            selected_indexes.append(index)

    if not selected_indexes:
        return [header.strip() for header in headers]

    return [headers[index].strip() for index in selected_indexes]


def _selected_row_values(row, headers):
    selected_indexes = []
    for column_name in COLUMNS:
        index = _column_index(headers, {column_name.casefold()})
        if index is not None:
            selected_indexes.append(index)

    if not selected_indexes:
        return [cell.strip() for cell in row if cell.strip()]

    values = []
    for index in selected_indexes:
        if index < len(row):
            values.append(row[index].strip())
        else:
            values.append("")
    return values


def _format_row_for_slack(row, headers):
    values = _selected_row_values(row, headers)
    return " | ".join(values)


def _table_cell(value):
    text = str(value if value is not None else " ")
    if not text:
        text = " "
    return {"type": "raw_text", "text": text}


def _table_item_cell(row, headers):
    item_index = _column_index(headers, {"item"})
    link_value = _find_link_value(row, headers)

    if item_index is None or item_index >= len(row):
        return _table_cell(" ")

    item_value = row[item_index].strip()
    if not item_value:
        return _table_cell(" ")

    if link_value:
        return {
            "type": "rich_text",
            "elements": [{
                "type": "rich_text_section",
                "elements": [{
                    "type": "link",
                    "text": item_value,
                    "url": link_value,
                }],
            }],
        }

    return _table_cell(item_value)


def _build_status_table(headers, rows):
    selected_headers = _visible_headers(headers)
    column_count = len(selected_headers)
    column_settings = [{"is_wrapped": True} for _ in range(column_count)]
    if column_count:
        column_settings[-1]["align"] = "right"

    table_rows = [[_table_cell(header) for header in selected_headers]]
    for row in rows:
        row_values = []
        for header_name in COLUMNS:
            index = _column_index(headers, {header_name.casefold()})
            if index is None:
                continue
            value = row[index].strip() if index < len(row) else " "
            if header_name.casefold() == "item":
                row_values.append(_table_item_cell(row, headers))
            else:
                row_values.append(_table_cell(value))

        if len(row_values) < column_count:
            row_values.extend([_table_cell(" ")] * (column_count - len(row_values)))
        elif len(row_values) > column_count:
            row_values = row_values[:column_count]

        table_rows.append(row_values)

    return {
        "type": "table",
        "column_settings": column_settings,
        "rows": table_rows,
    }


def _chunk_table_rows(rows, max_rows_per_table=99):
    for index in range(0, len(rows), max_rows_per_table):
        yield rows[index:index + max_rows_per_table]


def build_slack_message(sheet_values):
    if not sheet_values:
        return {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "No rows found in the sheet."}}]}

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

    blocks = []
    for status in STATUSES:
        rows = grouped.get(status, [])
        if not rows:
            continue

        if status == 'Approved':
            group_id = os.getenv('SLACK_USERGROUP_ID', '').strip()
            status_text = 'Approved, Need to Purchase by'
            if group_id:
                status_text = f'{status_text} <!subteam^{group_id}>'
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": status_text},
            })
        elif status == 'Ordered':
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Ordered, Confirm if Received"},
            })
        else:
            blocks.append({
                "type": "header",
                "text": {"type": "plain_text", "text": status},
            })

        for chunk in _chunk_table_rows(rows):
            blocks.append(_build_status_table(headers, chunk))

    if not blocks:
        return {"blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "No rows found with a recognized status."}}]}

    return {"blocks": blocks}


app = App(
    token=os.getenv("SLACK_BOT_TOKEN", ""),
    signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
)


def send_summary_to_slack(channel_id=None, user_id=None):
    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("SLACK_BOT_TOKEN is not configured")

    target = user_id or channel_id or os.getenv("SLACK_NOTIFICATION_CHANNEL_ID", "").strip()
    if not target:
        raise ValueError("No Slack destination is configured")

    sheet_values = _read_sheet()
    message = build_slack_message(sheet_values)
    payload = {"channel": target, "text": "PO status update", "blocks": message["blocks"]}
    return WebClient(token=bot_token).chat_postMessage(**payload)


@app.command("/po-status")
def handle_po_status(ack, body, say):
    ack()
    try:
        send_summary_to_slack(channel_id=body.get("channel_id"))
        say("PO status summary sent.")
    except Exception as exc:  # pragma: no cover
        say(f"Unable to send PO summary: {exc}")


@app.event("app_mention")
def handle_app_mention(event, say):
    try:
        send_summary_to_slack(channel_id=event.get("channel"))
        say("PO status summary sent.")
    except Exception as exc:  # pragma: no cover
        say(f"Unable to send PO summary: {exc}")


def main():
    load_dotenv()
    if not os.getenv("SLACK_APP_TOKEN"):
        raise RuntimeError("SLACK_APP_TOKEN is required for Socket Mode.")
    SocketModeHandler(app, os.getenv("SLACK_APP_TOKEN")).start()


if __name__ == "__main__":
    main()
