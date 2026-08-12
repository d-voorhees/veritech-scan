"""Worker health verification: Redis connectivity, queue/actor registration,
and Chromium launch + a basic render fixture.

`--startup-only` runs just the Chromium check with no external services
required — used as a Docker build-time `RUN` step so an ARM64 image that
cannot launch Chromium fails the build immediately rather than at first scan.
`make worker-check` runs the full set against a live stack.
"""

import argparse
import sys


def check_chromium_launch() -> bool:
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            page.set_content("<html><body><h1>Veritech Scan worker check</h1></body></html>")
            _ = page.title()
            browser.close()
        print("[worker-check] Chromium launched and rendered a fixture page successfully.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[worker-check] Chromium launch FAILED: {exc}", file=sys.stderr)
        return False


def check_redis() -> bool:
    from app.core.rate_limit import get_redis_client

    try:
        get_redis_client().ping()
        print("[worker-check] Redis connectivity OK.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[worker-check] Redis connectivity FAILED: {exc}", file=sys.stderr)
        return False


def check_queue() -> bool:
    try:
        import app.tasks.broker  # noqa: F401
        from app.tasks.scan_tasks import run_scan

        print(f"[worker-check] Dramatiq actor {run_scan.actor_name!r} registered on queue {run_scan.queue_name!r}.")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[worker-check] Queue/actor registration check FAILED: {exc}", file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Veritech Scan worker verification")
    parser.add_argument(
        "--startup-only", action="store_true", help="Only check Chromium launch (used during image build)"
    )
    args = parser.parse_args()

    if args.startup_only:
        sys.exit(0 if check_chromium_launch() else 1)

    results = [check_redis(), check_queue(), check_chromium_launch()]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
