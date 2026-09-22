"""
Create the alert policies for the trade compliance service.

Run once, idempotently -- an existing policy with the same display name is left
alone rather than duplicated.

    python infra/monitoring/create_alerts.py

WHY A SCRIPT AND NOT gcloud

`gcloud alpha monitoring policies create` needs the alpha component, which is not
installed on the deployment machine and cannot be installed non-interactively from
a script. The REST API needs no component. It also keeps the thresholds in version
control, which a console-clicked policy would not be.

WHAT IS ALERTED, AND WHY EACH ONE

1. The service is down. An uptime check with nobody watching it is just a graph.
2. The service is answering 5xx. A service that is up and erroring is invisible to
   an uptime check on /health, because /health does not touch Firestore or Nebius.
3. A tenant hit its spend ceiling. This one is not a fault -- it is the cost control
   working -- but it means a customer's screening has stopped, and that must not be
   discovered by the customer.

DELIBERATELY NOT ALERTED: latency. The pipeline runs multi-agent inference and a
p95 in the tens of seconds is normal for it, so a latency alert here would fire
constantly and train everyone to ignore the channel.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request

PROJECT = "vf-fraud-detection-phuochoa"
SERVICE = "vf-logistics"
BASE = f"https://monitoring.googleapis.com/v3/projects/{PROJECT}"


def token() -> str:
    """An access token from the local gcloud credentials."""
    result = subprocess.run(
        ["gcloud", "auth", "print-access-token"],
        capture_output=True,
        text=True,
        shell=True,
        check=True,
    )
    return result.stdout.strip()


def call(method: str, path: str, body: dict | None = None) -> dict:
    request = urllib.request.Request(
        f"{BASE}/{path}",
        method=method,
        data=json.dumps(body).encode() if body else None,
        headers={
            "Authorization": f"Bearer {token()}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.loads(response.read() or "{}")
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")
        raise SystemExit(f"{method} {path} failed: HTTP {error.code}\n{detail}")


def channels() -> list[str]:
    """Every enabled notification channel. Alerting nobody is not alerting."""
    found = call("GET", "notificationChannels").get("notificationChannels", [])
    enabled = [c["name"] for c in found if c.get("enabled")]
    if not enabled:
        raise SystemExit(
            "No enabled notification channel. Create one first, or these policies "
            "will fire into nothing."
        )
    return enabled


def existing() -> set[str]:
    found = call("GET", "alertPolicies").get("alertPolicies", [])
    return {p.get("displayName", "") for p in found}


def policies(notify: list[str]) -> list[dict]:
    return [
        {
            "displayName": "vf-logistics is unreachable",
            "documentation": {
                "content": (
                    "The /health endpoint stopped answering from multiple regions. "
                    "Check the Cloud Run revision and its logs. /health does not "
                    "touch Firestore or Nebius, so this means the container itself "
                    "is not serving."
                ),
                "mimeType": "text/markdown",
            },
            "combiner": "OR",
            "conditions": [
                {
                    "displayName": "uptime check failing",
                    "conditionThreshold": {
                        "filter": (
                            'metric.type="monitoring.googleapis.com/uptime_check/check_passed" '
                            'AND resource.type="uptime_url"'
                        ),
                        "aggregations": [
                            {
                                "alignmentPeriod": "300s",
                                "perSeriesAligner": "ALIGN_FRACTION_TRUE",
                            }
                        ],
                        "comparison": "COMPARISON_LT",
                        # Below 100% passing across the checked regions. Two
                        # consecutive windows, so one flaky probe from one region
                        # does not page anyone.
                        "thresholdValue": 1.0,
                        "duration": "600s",
                        "trigger": {"count": 1},
                    },
                }
            ],
            "notificationChannels": notify,
            "enabled": True,
        },
        {
            "displayName": "vf-logistics is returning server errors",
            "documentation": {
                "content": (
                    "Cloud Run is answering 5xx. The service is up -- the uptime "
                    "check will still be green -- but requests are failing. Usual "
                    "causes: Firestore permissions, a missing secret, or the Nebius "
                    "key being rejected."
                ),
                "mimeType": "text/markdown",
            },
            "combiner": "OR",
            "conditions": [
                {
                    "displayName": "5xx responses",
                    "conditionThreshold": {
                        "filter": (
                            'metric.type="run.googleapis.com/request_count" '
                            'AND resource.type="cloud_run_revision" '
                            f'AND resource.labels.service_name="{SERVICE}" '
                            'AND metric.labels.response_code_class="5xx"'
                        ),
                        "aggregations": [
                            {
                                "alignmentPeriod": "300s",
                                "perSeriesAligner": "ALIGN_RATE",
                                "crossSeriesReducer": "REDUCE_SUM",
                            }
                        ],
                        "comparison": "COMPARISON_GT",
                        # A rate, not a count: roughly one 5xx every two minutes
                        # sustained for five. A single error does not page anyone,
                        # because a single error is not an outage.
                        "thresholdValue": 0.008,
                        "duration": "300s",
                        "trigger": {"count": 1},
                    },
                }
            ],
            "notificationChannels": notify,
            "enabled": True,
        },
        {
            "displayName": "A tenant hit its model spend ceiling",
            "documentation": {
                "content": (
                    "A tenant reached VF_TENANT_SPEND_CEILING_USD and model calls "
                    "are being refused for it. This is the cost control working, "
                    "not a fault -- but that customer's screening has stopped, so "
                    "either raise their ceiling or tell them. The log line carries "
                    "the tenant and the amount."
                ),
                "mimeType": "text/markdown",
            },
            "combiner": "OR",
            "conditions": [
                {
                    "displayName": "spend ceiling reached",
                    "conditionThreshold": {
                        "filter": (
                            'metric.type="logging.googleapis.com/user/'
                            'vf_tenant_spend_ceiling_reached" '
                            'AND resource.type="cloud_run_revision"'
                        ),
                        "aggregations": [
                            {
                                "alignmentPeriod": "300s",
                                "perSeriesAligner": "ALIGN_SUM",
                                "crossSeriesReducer": "REDUCE_SUM",
                            }
                        ],
                        "comparison": "COMPARISON_GT",
                        # Any occurrence at all. Unlike the 5xx policy there is no
                        # noise to filter out here: this line is only ever logged
                        # when a customer has actually been cut off.
                        "thresholdValue": 0,
                        "duration": "0s",
                        "trigger": {"count": 1},
                    },
                }
            ],
            "notificationChannels": notify,
            "enabled": True,
        },
    ]


def main() -> int:
    notify = channels()
    print(f"notifying {len(notify)} channel(s)")

    already = existing()
    for policy in policies(notify):
        name = policy["displayName"]
        if name in already:
            print(f"  = {name} (exists, left alone)")
            continue
        call("POST", "alertPolicies", policy)
        print(f"  + {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
