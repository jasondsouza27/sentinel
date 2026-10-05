"""Strict URL parsing with a supplied, immutable offline suffix snapshot."""
import hashlib
import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from .contracts import ParsedUrl, UnsupportedUrl, MAX_URL_CHARS

BAD_ESCAPE = re.compile(r"%(?![0-9a-fA-F]{2})")

class UrlParser:
    def __init__(self, psl_path: Path):
        import tldextract
        import requests
        from requests_file import FileAdapter
        self.psl_path = Path(psl_path).resolve()
        if not self.psl_path.is_file():
            raise ValueError("suffix_snapshot_missing")
        self.psl_sha256 = hashlib.sha256(self.psl_path.read_bytes()).hexdigest()
        # No disk cache and no HTTP fallback: artifact files remain immutable.
        self._extract = tldextract.TLDExtract(
            suffix_list_urls=(self.psl_path.as_uri(),), fallback_to_snapshot=False,
            cache_dir=None, include_psl_private_domains=True,
        )

        # requests-file keeps a Windows file handle on the response. Force its
        # content into memory and close it before tldextract reads response.text.
        class LocalSnapshotSession(requests.Session):
            def request(self, method, url, **kwargs):
                if url != self_snapshot_uri:
                    raise ValueError("suffix_snapshot_only")
                response = super().request(method, url, **kwargs)
                try:
                    response.content
                finally:
                    response.close()
                return response
        self_snapshot_uri = self.psl_path.as_uri()
        with LocalSnapshotSession() as session:
            session.mount("file://", FileAdapter())
            self._extract.extract_str("example.org", session=session)

    def normalize(self, value: str) -> ParsedUrl:
        import idna
        if not isinstance(value, str):
            raise UnsupportedUrl("url_type")
        if not value or len(value) > MAX_URL_CHARS:
            raise UnsupportedUrl("url_empty_or_too_long")
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
            raise UnsupportedUrl("url_whitespace_or_control")
        if BAD_ESCAPE.search(value):
            raise UnsupportedUrl("url_invalid_escape")
        try:
            parts = urlsplit(value)
            if parts.scheme.lower() not in ("http", "https"):
                raise UnsupportedUrl("url_scheme")
            host = (parts.hostname or "").rstrip(".")
            port = parts.port
            if not host:
                raise UnsupportedUrl("url_host")
        except ValueError as error:
            if isinstance(error, UnsupportedUrl):
                raise
            raise UnsupportedUrl("url_authority") from None
        flags = []
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            try:
                host = idna.encode(host, uts46=True, std3_rules=True).decode("ascii").lower()
            except idna.IDNAError:
                raise UnsupportedUrl("url_host") from None
            if len(host) > 253:
                raise UnsupportedUrl("url_host")
            if any(label.startswith("xn--") for label in host.split(".")):
                flags.append("punycode")
            suffix = self._extract(host)
            if suffix.suffix:
                group = suffix.top_domain_under_public_suffix or host
            else:
                group = host
                flags.append("unknown_suffix")
            domain_group = "domain:" + group
            authority_host = host
        else:
            host = address.compressed.lower()
            domain_group = "ip:" + host
            authority_host = "[" + host + "]" if address.version == 6 else host
            flags.append("ip_host")
        user_info = ""
        if "@" in parts.netloc:
            user_info = parts.netloc.rsplit("@", 1)[0] + "@"
            flags.append("user_info")
        scheme = parts.scheme.lower()
        port_text = "" if port is None or (scheme, port) in (("http", 80), ("https", 443)) else ":" + str(port)
        model_url = urlunsplit((scheme, user_info + authority_host + port_text, parts.path, parts.query, parts.fragment))
        if len(model_url) > MAX_URL_CHARS:
            raise UnsupportedUrl("url_normalized_too_long")
        return ParsedUrl(model_url, host, domain_group, tuple(flags))
