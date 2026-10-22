## TODO
- filter rows in PO sheet to avoid non-supported vendors
- Add link cleaning to the app?

# PO Notifications Slack app

This app accepts product events from a webhook from vendordiff.com, looks up each event's `variant.id`
in the configured Google Sheet using the final segment of the row's product URL,
and posts one Slack message when a matching row has a status of `Approved`,
`Out of Stock`, or `Under Review`.

The worksheet must have a header row containing one product URL column named
`Link`, `URL`, `Product Link`, or `Product URL`, plus one `Status` column.
For example:

| Link | Status |
| --- | --- |
| https://andymark.com/products/biocore-frc-scoring-element-pre-order?variant=46355672170668 | Approved |

## Slack setup

1. Create or update the Slack app using `manifest.yaml`, install it in the
   workspace, and copy its bot token.
2. Invite the bot to the channel where notifications should be posted.
3. Create or choose a Slack user group for the notification role and copy its
   group ID. The app mentions the group with a Slack `<!subteam^GROUP_ID>` mention.

## Configuration

Set these environment variables in the deployment environment:

| Variable | Description |
| --- | --- |
| `SLACK_BOT_TOKEN` | Bot token for the installed Slack app (`xoxb-...`). |
| `SLACK_USERGROUP_ID` | Slack user group ID to notify. |
| `SLACK_NOTIFICATION_CHANNEL_ID` | Channel ID where the bot posts notifications. |
| `WEBHOOK_SECRET` | Shared secret required in the `X-Webhook-Secret` request header. |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Google service account credentials as a JSON string. |
| `GOOGLE_SHEET_ID` | ID of the spreadsheet containing product rows. |
| `GOOGLE_WORKSHEET_NAME` | Worksheet tab name; defaults to `Sheet1`. |

Share the spreadsheet with the service account email as a Viewer.

## Deploy to Vercel

The repository is configured to deploy `api/index.py` as a Python function.
Vercel installs the packages in the root `requirements.txt`, and `vercel.json`
maps `/webhook` and `/health` to the function. No separate web server or Slack
Socket Mode process is required.

1. Import this repository into Vercel and set the project root to the repository
   root (the folder containing `requirements.txt` and `vercel.json`).
2. Add every required variable from the configuration table to the Vercel
   project. Add them to each environment (Production, Preview, or Development)
   where the app should run. Paste the service account JSON as one JSON value.
3. Deploy the project and share the Google Sheet with the service account email
   as a Viewer.
4. Configure the vendor webhook to send `POST` requests to
   `https://YOUR-VERCEL-DOMAIN/webhook`, with the JSON payload and
   `X-Webhook-Secret` header.
5. Check `https://YOUR-VERCEL-DOMAIN/health`; a healthy deployment returns
   `{"status":"ok"}`.

The function has a 30-second maximum duration configured in `vercel.json`.
Vercel account and plan limits still apply.

To run locally, install dependencies with:

```sh
python -m pip install -r requirements.txt
```

Set the environment variables locally and run:

```sh
python webhook_app.py
```

## Webhook payload

The endpoint accepts version 1 payloads in the following shape:

```json
{
  "version": 1,
  "events": [
    {
      "id": 1234,
      "type": "price_change",
      "occurred_at": "2026-10-05T16:00:00.000Z",
      "url": "https://vendordiff.com/v/wcp/3-gear/7",
      "vendor": { "slug": "wcp", "name": "WCP" },
      "product": {
        "id": 3,
        "title": "Gear",
        "image_url": "https://cdn.example.com/gear.png"
      },
      "variant": { "id": 7, "title": "12T", "sku": "WCP-0001" },
      "price_cents": 1200,
      "old_price_cents": 1000,
      "old_title": null
    }
  ]
}
```

Send the shared secret as `X-Webhook-Secret`. Non-matching events return HTTP
200 without posting to Slack; invalid payloads return HTTP 400.
