import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import attrs
import scrapy

from funda_listing.pages.funda.com.product import FundaListingPage


# Statuses that indicate a listing is already closed.
# Requirement #5 — skip these in daily runs to avoid re-scraping the full archive.
_SOLD_URL_MARKERS = ("/verkocht/", "/verhuurd/")


class FundaSpider(scrapy.Spider):
    name = "funda"

    item_test = True

    custom_settings = {
        "FEEDS": {
            "funda_output.jl": {
                "format": "jsonlines",
                "encoding": "utf8",
                "overwrite": True,
            }
        },
        "CONCURRENT_REQUESTS": 10,
        "DOWNLOAD_DELAY": 1,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 3,
        "AUTOTHROTTLE_MAX_DELAY": 10,
        "LOG_LEVEL": "INFO",
    }


    FUNDA_URLS = {
        "rent_noord_holland": "https://www.funda.nl/zoeken/huur?selected_area=[%22provincie-noord-holland%22]&availability=[%22available%22]",
        "buy_noord_holland":  "https://www.funda.nl/zoeken/koop?selected_area=[%22provincie-noord-holland%22]&availability=[%22available%22]",
        "sold_noord_holland": "https://www.funda.nl/zoeken/koop?selected_area=[%22provincie-noord-holland%22]&availability=[%22negotiations%22,%22unavailable%22]",
        "daily_noord_holland": "https://www.funda.nl/zoeken/koop?selected_area=[%22provincie-noord-holland%22]&publication_date=%221%22&availability=[%22available%22]",
        "daily_rent_noord_holland": "https://www.funda.nl/zoeken/huur?selected_area=[%22provincie-noord-holland%22]&publication_date=%221%22&availability=[%22available%22]",
    }

    async def start(self):
        keys_arg = getattr(self, "job_keys", None)
        extra_url = getattr(self, "extra_url", None)

        if self.item_test or keys_arg or extra_url:

            if keys_arg:
                selected_keys = [k.strip() for k in keys_arg.split(",") if k.strip()]
            elif not extra_url:
                selected_keys = list(self.FUNDA_URLS.keys())
            else:
                selected_keys = []

            for job_key in selected_keys:
                url = self.FUNDA_URLS.get(job_key)
                if not url:
                    self.logger.warning("job_key not found in FUNDA_URLS, skipping: %s", job_key)
                    continue
                yield scrapy.Request(
                    url,
                    callback=self.parse_listing,
                    meta={
                        "zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True},
                        "job_key": job_key,
                    },
                )

            # ------------------------------------------------------------------
            # Single extra URL — passed via -a extra_url="https://..."
            # ------------------------------------------------------------------
            if extra_url:
                parsed = urlparse(extra_url.strip())
                if parsed.scheme in ("http", "https") and parsed.netloc:
                    self.logger.info("Queuing extra_url: %s", extra_url)
                    yield scrapy.Request(
                        extra_url.strip(),
                        callback=self.parse_listing,
                        meta={
                            "zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True},
                            "job_key": "extra_url",
                        },
                    )
                else:
                    self.logger.warning("Invalid extra_url provided, skipping: %s", extra_url)

        else:
            yield scrapy.Request(
                "https://www.funda.nl/sitemap_index.xml/",
                callback=self.parse_sitemap_index,
                meta={"zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True}},
            )

    def parse_sitemap_index(self, response):
        sitemap_urls = response.xpath(
            "//sitemap/loc/text() | //url/loc/text()"
        ).getall()
        for url in sitemap_urls:
            if "/detail/" in url:
                yield response.follow(
                    url,
                    callback=self.parse_detail,
                    meta={"zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True}},
                )
            elif "sitemap-detail" in url:
                yield scrapy.Request(
                    url,
                    callback=self.parse_sitemap_index,
                )

    def parse_listing(self, response):
        raw_text = response.xpath(
            '//script[@data-hid="result-list-metadata"]/text()'
        ).get()

        items = []

        if not raw_text:
            return

        try:
            data = json.loads(raw_text)
            items = data.get("itemListElement", [])
            for entry in items:
                url = entry.get("url")
                if not url:
                    continue

                job_key = response.meta.get("job_key", "")
                if not job_key.startswith("sold_"):
                    if any(marker in url for marker in _SOLD_URL_MARKERS):
                        self.logger.debug("Skipping closed listing (daily run): %s", url)
                        continue

                yield response.follow(
                    url,
                    callback=self.parse_detail,
                    meta={"zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True}},
                )

        except Exception as e:
            self.logger.error("JSON parse error: %s | %s", response.url, e)

        if items:
            parsed = urlparse(response.url)
            query = parse_qs(parsed.query)
            current_page = int(query.get("page", [1])[0])
            query["page"] = [str(current_page + 1)]
            new_query = urlencode(query, doseq=True)
            next_url = urlunparse(parsed._replace(query=new_query))
            yield response.follow(
                next_url,
                callback=self.parse_listing,
                meta={
                    "zyte_api": {"httpResponseBody": True, "httpResponseHeaders": True},
                    "job_key": response.meta.get("job_key"),
                },
            )

    async def parse_detail(self, response, page: FundaListingPage):  # noqa: ARG002
        if page.status != "available":
            yield {
                "status": page.status,
                "address": attrs.asdict(page.address),
            }
        else:
            item = await page.to_item()
            yield item