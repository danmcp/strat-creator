#!/usr/bin/env python3
"""Remove the [DRAFT] prefix from a Jira issue's summary.

Idempotent: exits cleanly if the summary has no [DRAFT] prefix.

Usage:
    python3 scripts/remove_draft_prefix.py RHAISTRAT-1500

Environment variables:
    JIRA_SERVER  Jira server URL
    JIRA_USER    Jira username/email
    JIRA_TOKEN   Jira API token
"""

import argparse
import sys

from jira_utils import get_issue, require_env, update_summary

DRAFT_PREFIX = "[DRAFT] "


def main():
    parser = argparse.ArgumentParser(description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("issue_key", help="Jira issue key (e.g. RHAISTRAT-1500)")
    args = parser.parse_args()

    server, user, token = require_env()
    if not all([server, user, token]):
        print("Error: JIRA_SERVER, JIRA_USER, and JIRA_TOKEN required.",
              file=sys.stderr)
        sys.exit(2)

    issue = get_issue(server, user, token, args.issue_key, fields=["summary"])
    summary = issue["fields"]["summary"]

    if not summary.startswith(DRAFT_PREFIX):
        print(f"[SKIP] No [DRAFT] prefix on {args.issue_key} -- summary unchanged")
        return

    update_summary(server, user, token, args.issue_key,
                   summary[len(DRAFT_PREFIX):])
    print(f"[SUMMARY] Removed [DRAFT] prefix from {args.issue_key}")


if __name__ == "__main__":
    main()
