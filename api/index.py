"""Vercel entry point for the PO Notifications Slack app."""

from slack_bolt.adapter.wsgi import SlackRequestHandler

from sheet_status_summary import app as bolt_app

handler = SlackRequestHandler(bolt_app, path="/slack/events")


def app(environ, start_response):
    path = (environ.get("PATH_INFO") or "").rstrip("/") or "/"

    if path in {"/", "/api/index"}:
        body = b"PO Notifications app ready"
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        start_response("200 OK", headers)
        return [body]

    if path == "/health":
        body = b"ok"
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        start_response("200 OK", headers)
        return [body]

    if path in {"/slack/events", "/summary", "/api/index/summary"}:
        return handler(environ, start_response)

    body = b"Not Found"
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    start_response("404 Not Found", headers)
    return [body]


if __name__ == "__main__":
    from sheet_status_summary import main

    main()

