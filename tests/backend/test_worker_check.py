from app.worker_check import check_chromium_launch


def test_chromium_launches_and_renders_fixture():
    """Real Playwright/Chromium launch — no mocking. This is the same check
    that runs at worker Docker image build time and via `make worker-check`.
    """
    assert check_chromium_launch() is True
