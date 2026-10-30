"""The JSON envelope must not reject imports within the raw UTF-8 file limit."""

import csv
import io
import json

import httpx
import pytest

from patchproof.app import create_app
from patchproof.domain import MAX_IMPORT_BYTES


def quote_heavy_json():
    cases = [
        {
            "id": f"ticket-{i}",
            "text": f"Please refund order {i:05} for a damaged item.",
            "expected": {
                "order_id": f"{i:05}", "issue_type": "damaged_item",
                "requested_action": "refund", "needs_review": False,
            },
            "fixture_outputs": {
                stage: '"' * 30_000 for stage in ("baseline", "candidate_1", "candidate_2")
            },
        }
        for i in range(10)
    ]
    return json.dumps({"name": "Quote-heavy scripted imports", "cases": cases}), len(cases)


def csv_content(count, text_suffix):
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow(
        ["id", "text", "order_id", "issue_type", "requested_action", "needs_review"]
    )
    for i in range(count):
        writer.writerow(
            [f"ticket-{i}", f"{i:05}: {text_suffix}", f"{i:05}", "other", "refund", "false"]
        )
    return out.getvalue(), count


async def post_body(client, path, body, *, streamed=False, method="POST"):
    if streamed:
        async def chunks():
            for start in range(0, len(body), 64_000):
                yield body[start:start + 64_000]

        content = chunks()
    else:
        content = body
    request = client.build_request(
        method, path, content=content, headers={"content-type": "application/json"}
    )
    assert ("content-length" not in request.headers) == streamed
    return await client.send(request)


@pytest.mark.parametrize("kind", ["json", "csv"])
@pytest.mark.parametrize("streamed", [False, True])
async def test_valid_source_below_two_mb_survives_json_transport_escaping(
    tmp_path, kind, streamed
):
    if kind == "json":
        content, count = quote_heavy_json()
    else:
        # NUL is valid CSV text and JSON must expand each byte into six bytes.
        content, count = csv_content(165, "\x00" * 11_990)
    assert len(content.encode("utf-8")) < MAX_IMPORT_BYTES
    body = json.dumps({"content": content, "format": kind, "reviewed": False}).encode()
    assert len(body) > 2_200_000
    app = create_app(tmp_path / "test.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await post_body(client, "/api/datasets/import", body, streamed=streamed)
    assert response.status_code == 200, response.text[:500]
    dataset = response.json()
    assert len(dataset["cases"]) == count
    assert dataset["human_review_pending"] is True
    if kind == "json":
        assert dataset["cases"][0]["fixture_outputs"]["baseline"] == '"' * 30_000
    else:
        assert dataset["cases"][0]["text"] == "00000: " + "\x00" * 11_990


async def test_import_source_limit_is_utf8_bytes_after_envelope_decoding(tmp_path):
    content, _ = csv_content(50, "😀" * 11_990)
    assert len(content) < MAX_IMPORT_BYTES < len(content.encode("utf-8"))
    body = json.dumps({"content": content, "format": "csv"}, ensure_ascii=False).encode()
    app = create_app(tmp_path / "test.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await post_body(client, "/api/datasets/import", body)
    assert response.status_code == 422
    assert "UTF-8 text of at most 2000000 bytes" in response.text


@pytest.mark.parametrize("streamed", [False, True])
@pytest.mark.parametrize(
    "method,path,body_size",
    [
        ("POST", "/api/datasets/import", 12_001_025),
        ("POST", "/api/experiments", 2_200_001),
        ("PUT", "/api/datasets/import", 2_200_001),
        ("POST", "/api/datasets/import/other", 2_200_001),
    ],
)
async def test_transport_caps_bound_declared_and_streamed_requests(
    tmp_path, streamed, method, path, body_size
):
    app = create_app(tmp_path / "test.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await post_body(
            client, path, b" " * body_size, streamed=streamed, method=method
        )
    assert response.status_code == 413


@pytest.mark.parametrize(
    "length", [b"-1", b"not-a-number", b"9" * 4301, b"\xb2"],
    ids=["negative", "nondecimal", "unrepresentable", "superscript"],
)
async def test_invalid_or_unrepresentable_content_length_is_rejected(tmp_path, length):
    app = create_app(tmp_path / "test.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            "/api/datasets/import", content=b"{}",
            headers={b"content-type": b"application/json", b"content-length": length},
        )
    assert response.status_code == 413


@pytest.mark.parametrize("leading_zeros", [False, True])
async def test_representable_content_length_accepts_valid_import(tmp_path, leading_zeros):
    content, _ = csv_content(1, "Please refund this order.")
    body = json.dumps({"content": content, "format": "csv"}).encode()
    length = ("000" if leading_zeros else "") + str(len(body))
    app = create_app(tmp_path / "test.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/datasets/import", content=body,
            headers={"content-type": "application/json", "content-length": length},
        )
    assert response.status_code == 200, response.text[:500]
    assert len(response.json()["cases"]) == 1


@pytest.mark.parametrize("media_type", ["Application/JSON", "application/json ; charset=utf-8"])
async def test_json_media_type_case_and_parameter_spacing_preserve_import(tmp_path, media_type):
    content, _ = csv_content(1, "Please refund this order.")
    app = create_app(tmp_path / "test.sqlite3")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/datasets/import",
            content=json.dumps({"content": content, "format": "csv"}),
            headers={"content-type": media_type},
        )
    assert response.status_code == 200, response.text
    saved = app.state.store.dataset(response.json()["dataset_id"])
    assert saved["cases"][0]["text"] == "00000: Please refund this order."
    assert saved["cases"][0]["expected"]["order_id"] == "00000"


@pytest.mark.parametrize(
    "media_type,origin,body,status",
    [
        ("Text/Plain", None, "{}", 415),
        ("application/jsonp", None, "{}", 415),
        ("Application/JSON", None, "{", 422),
        ("Application/JSON", "https://untrusted.example", "{}", 403),
    ],
)
async def test_media_type_normalization_preserves_request_boundaries(
    tmp_path, media_type, origin, body, status
):
    app = create_app(tmp_path / "test.sqlite3")
    headers = {"content-type": media_type}
    if origin:
        headers["origin"] = origin
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post("/api/datasets/import", content=body, headers=headers)
    assert response.status_code == status, response.text
    with app.state.store.connect() as db:
        assert db.execute("SELECT count(*) FROM datasets").fetchone()[0] == 0
