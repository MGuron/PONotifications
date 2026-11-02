"""Vercel entry point for the PO Notifications Slack app."""

from slack_bolt.adapter.wsgi import SlackRequestHandler

from sheet_status_summary import app as bolt_app

handler = SlackRequestHandler(bolt_app, path="/slack/events")


def app(environ, start_response):
    path = (environ.get("PATH_INFO") or "").rstrip("/") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    print(f"DEBUG route path={path} method={method}")
    print(f"DEBUG headers: {dict((k, v) for k, v in environ.items() if k.startswith('HTTP_') or k in {'CONTENT_TYPE', 'CONTENT_LENGTH'})}")

    if path in {"/", "/api/index"}:
        body = b"PO Notifications app ready"
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        print("DEBUG returning ready response")
        start_response("200 OK", headers)
        return [body]

    if path == "/health":
        body = b"ok"
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        print("DEBUG returning health response")
        start_response("200 OK", headers)
        return [body]

    if path in {"/slack/events", "/summary", "/api/index/summary"}:
        print(f"DEBUG forwarding to Slack handler for {path}")
        return handler(environ, start_response)

    body = b"Not Found"
    headers = [
        ("Content-Type", "text/plain; charset=utf-8"),
        ("Content-Length", str(len(body))),
    ]
    print(f"DEBUG 404 for {path}")
    start_response("404 Not Found", headers)
    return [body]


if __name__ == "__main__":
    from sheet_status_summary import main
    print("doing stuff")
    main()

