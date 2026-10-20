import json
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import attrs
import scrapy

from funda_listing.pages.funda.com.product import FundaListingPage


# Statuses that indicate a listing is already closed.
# Requirement #5 — daily runs skip these; run with -a status_only=<url> to
# harvest them instead (status + address records only).
_SOLD_URL_MARKERS = ("/verkocht/", "/verhuurd/")

# Funda exposes at most ~666 pages × 15 items ≈ 10 000 results per search query.
# When a query exceeds this we split it into two sub-queries by price range and
# recurse until every sub-range is under the cap.
_SPLIT_THRESHOLD = 9_500

# Upper price ceiling used as the starting split boundary.
# /koop (buy) listings rarely exceed €10M; /huur (rent) rarely exceed €25k/month.
_PRICE_CEIL_BUY  = 10_000_000
_PRICE_CEIL_RENT =     25_000

# Optional crawl-limit token the client may append to the crawl URL, e.g.
# ...&sort=publish_date_utc_desc,max_pages:15 — scrape at most that many
# result pages of the search. The plain query-param form (max_pages=15) is
# accepted too. The token is stripped from the URL before any request is
# sent, so funda never receives it as a stray suffix inside e.g. the sort
# parameter.
_MAX_PAGES_TOKEN = re.compile(r"[?,&]\s*max_pages\s*(?::|=)\s*(\d+)\s*")


class FundaSpider(scrapy.Spider):
    name = "funda"

    custom_settings = {
        "CONCURRENT_REQUESTS": 10,
        "DOWNLOAD_DELAY": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 3,
        "AUTOTHROTTLE_MAX_DELAY": 10,
        "LOG_LEVEL": "INFO",
    }


    def __init__(self, *args, status_only=None, max_pages=None, **kwargs):
        super().__init__(*args, **kwargs)
        # -a status_only=<url> crawls that search in status-only mode (every
        # listing a status + address record, closed listings followed);
        # -a extra_url=<url> crawls it in full mode. Normalised here rather
        # than in start() because the feed exporter reads spider attributes
        # (filename label) when the spider opens, which happens before
        # start() runs.
        self.status_only = str(status_only or "").strip()
        # Optional cap on result pages per search (int or None). Comes from a
        # token inside the crawl URL (see _extract_max_pages) or directly via
        # -a max_pages=15; a URL token overrides the argument. None = all
        # pages (subject to funda's ~10k cap and the price-split workaround).
        try:
            self.max_pages = int(max_pages) if max_pages else None
        except (TypeError, ValueError):
            self.max_pages = None

    async def start(self):
        # Whichever argument carries the URL decides the mode.
        extra_url = getattr(self, "status_only", None) or getattr(self, "extra_url", None)
        if not extra_url:
            self.logger.error(
                "No URL provided. Run with -a extra_url='https://...' (full "
                "scrape) or -a status_only='https://...' (status + address only)"
            )
            return
        # Pull an optional ",max_pages:15" style token out of the URL before
        # anything is requested — the cleaned URL is what funda sees.
        extra_url, url_max_pages = self._extract_max_pages(extra_url.strip())
        if url_max_pages:
            self.max_pages = url_max_pages
        parsed = urlparse(extra_url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            self.logger.error("Invalid URL: %s", extra_url)
            return
        if self.status_only:
            self.logger.info("Status-only crawl (status + address records): %s", extra_url)
        else:
            self.logger.info("Starting crawl for: %s", extra_url)
        if self.max_pages:
            self.logger.info(
                "max_pages=%d — crawling at most %d result page(s) of the search",
                self.max_pages, self.max_pages,
            )
        yield scrapy.Request(
            extra_url.strip(),
            callback=self.parse_listing,
            meta={
                "zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True},
                "job_key": "extra_url",
            },
        )

    def parse_listing(self, response):
        raw_text = response.xpath(
            '//script[@data-hid="result-list-metadata"]/text()'
        ).get()

        if not raw_text:
            self.logger.warning(
                "No result-list-metadata found (page blocked or result set "
                "exhausted): %s", response.url
            )
            return

        parsed = urlparse(response.url)
        query = parse_qs(parsed.query)
        current_page = int((query.get("page") or [1])[0])
        items = []

        try:
            data = json.loads(raw_text)
            items = data.get("itemListElement", [])

            # On the first page of any search, check total count.  If it exceeds
            # Funda's ~10k pagination cap, split into two price sub-ranges instead
            # of paginating — each sub-range goes through the same check, so the
            # splitting recurses automatically until every bucket is under the cap.
            # A max_pages cap skips the split: the client explicitly wants N
            # pages of this exact search (e.g. newest-first), not full coverage
            # via price sub-ranges; pagination below stops at the cap anyway.
            if current_page == 1 and not self.max_pages:
                total = self._get_total_count(response)
                if total > _SPLIT_THRESHOLD:
                    splits = list(self._split_search_by_price(response, query, parsed, total))
                    if splits:
                        yield from splits
                        return
                    # Range too narrow to split — fall through and paginate as-is,
                    # accepting the ~10k cap for this bucket.

            for entry in items:
                url = entry.get("url")
                if not url:
                    continue
                # Normal runs skip closed listings; -a status_only=<url> opts
                # into harvesting them (as status + address records).
                if not self.status_only and any(marker in url for marker in _SOLD_URL_MARKERS):
                    self.logger.debug("Skipping closed listing: %s", url)
                    continue
                yield response.follow(
                    url,
                    callback=self.parse_detail,
                    meta={"zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True}},
                )

        except Exception as e:
            self.logger.error("JSON parse error: %s | %s", response.url, e)

        if items:
            if self.max_pages and current_page >= self.max_pages:
                self.logger.info(
                    "max_pages=%d reached at page %d — pagination stopped for: %s",
                    self.max_pages, current_page, response.url,
                )
                return
            query["page"] = [str(current_page + 1)]
            next_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))
            yield response.follow(
                next_url,
                callback=self.parse_listing,
                meta={
                    "zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True},
                    "job_key": response.meta.get("job_key"),
                },
            )
        else:
            self.logger.info(
                "No items on page %d — pagination stopped for: %s",
                current_page, response.url,
            )

    @staticmethod
    def _extract_max_pages(url):
        """Split an optional max_pages token off a client-supplied crawl URL.

        The client appends the limit after the last real parameter, e.g.
        ...&sort=publish_date_utc_desc,max_pages:15; the plain query-param
        form (max_pages=15) is accepted too. Returns (clean_url, limit) with
        the token removed so it never reaches funda as a stray suffix.
        """
        match = _MAX_PAGES_TOKEN.search(url)
        if not match:
            return url, None
        limit = int(match.group(1))
        prefix, lead, remainder = url[: match.start()], url[match.start()], url[match.end() :]
        if lead == "?":
            # Removing the '?' that opens the query string would glue the
            # remaining params onto the path — keep it when params follow.
            cleaned = prefix + ("?" + remainder.lstrip("&") if remainder else "")
        else:
            cleaned = prefix + remainder
        return cleaned.rstrip("?&"), limit

    def _get_total_count(self, response) -> int:
        """Read totalListingsCount from __NUXT_DATA__ on a search result page."""
        nuxt_raw = response.xpath('//script[@id="__NUXT_DATA__"]/text()').get()
        if not nuxt_raw:
            return 0
        try:
            arr = json.loads(nuxt_raw)
            for item in arr:
                if isinstance(item, dict) and "totalListingsCount" in item:
                    idx = item["totalListingsCount"]
                    # Follow the reference chain: int index → ['Ref', N] → int value
                    for _ in range(5):
                        if not isinstance(idx, int) or not (0 <= idx < len(arr)):
                            break
                        val = arr[idx]
                        if isinstance(val, int):
                            return val
                        if isinstance(val, list) and len(val) == 2 and isinstance(val[1], int):
                            idx = val[1]
                        else:
                            break
                    break
        except Exception:
            pass
        return 0

    def _parse_price_range(self, query: dict, url: str):
        """Return (lo, hi) from the current ?price= param, or sensible defaults."""
        raw = (query.get("price") or [None])[0]
        ceil = _PRICE_CEIL_RENT if "/huur" in url else _PRICE_CEIL_BUY
        if raw:
            clean = raw.strip('"').strip("'")
            parts = clean.split("-", 1)
            try:
                lo = int(parts[0]) if parts[0] else 0
                hi = int(parts[1]) if len(parts) > 1 and parts[1] else ceil
                return lo, hi
            except ValueError:
                pass
        return 0, ceil

    def _split_search_by_price(self, response, query, parsed, total):
        """Yield two requests that cover the current price range split at its midpoint.

        The upper sub-range always uses an open-ended max (e.g. "5000000-") so
        that listings above the ceiling constant are never silently dropped.
        """
        lo, hi = self._parse_price_range(query, response.url)
        ceil = _PRICE_CEIL_RENT if "/huur" in response.url else _PRICE_CEIL_BUY
        is_open_top = (hi >= ceil)  # current range has no defined upper bound

        if hi - lo < 1_000:
            self.logger.warning(
                "Price range %d–%d is too narrow to split further "
                "(total %d). This bucket will be capped at ~10k results.",
                lo, hi, total,
            )
            return

        mid = (lo + hi) // 2
        if is_open_top:
            self.logger.info(
                "Search has %d results — splitting into price ranges [%d–%d] and [%d–]",
                total, lo, mid, mid,
            )
        else:
            self.logger.info(
                "Search has %d results — splitting into price ranges [%d–%d] and [%d–%d]",
                total, lo, mid, mid, hi,
            )

        for range_lo, range_hi in [(lo, mid), (mid, hi)]:
            # Preserve open-endedness: the upper sub-range uses "MID-" so
            # listings priced above the ceiling constant are never missed.
            if is_open_top and range_hi >= ceil:
                price_val = f'"{range_lo}-"'
            else:
                price_val = f'"{range_lo}-{range_hi}"'

            new_query = {k: v for k, v in query.items() if k != "page"}
            new_query["price"] = [price_val]
            new_url = urlunparse(
                parsed._replace(query=urlencode(new_query, doseq=True))
            )
            yield response.follow(
                new_url,
                callback=self.parse_listing,
                meta={
                    "zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True},
                    "job_key": response.meta.get("job_key"),
                },
            )

    async def parse_detail(self, response, page: FundaListingPage):  # noqa: ARG002
        try:
            if not page.status:
                # Empty status means the detail page didn't parse (no
                # __NUXT_DATA__ listing data), so every field would be empty.
                self.logger.warning(
                    "Empty status — detail page unparseable: %s", response.url
                )
            if self.status_only:
                # Status-only mode: status + address records only.
                yield {
                    "status": page.status,
                    "address": attrs.asdict(page.address),
                }
            else:
                # Full mode: the complete listing regardless of status —
                # onder-bod listings are still fully marketed pages. The
                # item's own status field still says which it is.
                item = await page.to_item()
                yield item
        except Exception as e:
            self.logger.error("parse_detail failed for %s: %s", response.url, e)