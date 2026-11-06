import json


def format_sse(event: dict) -> str:
    event_type = event["event"]
    payload = {k: v for k, v in event.items() if k != "event"}
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"
