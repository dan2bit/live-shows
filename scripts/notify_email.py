#!/usr/bin/env python3
"""
notify_email.py - send a plain-text digest to the project inbox via Resend.

One sender, several callers. The release digest and the weekly HFTB diff both
produce a block of text that is worth reading in the inbox rather than only in a
CI log, and neither should grow its own mail plumbing.

    python3 scripts/release_digest.py | python3 scripts/notify_email.py \\
        --subject "[releases] 3 new since last sweep"

    python3 scripts/notify_email.py --subject "..." --body-file report.txt
    python3 scripts/notify_email.py --subject "..." --dry-run < report.txt

Body comes from stdin unless --body-file is given.

WHY RESEND RATHER THAN SMTP

Sending through Gmail needs an app password, which is a *mailbox* credential: it
grants send-as for the account indefinitely and cannot be scoped. A Resend API
key can only push mail through Resend, reads no inbox, is revocable in one click,
and every send it makes is visible in a dashboard. Same word, very different
blast radius.

The key lives in the RESEND_API_KEY environment variable - in CI, a repository
secret; locally, the password manager. It is never committed and never printed,
including by --dry-run.

SENDING DOMAIN

Mail goes from a dedicated sending subdomain rather than the apex, because
mailbox providers build reputation per sending domain. Automated mail on
send.<domain> cannot drag down anything sent from the apex later, and it keeps
these DNS records clear of the ones serving the site.

EMPTY BODIES ARE NOT SENT

A digest with nothing to report should produce silence, not a mail saying
nothing happened - that is how an alert channel trains you to ignore it. An
empty body exits 0 without sending, so a caller can pipe unconditionally.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.resend.com/emails"
DEFAULT_FROM = "alerts@send.redhat-bootlegs.net"
DEFAULT_TO = "redhat.bootlegs@gmail.com"


def send(payload, api_key, timeout=30):
    req = urllib.request.Request(
        API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        # Deliberately does not echo the key or the Authorization header - CI
        # logs are readable by anyone who can read the repo.
        raise SystemExit("FATAL: Resend returned %s: %s" % (e.code, detail))
    except (urllib.error.URLError, TimeoutError) as e:
        raise SystemExit("FATAL: could not reach Resend: %s" % e)


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--subject", required=True)
    ap.add_argument("--to", default=DEFAULT_TO)
    ap.add_argument("--sender", default=DEFAULT_FROM,
                    help="From address (default %s)" % DEFAULT_FROM)
    ap.add_argument("--body-file", help="read the body from a file instead of stdin")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be sent and exit; makes no request "
                         "and needs no API key")
    args = ap.parse_args()

    if args.body_file:
        body = open(args.body_file, encoding="utf-8").read()
    else:
        body = "" if sys.stdin.isatty() else sys.stdin.read()

    if not body.strip():
        print("Nothing to send (empty body).")
        return 0

    payload = {
        "from": args.sender,
        "to": [args.to],
        "subject": args.subject,
        "text": body,
    }

    if args.dry_run:
        print("DRY RUN - would send:")
        print("  from    : %s" % payload["from"])
        print("  to      : %s" % ", ".join(payload["to"]))
        print("  subject : %s" % payload["subject"])
        print("  body    : %d chars, %d lines"
              % (len(body), len(body.splitlines())))
        print("--")
        print(body.rstrip())
        return 0

    api_key = os.environ.get("RESEND_API_KEY", "").strip()
    if not api_key:
        raise SystemExit(
            "FATAL: RESEND_API_KEY is not set. In CI this is a repository "
            "secret; locally it lives in the password manager. Use --dry-run "
            "to test without one.")

    res = send(payload, api_key)
    print("sent: %s" % res.get("id", "(no id returned)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
