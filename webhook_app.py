import hmac
import json
import os
from urllib.parse import urlparse

import gspread
from flask import Flask, jsonify, request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


QUALIFYING_STATUSES = {"approved", "out of stock", "under review"}
LINK_HEADERS = {"link", "url", "product link", "product url"}

app = Flask(__name__)


def _column_index(headers, accepted_names, label):
    matches = [
        index
        for index, header in enumerate(headers)
        if header.strip().casefold() in accepted_names
    ]
    if len(matches) != 1:
        raise ValueError(f"The Google Sheet must have exactly one {label} column.")
    return matches[0]

# TODO: update this to only match FRC vendor URLs
def _url_item_id(value):
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    item_id = parsed.path.rstrip("/").rsplit("/", 1)[-1]
    return item_id or None

# Validate JSON schema returned from vendordiff webhook
def validate_payload(payload):
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Webhook payload must have version 1.")

    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("Webhook payload must contain an events array.")

    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Each event must be a JSON object.")
        variant = event.get("variant")
        if not isinstance(variant, dict):
            raise ValueError("Each event must contain a variant object.")
        variant_id = variant.get("id")
        if isinstance(variant_id, bool) or not isinstance(variant_id, (int, str)):
            raise ValueError("Each event variant must have a numeric or string id.")
        if not str(variant_id).strip():
            raise ValueError("Each event variant id must not be empty.")
    return events

# Match webhook events to rows in the PO sheet
def matching_events(payload, sheet_values):
    events = validate_payload(payload)

    if not sheet_values:
        raise ValueError("The configured Google Sheet is empty.")
    headers = sheet_values[0]
    link_index = _column_index(headers, LINK_HEADERS, "product URL")
    status_index = _column_index(headers, {"status"}, "status")

    qualifying_rows = {}
    for row in sheet_values[1:]:
        if max(link_index, status_index) >= len(row):
            continue
        item_id = _url_item_id(row[link_index])
        status = row[status_index].strip()
        if item_id and status.casefold() in QUALIFYING_STATUSES:
            qualifying_rows.setdefault(item_id, status)

    matches = []
    for event in events:
        variant_id = event["variant"]["id"]
        variant_id = str(variant_id).strip()

        if variant_id in qualifying_rows:
            matches.append((event, qualifying_rows[variant_id]))
    return matches


def _slack_escape(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

#WCP prices are all in cents lol
def _price(cents):
    if isinstance(cents, bool) or not isinstance(cents, (int, float)):
        return "unknown"
    return f"${cents / 100:,.2f}"

# Create the message to post in Slack purchasing channel
def _notification_text(matches, usergroup_id):
    lines = [f"<!subteam^{usergroup_id}> Product status notification"]
    for event, status in matches:
        product = event.get("product") or {}
        variant = event.get("variant") or {}
        vendor = event.get("vendor") or {}
        url = event.get("url", "")
        if not isinstance(product, dict) or not isinstance(variant, dict):
            raise ValueError("Product and variant fields must be JSON objects.")
        if not isinstance(vendor, dict):
            raise ValueError("Vendor field must be a JSON object.")
        if not isinstance(url, str) or _url_item_id(url) is None:
            raise ValueError("Each matched event must have a valid product URL.")

        vendor_name = _slack_escape(vendor.get("name", ""))
        title = _slack_escape(product.get("title", ""))
        variant_title = _slack_escape(variant.get("title", ""))
        safe_url = _slack_escape(url)
        lines.append(
            f"• *{vendor_name} {title}* ({variant_title}) — status: "
            f"*{_slack_escape(status)}* — price: {_price(event.get('price_cents'))} "
            f"(was {_price(event.get('old_price_cents'))}) — <{safe_url}|view item>"
        )
    return "\n".join(lines)


def _read_sheet():
    credentials = json.loads(os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"])
    sheets_client = gspread.service_account_from_dict(credentials)
    spreadsheet = sheets_client.open_by_key(os.environ["GOOGLE_SHEET_ID"])
    worksheet = spreadsheet.worksheet(os.getenv("GOOGLE_WORKSHEET_NAME", "Sheet1"))
    return worksheet.get_all_values()

#Recieve vendordiff webhook, try to call other functions to parse json and match to google sheet
@app.route("/webhook", methods=["POST"])
@app.route("/api/index", methods=["POST"])
def receive_webhook():
    secret = os.getenv("WEBHOOK_SECRET")
    if not secret:
        app.logger.error("WEBHOOK_SECRET is not configured correctly")
        return jsonify(error="Webhook endpoint is not configured"), 503

    supplied_secret = request.headers.get("X-Webhook-Secret", "")
    if not hmac.compare_digest(supplied_secret, secret):
        return jsonify(error="Unauthorized."), 401

    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify(error="Request body must contain valid JSON"), 400

    try:
        validate_payload(payload)
    except ValueError as error:
        return jsonify(error=str(error)), 400

    try:
        sheet_values = _read_sheet()
    except (KeyError, json.JSONDecodeError, gspread.exceptions.GSpreadException):
        app.logger.exception("Unable to read the configured Google Sheet.")
        return jsonify(error="Unable to read the configured Google Sheet."), 503

    try:
        matches = matching_events(payload, sheet_values)
    except ValueError as error:
        app.logger.error("Invalid Google Sheet configuration: %s", error)
        return jsonify(error="The configured Google Sheet is missing required columns"), 503

    if not matches:
        return jsonify(notified=False, matched_events=0), 200

    usergroup_id = os.getenv("SLACK_USERGROUP_ID", "").strip()
    channel_id = os.getenv("SLACK_NOTIFICATION_CHANNEL_ID", "").strip()
    bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if not usergroup_id or not channel_id or not bot_token:
        app.logger.error(
            "SLACK_USERGROUP_ID, SLACK_NOTIFICATION_CHANNEL_ID, and "
            "SLACK_BOT_TOKEN must be configured."
        )
        return jsonify(error="Slack notifications are not configured"), 503

    try:
        text = _notification_text(matches, usergroup_id)
        WebClient(token=bot_token).chat_postMessage(
            channel=channel_id,
            text=text,
            mrkdwn=True,
        )
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except SlackApiError:
        app.logger.exception("Slack rejected the notification")
        return jsonify(error="Slack could not send the notification"), 502

    return jsonify(notified=True, matched_events=len(matches)), 200


@app.get("/health")
@app.get("/api/index/health")
def health():
    return jsonify(status="ok")

#Local hook for testing without deployment, will probably delete
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "3000")))
