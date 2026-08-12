from app.worker_check import check_chromium_launch


def test_chromium_launches_and_renders_fixture():
    """Real Playwright/Chromium launch — no mocking. This is the same check
    that scripts/install-server.sh and scripts/deploy.sh run against the
    native host before starting/restarting the worker service.
    """
    assert check_chromium_launch() is True
