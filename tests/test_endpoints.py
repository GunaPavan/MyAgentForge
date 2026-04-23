"""HTTP endpoint + security-header tests."""
import pytest


@pytest.mark.asyncio
async def test_root_returns_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "MyAgentForge" in r.text
    assert "<html" in r.text.lower()


@pytest.mark.asyncio
async def test_health_endpoint(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "mode": "mock"}


@pytest.mark.asyncio
async def test_config_endpoint_has_no_secrets(client):
    r = await client.get("/api/config")
    assert r.status_code == 200
    data = r.json()
    # Expected safe fields
    assert "mode" in data
    assert "skip_tester" in data
    assert "max_review_iterations" in data
    assert "max_tokens" in data
    # Must NEVER expose API keys or URLs
    assert "api_key" not in data
    assert "base_url" not in data
    assert "key" not in data
    assert "secret" not in data


@pytest.mark.asyncio
async def test_security_headers_on_root(client):
    r = await client.get("/")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert "strict-origin" in (r.headers.get("referrer-policy") or "").lower()
    assert r.headers.get("permissions-policy")
    csp = r.headers.get("content-security-policy") or ""
    # Key CSP directives
    assert "default-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "base-uri 'self'" in csp
    # Must NOT allow unsafe-inline scripts
    assert "'unsafe-inline'" not in csp.split("script-src")[1].split(";")[0]


@pytest.mark.asyncio
async def test_security_headers_on_api(client):
    r = await client.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("content-security-policy")


@pytest.mark.asyncio
async def test_download_zip_requires_files(client):
    r = await client.post("/download-zip", json={"files": {}})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_download_zip_success(client):
    r = await client.post("/download-zip", json={
        "files": {"hello.py": "print('hi')", "readme.md": "# test"}
    })
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers["content-disposition"]
    assert len(r.content) > 0


@pytest.mark.asyncio
async def test_download_zip_path_traversal_stripped(client, tmp_path):
    """Filenames with '../' must have path components removed."""
    import zipfile, io

    r = await client.post("/download-zip", json={
        "files": {"../../etc/passwd": "fake", "/absolute/secret": "fake2", "ok.txt": "ok"}
    })
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        names = zf.namelist()
    # No traversal or absolute paths survive
    for n in names:
        assert ".." not in n
        assert not n.startswith("/")
    # ok.txt preserved; traversal entries kept only as basename
    assert "ok.txt" in names


@pytest.mark.asyncio
async def test_download_zip_rejects_too_many_files(client):
    files = {f"f{i}.py": "x" for i in range(200)}
    r = await client.post("/download-zip", json={"files": files})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_download_zip_rejects_oversized(client):
    # 11 MB total content — above 10 MB cap
    big = "x" * (11 * 1024 * 1024)
    r = await client.post("/download-zip", json={"files": {"big.txt": big}})
    assert r.status_code == 400
