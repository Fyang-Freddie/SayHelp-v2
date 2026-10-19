def test_static_assets_reachable(client):
    for path in ["/", "/app.js", "/style.css", "/chat.html"]:
        assert client.get(path).status_code == 200
