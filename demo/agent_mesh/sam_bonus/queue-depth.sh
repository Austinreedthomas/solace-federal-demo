#!/usr/bin/env bash
# Print depth of the primary operator's guaranteed queue. Never prints secrets.
set -euo pipefail
cd "$(dirname "$0")/proj" || exit 1
PYTHONPATH=src ../.venv/bin/python - <<'PY'
from ops_watch.semp import operator_queue_name, queue_stats, queue_subscriptions, client_connection_count, operator_username
name = operator_queue_name()
s = queue_stats(name)
subs = ", ".join(queue_subscriptions(name)) or "(none)"
try:
    clients = client_connection_count(operator_username())
    client_bit = f"  operatorClients={clients}"
except Exception:
    client_bit = ""
print(
    f"{s['queueName']}  spooled={s['spooledMsgCount']}  unacked={s['txUnackedMsgCount']}  "
    f"binds={s['bindCount']}{client_bit}  subscriptions={subs}"
)
PY
