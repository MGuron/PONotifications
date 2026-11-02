"""Vercel entry point for the PO Notifications Slack app."""

from slack_bolt.adapter.wsgi import SlackRequestHandler

from sheet_status_summary import app as bolt_app

handler = SlackRequestHandler(bolt_app, path="/api/index")


def app(environ, start_response):
    path = (environ.get("PATH_INFO") or "").rstrip("/") or "/"
    method = environ.get("REQUEST_METHOD", "GET")
    print(f"DEBUG route path={path} method={method}")
    print(f"DEBUG headers: {dict((k, v) for k, v in environ.items() if k.startswith('HTTP_') or k in {'CONTENT_TYPE', 'CONTENT_LENGTH'})}")

    if path in {"/api/index", "/slack/events", "/summary", "/api/index/summary"}:
        normalized_environ = dict(environ)
        normalized_environ["PATH_INFO"] = "/api/index"
        print(f"DEBUG forwarding to Slack handler for {path}")
        return handler(normalized_environ, start_response)

    if path in {"/", "/health"}:
        body = b"ok" if path == "/health" else b"PO Notifications app ready"
        headers = [
            ("Content-Type", "text/plain; charset=utf-8"),
            ("Content-Length", str(len(body))),
        ]
        print(f"DEBUG returning {path} response")
        start_response("200 OK", headers)
        return [body]

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

