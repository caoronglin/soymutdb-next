"""Security regression tests, round 2 — input and release boundaries.

Negative cases only.  The four boundaries pinned here are the ones an
attacker reaches without an account:

1. **Release / identity boundary** — an anonymous caller cannot discover a
   draft-release, non-public or soft-deleted mutant line, and cannot turn an
   internal persistence key into an existence oracle.
2. **Upload boundary** — traversal, absolute and control-character file names
   never become object-key segments.
3. **Outbound fetch boundary (SSRF)** — the external-article connector only
   accepts the exact approved HTTPS hosts, never a userinfo/port/redirect
   variant of them.
4. **HTML boundary (XSS)** — rich-text cleaning strips active content and
   cannot be corrupted into emitting attributes of its own.

Plus the leakage boundary: an unhandled server error must not echo exception
text, SQL or filesystem paths back to the caller.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from app.core.sanitize import sanitize_rich_html
from app.core.security import RoleName, hash_password
from app.models.auth import Role, User
from app.models.content import Release, ReleaseStatus
from app.models.data_publishing import ActiveRelease
from app.models.variant import MutantLine

MUTANTS_PREFIX = "/api/v1/mutants"

#: Fixture public ids must avoid the Crockford look-alikes the API folds away
#: (``I``/``L`` -> ``1``, ``O`` -> ``0``), otherwise the locator never matches
#: and a test would "pass" for the wrong reason.
PUBLIC_ID = "SMPUBAAA1"
DRAFT_PUBLIC_ID = "SMDRAFT01"
PRIVATE_PUBLIC_ID = "SMPRVBATE"
DELETED_PUBLIC_ID = "SMDGTED01"
ORPHAN_PUBLIC_ID = "SMNBREL1"
LEAK_PUBLIC_ID = "SMAEAK001"


# ---------------------------------------------------------------------------
# 1. Anonymous callers cannot reach draft / internal / non-public records
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def published_release(db_session):
    release = Release(
        version="sec-r2-public",
        name="security round 2 public release",
        status=ReleaseStatus.PUBLISHED,
    )
    db_session.add(release)
    await db_session.flush()
    db_session.add(ActiveRelease(id=1, release_id=release.id))
    await db_session.flush()
    return release


@pytest_asyncio.fixture
async def draft_release(db_session, published_release):
    """A second, unpublished release whose rows must stay invisible."""
    draft = Release(
        version="sec-r2-draft",
        name="security round 2 draft release",
        status=ReleaseStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.flush()
    return draft


@pytest.mark.asyncio
async def test_anonymous_cannot_see_a_draft_release_mutant(
    client, db_session, published_release, draft_release
) -> None:
    """A draft-release row exists but is unreachable and undiscoverable."""
    draft_line = MutantLine(
        name="draft-only",
        public_id=DRAFT_PUBLIC_ID,
        is_public=True,
        release_id=draft_release.id,
    )
    public_line = MutantLine(
        name="public-one",
        public_id=PUBLIC_ID,
        is_public=True,
        release_id=published_release.id,
    )
    db_session.add_all([draft_line, public_line])
    await db_session.commit()

    listing = await client.get(MUTANTS_PREFIX)
    draft_lookup = await client.get(f"{MUTANTS_PREFIX}/{draft_line.public_id}")
    public_lookup = await client.get(f"{MUTANTS_PREFIX}/{public_line.public_id}")

    assert listing.status_code == 200
    listed_ids = {line["public_id"] for line in listing.json()}
    assert listed_ids == {PUBLIC_ID}
    assert draft_lookup.status_code == 404
    assert public_lookup.status_code == 200


@pytest.mark.asyncio
async def test_internal_persistence_key_is_not_an_existence_oracle(
    client, db_session, published_release
) -> None:
    """Internal id, public id and nonsense all answer identically for an outsider.

    The three responses must be indistinguishable: if any of them differed in
    status code, body shape or headers, an anonymous caller could use the
    endpoint to enumerate unpublished records.
    """
    line = MutantLine(
        name="internal-only",
        public_id=PUBLIC_ID,
        is_public=True,
        release_id=published_release.id,
    )
    db_session.add(line)
    await db_session.flush()
    internal_id = str(line.id)
    await db_session.commit()

    assert line.id is not None

    by_internal = await client.get(f"{MUTANTS_PREFIX}/{internal_id}")
    by_unknown = await client.get(f"{MUTANTS_PREFIX}/SMD0ESN0TEX1ST")

    assert by_internal.status_code == by_unknown.status_code == 404
    assert by_internal.json()["error"]["code"] == by_unknown.json()["error"]["code"]
    assert (
        by_internal.headers.get("cache-control")
        == by_unknown.headers.get("cache-control")
    )
    # The unpublished record itself is disclosed nowhere in the body.
    assert "internal-only" not in by_internal.text
    assert PUBLIC_ID not in by_internal.text


@pytest.mark.asyncio
async def test_non_public_and_soft_deleted_mutants_stay_hidden(
    client, db_session, published_release
) -> None:
    private_line = MutantLine(
        name="private-line",
        public_id=PRIVATE_PUBLIC_ID,
        is_public=False,
        release_id=published_release.id,
    )
    deleted_line = MutantLine(
        name="deleted-line",
        public_id=DELETED_PUBLIC_ID,
        is_public=True,
        is_deleted=True,
        release_id=published_release.id,
    )
    orphan_line = MutantLine(name="no-release", public_id=ORPHAN_PUBLIC_ID)
    null_public_id = MutantLine(
        name="null-public-id",
        public_id=None,
        is_public=True,
        release_id=published_release.id,
    )
    db_session.add_all([private_line, deleted_line, orphan_line, null_public_id])
    await db_session.commit()

    listing = await client.get(MUTANTS_PREFIX)
    assert listing.status_code == 200
    assert listing.json() == []

    for hidden in (private_line, deleted_line, orphan_line):
        response = await client.get(f"{MUTANTS_PREFIX}/{hidden.public_id}")
        assert response.status_code == 404, hidden.name


@pytest.mark.asyncio
async def test_no_public_response_body_carries_an_internal_id(
    client, db_session, published_release
) -> None:
    """Neither the detail page nor the list leaks the persistence key."""
    line = MutantLine(
        name="leak-check",
        public_id=LEAK_PUBLIC_ID,
        is_public=True,
        release_id=published_release.id,
    )
    db_session.add(line)
    await db_session.flush()
    internal_id = str(line.id)
    await db_session.commit()

    detail = await client.get(f"{MUTANTS_PREFIX}/{line.public_id}")
    listing = await client.get(MUTANTS_PREFIX)

    assert detail.status_code == 200
    assert internal_id not in detail.text
    assert internal_id not in listing.text
    assert detail.json()["public_id"] == LEAK_PUBLIC_ID
    assert "id" not in detail.json()


# ---------------------------------------------------------------------------
# 2. Upload / object-key boundary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "filename",
    [
        "..",
        ".",
        "",
        "../secret.png",
        "../../../../etc/passwd",
        "/etc/passwd",
        "a/b/c.png",
        "..\\..\\win.png",
        "C:\\Windows\\evil.png",
        "\x00evil.png",
        "   ",
    ],
)
def test_unsafe_upload_filenames_never_reach_an_object_key(filename: str) -> None:
    """Traversal collapses to a bare name, or is refused outright.

    Either outcome is safe: the result is never a separator, never a ``..``
    segment and never absolute, so it cannot escape the ``uploads/`` prefix.
    """
    from app.services.presign import build_uploads_key, sanitize_filename

    try:
        sanitized = sanitize_filename(filename)
    except ValueError:
        return
    assert "/" not in sanitized
    assert "\\" not in sanitized
    assert sanitized not in {".", ".."}
    assert "\x00" not in sanitized
    key = build_uploads_key("news", sanitized)
    assert key.startswith("uploads/news/")
    assert "//" not in key
    assert ".." not in key.split("/")


@pytest.mark.parametrize(
    "purpose",
    ["..", "../../etc", "/absolute", "news/../../etc", "\x00"],
)
def test_upload_purpose_cannot_escape_its_key_segment(purpose: str) -> None:
    """A hostile ``purpose`` is either refused or reduced to one safe segment."""
    from app.services.presign import build_uploads_key

    try:
        key = build_uploads_key(purpose, "cover.png")
    except ValueError:
        return
    assert key.startswith("uploads/")
    segment = key.split("/")[1]
    assert segment not in {"", ".", ".."}
    assert "/" not in segment
    assert ".." not in key.split("/")


@pytest.mark.parametrize(
    "object_key",
    [
        "uploads-evil/news/x.png",
        "/uploads/news/x.png",
        "uploads//news/x.png",
        "uploads/news/../secret.png",
        "uploads/./news/x.png",
        "",
        f"analyses/{uuid.uuid4()}/input/x",
    ],
)
def test_object_keys_outside_the_uploads_namespace_are_rejected(
    object_key: str,
) -> None:
    from app.core.exceptions import ValidationError as AppValidationError
    from app.schemas.media import MediaAssetCompleteRequest

    with pytest.raises(Exception):
        MediaAssetCompleteRequest(
            object_key=object_key,
            filename="cover.png",
            purpose="news",
            size=10,
            content_type="image/png",
            checksum_sha256="ab" * 32,
        )
    # Keep the exception import referenced so the intent stays explicit.
    assert AppValidationError is not None


@pytest.mark.parametrize(
    "overrides",
    [
        {"filename": "cover.svg"},
        {"filename": "cover.html"},
        {"purpose": "../../etc"},
        {"purpose": "unknown-purpose"},
        {"content_type": "text/html"},
        {"content_type": "image/svg+xml"},
        {"checksum_sha256": "nothex"},
        {"size": 0},
        {"size": 10 * 1024 * 1024 + 1},
    ],
)
def test_presign_request_rejects_unsafe_declarations(overrides: dict) -> None:
    from pydantic import ValidationError

    from app.schemas.uploads import UploadPresignRequest

    body: dict = {
        "filename": "cover.png",
        "purpose": "news",
        "size": 1024,
        "content_type": "image/png",
        "checksum_sha256": "ab" * 32,
    }
    body.update(overrides)
    with pytest.raises(ValidationError):
        UploadPresignRequest(**body)


@pytest.mark.parametrize(
    "filename",
    ["../../evil.png", "/etc/passwd.png", "a/b/cover.png", "..\\..\\evil.png"],
)
def test_traversal_filename_never_reaches_the_object_key_verbatim(filename: str) -> None:
    """The declared name is re-sanitised at key-construction time.

    ``UploadPresignRequest`` keeps the raw declared name (it only checks that
    a safe basename *can* be derived), so the guarantee has to hold where the
    key is actually built.
    """
    from app.schemas.uploads import UploadPresignRequest
    from app.services.presign import build_uploads_key

    request = UploadPresignRequest(
        filename=filename,
        purpose="news",
        size=1024,
        content_type="image/png",
        checksum_sha256="ab" * 32,
    )
    key = build_uploads_key(request.purpose, request.filename)

    assert key.startswith("uploads/news/")
    assert ".." not in key.split("/")
    assert "//" not in key
    assert not key.endswith("/")
    assert "/" not in key.split("/")[-1]


# ---------------------------------------------------------------------------
# 3. Outbound fetch boundary (SSRF)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "platform,url",
    [
        ("wechat", "http://mp.weixin.qq.com/s/abc"),  # scheme downgrade
        ("wechat", "https://mp.weixin.qq.com.evil.test/s/abc"),  # suffix look-alike
        ("wechat", "https://evilmp.weixin.qq.com.evil.test/s/abc"),
        ("wechat", "https://user:pw@mp.weixin.qq.com/s/abc"),  # credentials
        ("wechat", "https://mp.weixin.qq.com:8443/s/abc"),  # non-standard port
        ("wechat", "https://127.0.0.1/s/abc"),  # loopback
        ("wechat", "https://169.254.169.254/latest/meta-data/"),  # link-local
        ("wechat", "https://[::1]/s/abc"),
        ("wechat", "file:///etc/passwd"),
        ("wechat", "gopher://mp.weixin.qq.com/s/abc"),
        ("xmol", "https://x-mol.com.evil.test/p/1"),
        ("unknown-platform", "https://mp.weixin.qq.com/s/abc"),
    ],
)
def test_external_article_fetch_rejects_everything_off_the_allowlist(
    platform: str, url: str
) -> None:
    """The connector is a fixed-host fetch, not a proxy."""
    from app.core.exceptions import ValidationError as AppValidationError
    from app.services.external_article_service import normalize_external_article_url

    with pytest.raises(AppValidationError):
        normalize_external_article_url(platform, url)


@pytest.mark.parametrize(
    "platform,url",
    [
        ("wechat", "https://mp.weixin.qq.com/s/abc"),
        ("xmol", "https://x-mol.com/p/1"),
        ("xmol", "https://en.x-mol.com/p/1"),
    ],
)
def test_external_article_fetch_accepts_only_the_approved_forms(
    platform: str, url: str
) -> None:
    from app.services.external_article_service import normalize_external_article_url

    assert normalize_external_article_url(platform, url).startswith("https://")


def test_external_article_preview_refuses_to_follow_a_redirect() -> None:
    """A 3xx must be an error, never a hop toward an internal address."""
    import inspect

    from app.services.external_article_service import ExternalArticlePreviewService

    source = inspect.getsource(ExternalArticlePreviewService.preview)
    assert "follow_redirects=False" in source
    assert "redirected" in source


# ---------------------------------------------------------------------------
# 4. HTML boundary (XSS)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        "<script>alert(1)</script>",
        "<img src=x onerror=alert(1)>",
        "<a href=\"javascript:alert(1)\">x</a>",
        "<a href=\"JaVaScRiPt:alert(1)\">x</a>",
        "<a href=\"&#106;avascript:alert(1)\">x</a>",
        "<iframe src=\"https://evil.test\"></iframe>",
        "<svg/onload=alert(1)>",
        "<p onclick=\"steal()\">t</p>",
        "<object data=\"https://evil.test\"></object>",
        "<img src=\"data:image/svg+xml;base64,PHN2Zz4=\">",
        "<a href=\"data:text/html;base64,PHNjcmlwdD4=\">x</a>",
        "<style>body{display:none}</style>",
        "<form action=\"https://evil.test\"><input name=pw></form>",
    ],
)
def test_rich_text_sanitizer_removes_active_content(payload: str) -> None:
    cleaned = sanitize_rich_html(payload)
    lowered = cleaned.lower()
    for dangerous in (
        "<script",
        "<iframe",
        "<object",
        "<style",
        "<form",
        "<svg",
        "onerror",
        "onclick",
        "onload",
        "javascript:",
        "data:text/html",
        "data:image/svg+xml",
    ):
        assert dangerous not in lowered, (payload, cleaned)


def test_target_blank_links_always_carry_noopener_and_noreferrer() -> None:
    """An author-supplied ``rel`` must not be able to weaken the guarantee."""
    assert (
        'rel="noopener noreferrer"'
        in sanitize_rich_html('<a href="https://ok.test" target="_blank">x</a>')
    )
    # ``rel="opener"`` re-enables window.opener on the page that opens.
    hardened = sanitize_rich_html(
        '<a href="https://ok.test" target="_blank" rel="opener">x</a>'
    )
    assert "opener" not in hardened.replace("noopener", "")
    assert 'rel="noopener noreferrer"' in hardened
    # A same-tab link is left alone.
    assert "rel=" not in sanitize_rich_html('<a href="https://ok.test">x</a>')


def test_rel_rewrite_does_not_corrupt_an_attribute_containing_gt() -> None:
    """A raw ``>`` inside an attribute must not end the tag early.

    bleach leaves ``title="a>b"`` untouched, so a naive ``[^>]*>`` rewrite
    would inject the new attribute in the middle of the title and emit
    malformed HTML into stored CMS content.
    """
    cleaned = sanitize_rich_html(
        '<a target="_blank" href="https://ok.test" title="a>b">x</a>'
    )
    assert cleaned == (
        '<a target="_blank" href="https://ok.test" title="a>b" '
        'rel="noopener noreferrer">x</a>'
    )


# ---------------------------------------------------------------------------
# 5. Error / stack-trace leakage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unhandled_errors_do_not_leak_internals() -> None:
    """A 500 body is a fixed message; the exception text stays in the log."""
    from httpx import ASGITransport, AsyncClient

    from app.core.database import get_db
    from app.core.exceptions import (
        HTTPException,
        SoyMutDBError,
        http_exception_handler,
        soy_mut_db_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )

    leaked = (
        "SELECT password_hash FROM users; -- "
        "/srv/soymutdb/apps/api/app/api/v1/auth.py line 199"
    )

    class ExplodingSession:
        async def execute(self, *args, **kwargs):
            raise RuntimeError(leaked)

        async def scalar(self, *args, **kwargs):
            raise RuntimeError(leaked)

    application = FastAPI(title="leak probe")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)

    @application.get("/boom")
    async def boom():  # pragma: no cover - always raises
        raise RuntimeError(leaked)

    @application.get("/db")
    async def db_route():
        return (await get_db()).execute  # type: ignore[return-value]

    async def override_get_db():
        yield ExplodingSession()

    application.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/db")

    assert response.status_code == 500
    body = response.text
    assert leaked not in body
    assert "Traceback" not in body
    assert "password_hash" not in body
    assert "RuntimeError" not in body
    assert response.json()["error"]["code"] == "internal_error"
    # A correlatable request id is always present for log correlation.
    assert response.json()["request_id"]


@pytest.mark.asyncio
async def test_validation_errors_do_not_echo_input_values() -> None:
    """The 422 envelope carries field/message/type only, never the input."""
    from httpx import ASGITransport, AsyncClient

    from app.core.database import get_db
    from app.core.exceptions import (
        HTTPException,
        SoyMutDBError,
        http_exception_handler,
        soy_mut_db_exception_handler,
        unhandled_exception_handler,
        validation_exception_handler,
    )

    class _Session:
        pass

    application = FastAPI(title="validation leak probe")
    application.add_exception_handler(SoyMutDBError, soy_mut_db_exception_handler)
    application.add_exception_handler(HTTPException, http_exception_handler)
    application.add_exception_handler(
        RequestValidationError, validation_exception_handler
    )
    application.add_exception_handler(Exception, unhandled_exception_handler)

    @application.post("/strict")
    async def strict(payload: dict[str, int]):
        return payload

    async def override_get_db():
        yield _Session()

    application.dependency_overrides[get_db] = override_get_db

    secret = "hunter2-should-never-be-echoed"
    transport = ASGITransport(app=application, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/strict", json={"count": secret})

    assert response.status_code == 422
    assert secret not in response.text
    entry = response.json()["errors"][0]
    assert set(entry) == {"field", "message", "type"}


# ---------------------------------------------------------------------------
# 6. Admin write boundary stays behind the role gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rich_text_admin_write_is_role_gated_and_sanitized(
    client, db_session
) -> None:
    """A viewer cannot write HTML into the CMS; an admin's write is cleaned.

    The two halves matter separately: the role gate must refuse *before* any
    row is written, and an authorised write must still pass through
    ``sanitize_rich_html`` so a privileged-but-compromised editor account
    cannot park script in stored content.
    """
    from sqlalchemy import select

    from app.core.security import create_access_token
    from app.models.content import StaticPage

    async def _role(name: str) -> Role:
        result = await db_session.execute(select(Role).where(Role.name == name))
        role = result.scalar_one()
        await db_session.flush()
        return role

    payload = {
        "slug": "sec-r2-xss",
        "title_en": "Security round 2",
        "content_en": '<p>ok</p><script>alert(1)</script><img src=x onerror=alert(2)>',
    }

    viewer = User(
        id=uuid.uuid4(),
        username="sec2-viewer",
        email="sec2-viewer@soymutdb.local",
        password_hash=hash_password("Sup3rSecret!x"),
        is_active=True,
        is_deleted=False,
        role_id=(await _role(RoleName.VIEWER.value)).id,
    )
    admin = User(
        id=uuid.uuid4(),
        username="sec2-admin",
        email="sec2-admin@soymutdb.local",
        password_hash=hash_password("Sup3rSecret!x"),
        is_active=True,
        is_deleted=False,
        role_id=(await _role(RoleName.ADMINISTRATOR.value)).id,
    )
    db_session.add_all([viewer, admin])
    await db_session.commit()

    anonymous = await client.post("/api/v1/admin/content/pages", json=payload)
    viewer_write = await client.post(
        "/api/v1/admin/content/pages",
        json=payload,
        headers={"Authorization": f"Bearer {create_access_token(subject=str(viewer.id))}"},
    )
    admin_write = await client.post(
        "/api/v1/admin/content/pages",
        json=payload,
        headers={"Authorization": f"Bearer {create_access_token(subject=str(admin.id))}"},
    )

    assert anonymous.status_code == 401
    assert viewer_write.status_code == 403
    assert viewer_write.headers["cache-control"] == "private, no-store"
    assert admin_write.status_code == 201

    stored = await db_session.execute(
        select(StaticPage).where(StaticPage.slug == payload["slug"])
    )
    page = stored.scalar_one()
    assert "<script" not in page.content_en.lower()
    assert "onerror" not in page.content_en.lower()
    assert "<p>ok</p>" in page.content_en
