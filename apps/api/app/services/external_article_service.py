"""Safe, bounded previews for approved external article sources.

This module intentionally performs an explicit **preview only** operation:
content is fetched only after an authenticated editor submits a supported source
URL, it is size/time bounded, sanitised, and returned for human review.  The
caller must still save a normal CMS draft; this service never persists or
publishes an article.

The fixed platform allowlist, disabled redirect following, and no-arbitrary-host
rule make this a controlled connector rather than a general-purpose server-side
fetch proxy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from html.parser import HTMLParser
from typing import Callable, Final
from urllib.parse import urlsplit, urlunsplit

import bleach
import httpx

from ..core.config import get_settings
from ..core.exceptions import ServiceUnavailableError, ValidationError
from ..core.sanitize import sanitize_rich_html

EXTERNAL_ARTICLE_MAX_BYTES: Final[int] = 2 * 1024 * 1024
EXTERNAL_ARTICLE_CONNECT_TIMEOUT_SECONDS: Final[float] = 5.0
EXTERNAL_ARTICLE_READ_TIMEOUT_SECONDS: Final[float] = 10.0
EXTERNAL_ARTICLE_PREVIEW_TTL_SECONDS: Final[int] = 30 * 60
_EXTERNAL_ARTICLE_PREVIEW_TOKEN_MAX_LENGTH: Final[int] = 4096
_EXTERNAL_ARTICLE_PREVIEW_TOKEN_VERSION: Final[int] = 1
_EXTERNAL_ARTICLE_MAX_HTML_TOKENS: Final[int] = 50_000
_EXTERNAL_ARTICLE_MAX_HTML_NESTING: Final[int] = 256

_settings = get_settings()

# Exact host allowlists are intentional.  Do not weaken these to suffix
# matching: a user-controlled subdomain would turn a CMS convenience feature
# into an SSRF surface.  Add a host only after a platform/terms review.
_ALLOWED_SOURCE_HOSTS: Final[dict[str, frozenset[str]]] = {
    "wechat": frozenset({"mp.weixin.qq.com"}),
    "xmol": frozenset({"x-mol.com", "www.x-mol.com", "en.x-mol.com"}),
}

_VOID_TAGS: Final[frozenset[str]] = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


@dataclass(frozen=True, slots=True)
class ExternalArticlePreview:
    """Normalized, sanitised article preview returned to the admin route."""

    platform: str
    source_url: str
    title: str
    content_html: str
    source_content_hash: str
    source_published_at: datetime | None


@dataclass(frozen=True, slots=True)
class ExternalArticlePreviewAttestation:
    """Server-attested source provenance accepted at the CMS save boundary."""

    platform: str
    source_url: str
    source_content_hash: str
    source_published_at: datetime | None


def _platform_value(platform: object) -> str:
    value = getattr(platform, "value", platform)
    if not isinstance(value, str):
        raise ValidationError("Unsupported external article platform")
    normalized = value.strip().lower()
    if normalized not in _ALLOWED_SOURCE_HOSTS:
        raise ValidationError("Unsupported external article platform")
    return normalized


def normalize_external_article_url(platform: object, source_url: str) -> str:
    """Validate and canonicalize a platform-owned HTTPS article URL.

    No DNS resolution or network traffic happens here.  The strict hostname
    check is nevertheless performed before any later fetch so a malformed or
    arbitrary URL cannot enter a redirect chain, logs, or source provenance.
    Query parameter order is preserved because source platforms can attach
    signatures to their article links.
    """

    if not isinstance(source_url, str) or not source_url.strip():
        raise ValidationError("source_url is required")

    platform_value = _platform_value(platform)
    candidate = source_url.strip()
    if len(candidate) > 2048 or any(ord(char) < 32 for char in candidate):
        raise ValidationError("source_url is invalid")

    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise ValidationError("source_url is invalid") from exc

    if parsed.scheme.lower() != "https":
        raise ValidationError("source_url must use HTTPS")
    if parsed.username is not None or parsed.password is not None:
        raise ValidationError("source_url must not include credentials")
    if port not in (None, 443):
        raise ValidationError("source_url must use the platform HTTPS port")

    hostname = (parsed.hostname or "").lower().rstrip(".")
    if hostname not in _ALLOWED_SOURCE_HOSTS[platform_value]:
        raise ValidationError("source_url host is not approved for this platform")

    path = parsed.path or "/"
    if not path.startswith("/"):
        raise ValidationError("source_url path is invalid")

    # URL fragments never affect a source document and would defeat a unique
    # source URL index.  Preserve the query exactly to avoid changing signed
    # platform URLs.
    return urlunsplit(("https", hostname, path, parsed.query, ""))


def _token_b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _token_b64decode(value: str) -> bytes:
    if not value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid base64url token component")
    decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    # Reject equivalent encodings that differ only in unused base64 pad bits.
    # This keeps one serialized representation per signed attestation.
    if _token_b64encode(decoded) != value:
        raise ValueError("noncanonical base64url token component")
    return decoded


def _attestation_payload(preview: ExternalArticlePreview, exp: int) -> bytes:
    return json.dumps(
        {
            "v": _EXTERNAL_ARTICLE_PREVIEW_TOKEN_VERSION,
            "exp": exp,
            "platform": preview.platform,
            "source_url": preview.source_url,
            "source_content_hash": preview.source_content_hash,
            "source_published_at": (
                preview.source_published_at.astimezone(UTC).isoformat()
                if preview.source_published_at is not None
                else None
            ),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _attestation_signature(payload: bytes) -> bytes:
    return hmac.new(
        _settings.jwt_secret.encode("utf-8"),
        b"soymutdb:external-article-preview:v1:" + payload,
        hashlib.sha256,
    ).digest()


def sign_external_article_preview(
    preview: ExternalArticlePreview, *, ttl: int = EXTERNAL_ARTICLE_PREVIEW_TTL_SECONDS
) -> str:
    """Return a short-lived, server-signed proof of one reviewed preview.

    The fingerprint is intentionally not trusted from a browser form. Instead
    the save API accepts this HMAC attestation and rehydrates provenance from
    its signed payload. This remains stateless and is not a JWT.
    """
    payload = _attestation_payload(preview, int(time.time()) + int(ttl))
    return f"{_token_b64encode(payload)}.{_token_b64encode(_attestation_signature(payload))}"


def verify_external_article_preview_attestation(
    token: str,
) -> ExternalArticlePreviewAttestation:
    """Validate a preview attestation and return canonical source metadata."""
    invalid_message = "External article preview attestation is invalid"
    if not isinstance(token, str) or not token or len(token) > _EXTERNAL_ARTICLE_PREVIEW_TOKEN_MAX_LENGTH:
        raise ValidationError(invalid_message)
    try:
        encoded_payload, encoded_signature = token.split(".", maxsplit=1)
        payload = _token_b64decode(encoded_payload)
        signature = _token_b64decode(encoded_signature)
        expected_signature = _attestation_signature(payload)
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError("signature mismatch")
        decoded = json.loads(payload)
    except (TypeError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValidationError(invalid_message) from exc

    if not isinstance(decoded, dict) or decoded.get("v") != _EXTERNAL_ARTICLE_PREVIEW_TOKEN_VERSION:
        raise ValidationError(invalid_message)
    expires_at = decoded.get("exp")
    if not isinstance(expires_at, int):
        raise ValidationError(invalid_message)
    if expires_at <= int(time.time()):
        raise ValidationError("External article preview attestation has expired")

    try:
        platform = _platform_value(decoded.get("platform"))
        source_url = normalize_external_article_url(platform, decoded.get("source_url"))
        source_content_hash = decoded.get("source_content_hash")
        if not isinstance(source_content_hash, str) or not re.fullmatch(
            r"[a-f0-9]{64}", source_content_hash
        ):
            raise ValueError("invalid source content hash")
        source_published_at_value = decoded.get("source_published_at")
        if source_published_at_value is None:
            source_published_at = None
        elif isinstance(source_published_at_value, str):
            source_published_at = datetime.fromisoformat(
                source_published_at_value.replace("Z", "+00:00")
            )
            if source_published_at.tzinfo is None:
                source_published_at = source_published_at.replace(tzinfo=UTC)
            else:
                source_published_at = source_published_at.astimezone(UTC)
        else:
            raise ValueError("invalid source publication date")
    except (TypeError, ValueError, ValidationError) as exc:
        raise ValidationError(invalid_message) from exc

    return ExternalArticlePreviewAttestation(
        platform=platform,
        source_url=source_url,
        source_content_hash=source_content_hash,
        source_published_at=source_published_at,
    )


def _plain_text(html: str) -> str:
    return " ".join(bleach.clean(html, tags=[], strip=True).split())


class _MarkupComplexityGuard(HTMLParser):
    """Reject bounded-but-pathological markup before repeated extraction passes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._token_count = 0
        self._depth = 0

    def _bump(self) -> None:
        self._token_count += 1
        if self._token_count > _EXTERNAL_ARTICLE_MAX_HTML_TOKENS:
            raise ValidationError("The external article markup is too complex")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._bump()
        if tag.lower() not in _VOID_TAGS:
            self._depth += 1
            if self._depth > _EXTERNAL_ARTICLE_MAX_HTML_NESTING:
                raise ValidationError("The external article markup is too complex")

    def handle_startendtag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        self._bump()

    def handle_endtag(self, tag: str) -> None:
        self._bump()
        if tag.lower() not in _VOID_TAGS:
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data: str) -> None:
        self._bump()

    def handle_comment(self, data: str) -> None:
        self._bump()

    def handle_decl(self, decl: str) -> None:
        self._bump()

    def handle_pi(self, data: str) -> None:
        self._bump()


def _assert_markup_complexity(html: str) -> None:
    guard = _MarkupComplexityGuard()
    guard.feed(html)
    guard.close()


class _MetadataCollector(HTMLParser):
    """Collect document title and best-effort publication metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._inside_title = False
        self._inside_publish_time = False
        self._title_parts: list[str] = []
        self._meta_titles: list[str] = []
        self._meta_dates: list[str] = []
        self._publish_time_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): (value or "") for name, value in attrs}
        lowered = tag.lower()
        if lowered == "title":
            self._inside_title = True
        elif lowered == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            content = attributes.get("content", "").strip()
            if key in {"og:title", "twitter:title"} and content:
                self._meta_titles.append(content)
            if key in {"article:published_time", "og:published_time", "publishdate", "pubdate"} and content:
                self._meta_dates.append(content)
        elif lowered == "time":
            value = attributes.get("datetime", "").strip()
            if value:
                self._meta_dates.append(value)
        if attributes.get("id", "").lower() in {"publish_time", "publish-time", "pubtime"}:
            self._inside_publish_time = True

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered == "title":
            self._inside_title = False
        if self._inside_publish_time and lowered in {"span", "time", "p", "div"}:
            self._inside_publish_time = False

    def handle_data(self, data: str) -> None:
        if self._inside_title:
            self._title_parts.append(data)
        if self._inside_publish_time:
            self._publish_time_parts.append(data)

    @property
    def title(self) -> str:
        values = [*self._meta_titles, "".join(self._title_parts)]
        for value in values:
            normalized = " ".join(value.split())
            if normalized:
                return normalized[:512]
        return "Imported article"

    @property
    def published_at(self) -> datetime | None:
        candidates = [*self._meta_dates, "".join(self._publish_time_parts)]
        for candidate in candidates:
            parsed = _parse_published_at(candidate)
            if parsed is not None:
                return parsed
        return None


def _parse_published_at(value: str) -> datetime | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class _FragmentExtractor(HTMLParser):
    """Copy the first matching HTML subtree for a later bleach sanitization."""

    def __init__(self, predicate: Callable[[str, dict[str, str]], bool]) -> None:
        super().__init__(convert_charrefs=True)
        self._predicate = predicate
        self._parts: list[str] = []
        self._depth: int | None = None
        self._finished = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._finished:
            return
        lowered = tag.lower()
        attributes = {name.lower(): (value or "") for name, value in attrs}
        if self._depth is None:
            if not self._predicate(lowered, attributes):
                return
            self._depth = 0 if lowered in _VOID_TAGS else 1
        else:
            if lowered not in _VOID_TAGS:
                self._depth += 1
        self._parts.append(self.get_starttag_text() or f"<{lowered}>")
        if self._depth == 0:
            self._finished = True

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self._depth is None or self._finished:
            return
        self._parts.append(self.get_starttag_text() or f"<{tag.lower()} />")

    def handle_endtag(self, tag: str) -> None:
        if self._depth is None or self._finished:
            return
        lowered = tag.lower()
        if lowered in _VOID_TAGS:
            return
        self._parts.append(f"</{lowered}>")
        self._depth -= 1
        if self._depth <= 0:
            self._finished = True

    def handle_data(self, data: str) -> None:
        if self._depth is not None and not self._finished:
            self._parts.append(escape(data, quote=False))

    def fragment(self) -> str:
        return "".join(self._parts)


def _class_tokens(attributes: dict[str, str]) -> set[str]:
    return {token.strip().lower() for token in attributes.get("class", "").split() if token.strip()}


def _candidate_predicates(platform: str) -> tuple[Callable[[str, dict[str, str]], bool], ...]:
    if platform == "wechat":
        return (
            lambda _tag, attrs: attrs.get("id", "").lower() == "js_content",
            lambda tag, _attrs: tag == "article",
        )
    return (
        lambda _tag, attrs: attrs.get("id", "").lower()
        in {"article-content", "article_content", "content-detail"},
        lambda _tag, attrs: bool(
            _class_tokens(attrs)
            & {"article-content", "article_content", "content-detail", "article-detail"}
        ),
        lambda tag, _attrs: tag == "article",
    )


def extract_external_article(platform: object, html: str, source_url: str) -> ExternalArticlePreview:
    """Extract and sanitize a platform article from already-bounded HTML."""

    platform_value = _platform_value(platform)
    canonical_url = normalize_external_article_url(platform_value, source_url)
    _assert_markup_complexity(html)
    metadata = _MetadataCollector()
    try:
        metadata.feed(html)
        metadata.close()
    except Exception as exc:  # HTMLParser is deliberately defensive about malformed input.
        raise ValidationError("The source page could not be parsed") from exc

    fragment = ""
    for predicate in _candidate_predicates(platform_value):
        extractor = _FragmentExtractor(predicate)
        try:
            extractor.feed(html)
            extractor.close()
        except Exception as exc:
            raise ValidationError("The source page could not be parsed") from exc
        candidate = extractor.fragment()
        sanitized = sanitize_rich_html(candidate)
        if _plain_text(sanitized):
            fragment = sanitized
            break

    if not fragment:
        raise ValidationError("No readable article content was found at the approved source URL")

    fingerprint_input = f"{platform_value}\n{canonical_url}\n{fragment}".encode("utf-8")
    return ExternalArticlePreview(
        platform=platform_value,
        source_url=canonical_url,
        title=metadata.title,
        content_html=fragment,
        source_content_hash=hashlib.sha256(fingerprint_input).hexdigest(),
        source_published_at=metadata.published_at,
    )


def _response_charset(content_type: str | None) -> str:
    if not content_type:
        return "utf-8"
    match = re.search(r"charset=([^;\s]+)", content_type, re.IGNORECASE)
    return match.group(1).strip("\"'") if match else "utf-8"


class ExternalArticlePreviewService:
    """Fetch one approved external page under strict resource and host bounds."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        max_bytes: int = EXTERNAL_ARTICLE_MAX_BYTES,
    ) -> None:
        self._transport = transport
        self._max_bytes = max(1, max_bytes)

    async def preview(self, platform: object, source_url: str) -> ExternalArticlePreview:
        platform_value = _platform_value(platform)
        canonical_url = normalize_external_article_url(platform_value, source_url)
        timeout = httpx.Timeout(
            connect=EXTERNAL_ARTICLE_CONNECT_TIMEOUT_SECONDS,
            read=EXTERNAL_ARTICLE_READ_TIMEOUT_SECONDS,
            write=EXTERNAL_ARTICLE_CONNECT_TIMEOUT_SECONDS,
            pool=EXTERNAL_ARTICLE_CONNECT_TIMEOUT_SECONDS,
        )
        headers = {
            "Accept": "text/html,application/xhtml+xml",
            "User-Agent": "SoyMutDB-Content-Preview/1.0",
        }

        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                headers=headers,
                timeout=timeout,
                transport=self._transport,
            ) as client:
                async with client.stream("GET", canonical_url) as response:
                    if 300 <= response.status_code < 400:
                        raise ValidationError(
                            "The source URL redirected; use the platform's canonical article URL"
                        )
                    if response.status_code >= 400:
                        raise ServiceUnavailableError(
                            "The external source did not return a readable article"
                        )
                    content_type = response.headers.get("content-type", "")
                    media_type = content_type.split(";", 1)[0].strip().lower()
                    if media_type not in {"text/html", "application/xhtml+xml"}:
                        raise ValidationError("The external source did not return an HTML article")
                    try:
                        advertised_size = int(response.headers.get("content-length", "0"))
                    except ValueError:
                        advertised_size = 0
                    if advertised_size > self._max_bytes:
                        raise ValidationError("The external article is too large to preview")

                    chunks: list[bytes] = []
                    received = 0
                    async for chunk in response.aiter_bytes():
                        received += len(chunk)
                        if received > self._max_bytes:
                            raise ValidationError("The external article is too large to preview")
                        chunks.append(chunk)
        except (ValidationError, ServiceUnavailableError):
            raise
        except httpx.HTTPError as exc:
            raise ServiceUnavailableError("The external source could not be reached") from exc

        raw = b"".join(chunks)
        try:
            document = raw.decode(_response_charset(content_type), errors="replace")
        except LookupError:
            document = raw.decode("utf-8", errors="replace")
        return extract_external_article(platform_value, document, canonical_url)


__all__ = [
    "EXTERNAL_ARTICLE_MAX_BYTES",
    "EXTERNAL_ARTICLE_PREVIEW_TTL_SECONDS",
    "ExternalArticlePreview",
    "ExternalArticlePreviewAttestation",
    "ExternalArticlePreviewService",
    "extract_external_article",
    "normalize_external_article_url",
    "sign_external_article_preview",
    "verify_external_article_preview_attestation",
]
