def test_healthz(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_static_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
