#!/bin/sh
set -e

# Start the agentspan server (SQLite mode — no Postgres needed for a
# single-session personal-assistant agent) in the background.
java -jar /opt/agentspan/agentspan-runtime.jar &
AGENTSPAN_PID=$!

# Wait for it to become healthy before starting the FastAPI app, since
# AgentRuntime() fails fast if the server isn't reachable yet.
echo "Waiting for agentspan server to become healthy..."
until curl -fsS http://localhost:6767/actuator/health >/dev/null 2>&1; do
    if ! kill -0 "$AGENTSPAN_PID" 2>/dev/null; then
        echo "agentspan server process exited unexpectedly" >&2
        exit 1
    fi
    sleep 1
done
echo "agentspan server is healthy."

# Exec so uvicorn becomes PID 1 and receives container signals directly.
exec uvicorn agent.agentcore_app:app --host 0.0.0.0 --port 8080
