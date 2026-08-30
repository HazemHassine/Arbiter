from fastapi.testclient import TestClient

from arbiter.api.app import create_app


def test_ui_static_bundle_serving(service_factory):
    client = TestClient(create_app(services=service_factory()))

    # Root redirect
    redirect = client.get("/", follow_redirects=False)
    assert redirect.status_code in (307, 308, 302, 301)
    assert redirect.headers["location"] == "/ui/"

    # UI HTML export
    ui = client.get("/ui/")
    assert ui.status_code == 200
    assert "Arbiter — Local Development Control Plane" in ui.text
    assert 'id="resource-selector"' in ui.text

    # Icons JS
    icons = client.get("/ui/icons.js")
    assert icons.status_code == 200
