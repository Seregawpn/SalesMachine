"""A minimal stdio echo server for testing ProcessTransport.

Reads one JSON line at a time from stdin. For a "thread/start" request,
replies with a thread_created result. For a "turn/start" request, emits
an agentMessage event echoing the prompt back, then a turn/completed
event. Ignores everything else (including "initialize"/"initialized",
which ProcessTransport's own tests don't need a reply to).
"""
import json
import sys


def main() -> None:
    for raw_line in sys.stdin:
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        message = json.loads(raw_line)
        method = message.get("method")

        if method == "thread/start":
            response = {"id": message["id"], "result": {"thread": {"id": "fake-thread-1"}}}
            print(json.dumps(response), flush=True)

        elif method == "turn/start":
            prompt = message["params"]["input"][0]["text"]
            agent_message = {
                "method": "item/completed",
                "params": {"item": {"type": "agentMessage", "text": f"echo: {prompt}"}},
            }
            print(json.dumps(agent_message), flush=True)
            print(json.dumps({"method": "turn/completed", "params": {}}), flush=True)


if __name__ == "__main__":
    main()
