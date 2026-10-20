import json
import math
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import scrapy

from funda_listing.pages.immoweb.be.product import ImmowebListingPage


class ImmowebSpider(scrapy.Spider):

    name = "immoweb"

    # immoweb reports at most 9969 items and serves at most 333 pages of 30.
    # Anything at or above this is assumed truncated and gets subdivided.
    CAP = 9969
    SPLIT_THRESHOLD = 9900
    MAX_PAGE = 333
    PAGE_SIZE = 30
    MAX_SPLIT_DEPTH = 14

    # Path segments that label the preceding segment as a place rather than
    # being a place themselves (…/brussels/district, …/limburg/province).
    _PLACE_KINDS = ("district", "province", "municipality", "city", "region", "commune")

    # Transaction path segments mapped onto funda's label vocabulary, so
    # files from both spiders read the same way (buy/rent).
    _KIND_SEGMENTS = {
        "buy": ("for-sale", "te-koop", "a-vendre"),
        "rent": ("for-rent", "te-huur", "a-louer"),
    }

    custom_settings = {
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 5,
        "RETRY_HTTP_CODES": [429, 403, 500, 502, 503, 504, 522, 524, 408],
        "DOWNLOAD_TIMEOUT": 60,
        "AUTOTHROTTLE_ENABLED": False,
        "DOWNLOAD_DELAY": 0.1,
        "CONCURRENT_REQUESTS": 16,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 16,
        "ZYTE_API_ENABLED": False,
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy.core.downloader.handlers.http11.HTTP11DownloadHandler",
            "https": "scrapy.core.downloader.handlers.http11.HTTP11DownloadHandler",
        },
        "USER_AGENT": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "DEFAULT_REQUEST_HEADERS": {
            "Accept-Language": "en-US,en;q=0.9",
        },
        "ITEM_PIPELINES": {
            "funda_listing.immoweb_pipelines.CoverageStatsPipeline": 900,
        },
        # No FEEDS override: the global GCS export applies, with uri_params
        # routing the file to country=be (or country=lu for a countries=LU
        # search) and naming it from the label derived in __init__.
    }

    def __init__(self, *args, include_raw=None, max_items=None, probe_only=None, **kwargs):
        super().__init__(*args, **kwargs)
        # Derived here rather than in start() because the feed exporter reads
        # these when the spider opens, which happens before start() runs.
        self.region, self.label = self._label(kwargs.get("extra_url") or "")
        self.include_raw = str(include_raw or "").lower() in ("1", "true", "yes")
        self.probe_only = str(probe_only or "").lower() in ("1", "true", "yes")
        self.max_items = int(max_items) if max_items else None
        self.seen_ids = set()
        self.items_scraped = 0
        self.slices_done = 0
        self.reachable_total = 0
        self.truncated_slices = []
        self.detail_fallbacks = 0
        self.detail_failures = 0

    # -- entry point --------------------------------------------------------

    async def start(self):
        extra_url = getattr(self, "extra_url", None)
        if not extra_url:
            self.logger.error('No extra_url provided. Run with -a extra_url="https://..."')
            return
        try:
            api_base, classified_base, lo, hi = self._derive_config(extra_url.strip())
        except ValueError as e:
            self.logger.error(str(e))
            return

        self.api_base = api_base
        self.classified_base = classified_base
        self.logger.info("search URL : %s", extra_url)
        self.logger.info("API base   : %s", api_base)
        self.logger.info("price seed : %s .. %s", lo, hi)
        yield self._probe(lo, hi, depth=0)

    @classmethod
    def _label(cls, url: str):
        """(region, label) for routing and naming the output file.

        region picks the GCS country= folder: "luxembourg" for a
        ?countries=LU search (immoweb has no .lu site — the Grand Duchy is
        reached through immoweb.be with that filter), otherwise "belgium",
        unless the URL names a place (…/for-sale/brussels/district).

        label names the file in funda's <status>-<kind>[-<place>]
        convention, e.g. available-buy / available-rent-brussels. The place
        is included only for sub-country scopes — country-wide crawls read
        exactly like funda's (funda_sold-buy ↔ immoweb_available-buy).
        """
        try:
            split = urlsplit(url)
            parts = [s for s in split.path.split("/") if s]
        except ValueError:
            return "unknown", "available"
        idx = next((i for i, s in enumerate(parts) if s in ("search", "search-results")), None)
        if idx is None:
            return "unknown", "available"

        rest = parts[idx + 1:]
        countries = dict(parse_qsl(split.query)).get("countries", "")
        region = "luxembourg" if countries.strip().upper() == "LU" else "belgium"
        place = ""
        for i, seg in enumerate(rest):
            if seg in cls._PLACE_KINDS and i > 0:
                region = rest[i - 1]
                place = cls._slug(rest[i - 1])
                rest = rest[:i - 1]
                break
        kind = next(
            (k for k, segs in cls._KIND_SEGMENTS.items() if any(s in segs for s in rest)),
            "",
        )
        label = "-".join(p for p in ("available", kind, place) if p)
        return cls._slug(region) or "belgium", label

    @staticmethod
    def _derive_config(url: str):
        """Turn an immoweb search/page URL into
        (api_base, classified_base, min_price, max_price).

        Any minPrice/maxPrice already in the URL becomes the seed bound for
        subdivision, so a user-supplied price filter is still respected.
        """
        sp = urlsplit(url)
        if not sp.netloc:
            raise ValueError(f"Not a valid URL: {url!r}")
        parts = [s for s in sp.path.split("/") if s]
        locale = parts[0] if parts and len(parts[0]) == 2 else "en"
        classified = f"{sp.scheme or 'https'}://{sp.netloc}/{locale}/classified/"

        idx = next((i for i, s in enumerate(parts) if s in ("search", "search-results")), None)
        if idx is None:
            raise ValueError("URL must be an immoweb search URL (…/search/…).")
        parts[idx] = "search-results"
        new_path = "/" + "/".join(parts)

        lo = hi = None
        kept = []
        for k, v in parse_qsl(sp.query, keep_blank_values=True):
            kl = k.lower()
            if kl == "page":
                continue
            if kl == "minprice":
                lo = int(v) if v.isdigit() else None
                continue
            if kl == "maxprice":
                hi = int(v) if v.isdigit() else None
                continue
            kept.append((k, v))

        api_base = urlunsplit((sp.scheme or "https", sp.netloc, new_path, urlencode(kept), ""))
        return api_base, classified, lo, hi

    def _slice_url(self, page: int, lo, hi) -> str:
        sp = urlsplit(self.api_base)
        q = parse_qsl(sp.query, keep_blank_values=True)
        if lo is not None:
            q.append(("minPrice", str(lo)))
        if hi is not None:
            q.append(("maxPrice", str(hi)))
        q.append(("page", str(page)))
        return urlunsplit((sp.scheme, sp.netloc, sp.path, urlencode(q), ""))

    def _probe(self, lo, hi, depth: int) -> scrapy.Request:
        return scrapy.Request(
            self._slice_url(1, lo, hi),
            callback=self.parse_probe,
            headers={"Accept": "application/json"},
            meta={"lo": lo, "hi": hi, "depth": depth},
            dont_filter=True,
        )

    # -- slice discovery ----------------------------------------------------

    @staticmethod
    def _load(response):
        """Search API returns an object normally, but a bare list for
        out-of-range pages and some error states."""
        try:
            data = json.loads(response.text)
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def _split_point(lo, hi):
        """Midpoint for a price band. The top band is open-ended, so it grows
        geometrically instead — high-price listings thin out fast, so this
        converges in a handful of steps."""
        low = lo or 0
        if hi is None:
            return max(low * 2, 150_000)
        if hi - low < 2:
            return None
        return (low + hi) // 2

    def parse_probe(self, response):
        lo, hi, depth = response.meta["lo"], response.meta["hi"], response.meta["depth"]
        label = f"[{lo or 0}..{hi if hi is not None else 'inf'}]"

        data = self._load(response)
        if data is None:
            self.logger.warning("slice %s: non-object response, skipping", label)
            return

        total = data.get("totalItems") or 0
        if not total:
            self.logger.debug("slice %s: empty", label)
            return

        if total >= self.SPLIT_THRESHOLD:
            mid = self._split_point(lo, hi) if depth < self.MAX_SPLIT_DEPTH else None
            if mid is not None and (lo is None or mid > lo) and (hi is None or mid < hi):
                self.logger.info("slice %s: %d at cap -> splitting at %d", label, total, mid)
                yield self._probe(lo, mid, depth + 1)
                yield self._probe(mid + 1, hi, depth + 1)
                return
            # Can't narrow further — page what we can and record the loss
            # rather than pretending the slice was complete.
            self.logger.error(
                "slice %s: %d at cap but cannot subdivide further; "
                "this slice is TRUNCATED to %d items",
                label, total, self.MAX_PAGE * self.PAGE_SIZE,
            )
            self.truncated_slices.append(label)

        pages = min(math.ceil(total / self.PAGE_SIZE), self.MAX_PAGE)
        self.slices_done += 1
        self.reachable_total += total
        self.logger.info("slice %s: %d items over %d pages", label, total, pages)
        if self.probe_only:
            return
        for p in range(1, pages + 1):
            yield scrapy.Request(
                self._slice_url(p, lo, hi),
                callback=self.parse_page,
                headers={"Accept": "application/json"},
                meta={"slice": label, "page": p},
                dont_filter=True,
            )

    # -- detail URLs --------------------------------------------------------

    @staticmethod
    def _slug(value) -> str:
        text = unicodedata.normalize("NFKD", str(value or ""))
        text = text.encode("ascii", "ignore").decode()
        return re.sub(r"[^a-zA-Z0-9]+", "-", text).strip("-").lower()

    def _detail_url(self, result: dict):
        """Build the canonical listing URL straight from the search result.

        `/classified/{id}` works but 301-redirects to the slug form, so every
        listing costs two requests. The search payload already carries type,
        transaction, locality and postcode, which is exactly what the slug is
        made of — building it here halves the request count over a full crawl.
        Returns None if any part is missing, in which case the caller falls
        back to the id form.
        """
        prop = result.get("property") or {}
        txn = result.get("transaction") or {}
        loc = prop.get("location") or {}
        parts = [
            self._slug(prop.get("type")),
            self._slug(txn.get("type")),
            self._slug(loc.get("locality")),
            str(loc.get("postalCode") or "").strip(),
        ]
        if not all(parts):
            return None
        return f"{self.classified_base}{'/'.join(parts)}/{result['id']}"

    def _detail_request(self, url, listing_id, is_fallback=False):
        return scrapy.Request(
            url,
            callback=self.parse_detail,
            errback=self.detail_errback,
            meta={"listing_id": listing_id, "is_fallback": is_fallback},
            dont_filter=is_fallback,
        )

    def detail_errback(self, failure):
        """A constructed slug URL can 404 if immoweb renames a locality. Fall
        back to the id form, which always redirects to the right page, rather
        than dropping the listing."""
        request = failure.request
        listing_id = request.meta.get("listing_id")
        if request.meta.get("is_fallback") or not listing_id:
            self.detail_failures += 1
            self.logger.error("detail permanently failed: %s (%s)", request.url, failure.value)
            return
        self.detail_fallbacks += 1
        self.logger.warning("slug URL failed (%s), retrying by id: %s", failure.value, listing_id)
        yield self._detail_request(
            f"{self.classified_base}{listing_id}", listing_id, is_fallback=True
        )

    # -- result pages -------------------------------------------------------

    def parse_page(self, response):
        data = self._load(response)
        if data is None:
            self.logger.warning(
                "slice %s page %s: non-object response",
                response.meta["slice"], response.meta["page"],
            )
            return

        for r in data.get("results") or []:
            if not isinstance(r, dict):
                continue
            listing_id = r.get("id")
            if not listing_id or listing_id in self.seen_ids:
                continue
            if self.max_items and len(self.seen_ids) >= self.max_items:
                return
            self.seen_ids.add(listing_id)
            url = self._detail_url(r) or f"{self.classified_base}{listing_id}"
            yield self._detail_request(url, listing_id)

    async def parse_detail(self, response, page: ImmowebListingPage):  # noqa: ARG002
        try:
            item = await page.to_item()
        except Exception as e:
            self.logger.error("parse_detail failed for %s: %s", response.url, e)
            return

        if not item.id:
            # window.classified missing or unparseable — worth knowing about
            # rather than emitting a row of empty strings.
            self.logger.warning("no classified payload at %s", response.url)
            return
        if not self.include_raw:
            item.raw = None
        self.items_scraped += 1
        yield item

    def closed(self, reason):
        self.logger.info(
            "done: %d leaf slices, %d reachable listings (sum of slice totals), "
            "%d unique discovered, %d items emitted (%s)",
            self.slices_done, self.reachable_total, len(self.seen_ids),
            self.items_scraped, reason,
        )
        if self.reachable_total > self.CAP:
            self.logger.info(
                "subdivision recovered %d listings beyond the %d single-query cap",
                self.reachable_total - self.CAP, self.CAP,
            )
        if self.detail_fallbacks:
            self.logger.info(
                "%d listing(s) needed the id-URL fallback", self.detail_fallbacks
            )
        if self.detail_failures:
            self.logger.error(
                "%d listing(s) could not be fetched at all", self.detail_failures
            )
        missed = len(self.seen_ids) - self.items_scraped
        if missed > 0:
            self.logger.warning(
                "%d discovered listing(s) produced no item", missed
            )
        if self.truncated_slices:
            self.logger.error(
                "%d slice(s) hit the cap and could not be subdivided: %s",
                len(self.truncated_slices), ", ".join(self.truncated_slices),
            )
