import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import attrs
import scrapy

from funda_listing.pages.funda.com.product import FundaListingPage


# Statuses that indicate a listing is already closed.
# Requirement #5 — skip these in daily runs to avoid re-scraping the full archive.
_SOLD_URL_MARKERS = ("/verkocht/", "/verhuurd/")

# Funda exposes at most ~666 pages × 15 items ≈ 10 000 results per search query.
# When a query exceeds this we split it into two sub-queries by price range and
# recurse until every sub-range is under the cap.
_SPLIT_THRESHOLD = 9_500

# Upper price ceiling used as the starting split boundary.
# /koop (buy) listings rarely exceed €10M; /huur (rent) rarely exceed €25k/month.
_PRICE_CEIL_BUY  = 10_000_000
_PRICE_CEIL_RENT =     25_000


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


    async def start(self):
        extra_url = getattr(self, "extra_url", None)
        if not extra_url:
            self.logger.error("No extra_url provided. Run with -a extra_url='https://...'")
            return
        parsed = urlparse(extra_url.strip())
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            self.logger.error("Invalid extra_url: %s", extra_url)
            return
        self.logger.info("Starting crawl for: %s", extra_url)
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
            if current_page == 1:
                total = self._get_total_count(response)
                if total > _SPLIT_THRESHOLD:
                    splits = list(self._split_search_by_price(response, query, parsed, total))
                    if splits:
                        yield from splits
                        return
                    # Range too narrow to split — fall through and paginate as-is,
                    # accepting the ~10k cap for this bucket.

            # If the search URL explicitly targets sold/rented listings
            # (availability contains "unavailable" or "negotiations") do NOT
            # filter them out — the user intentionally wants that archive.
            avail = (query.get("availability") or [""])[0]
            is_sold_search = any(
                x in avail for x in ("unavailable", "negotiations", "verhuurd")
            )

            for entry in items:
                url = entry.get("url")
                if not url:
                    continue
                if not is_sold_search and any(marker in url for marker in _SOLD_URL_MARKERS):
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
            if page.status != "available":
                yield {
                    "status": page.status,
                    "address": attrs.asdict(page.address),
                }
            else:
                item = await page.to_item()
                yield item
        except Exception as e:
            self.logger.error("parse_detail failed for %s: %s", response.url, e)