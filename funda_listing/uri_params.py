import os
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse


def _label_from_url(url: str) -> str:
    """Derive a crawl label like 'available-buy' or 'negotiations-rent'.

    Describes WHAT was crawled, from the URL itself: the transaction type
    from the path (koop/huur) and the availability filter from the query
    (funda's 'negotiations' = onder bod, 'unavailable' = sold). Purely
    descriptive — crawl behaviour never depends on it.
    """
    parsed = urlparse(url or "")
    kind = "rent" if "/huur" in parsed.path.lower() else "buy" if "/koop" in parsed.path.lower() else ""
    avail = (parse_qs(parsed.query).get("availability") or [""])[0].lower()
    if any(x in avail for x in ("unavailable", "verhuurd")):
        status = "sold"
    elif "negotiation" in avail:
        status = "negotiations"
    else:
        status = "available"
    return "-".join(p for p in (status, kind) if p)


def uri_params(params, spider):
    """Fill the placeholders in the FEEDS URI.

    %(bucket)s reads FUNDA_GCS_BUCKET from the job settings, so the upload
    target can be changed from the Zyte Dash (Spider Settings) without a
    redeploy; the local fallback keeps `scrapy crawl` working off-Zyte.

    %(country)s routes the file into the right country folder, derived from
    the crawl itself: funda.nl → nl, immoweb.be → be, and an immoweb.be
    ?countries=LU search → lu (immoweb has no .lu site — Luxembourg
    listings live on immoweb.be behind that filter).

    The filename is %(fileid)s_%(time)s.json, where fileid joins — in order,
    each only when present:

      - the spider name (always, e.g. "funda" / "immoweb")
      - the crawl label: an explicit -a job=... argument wins; otherwise,
        for funda it is derived from the crawl URL's koop/huur path and
        availability filter (available-buy / negotiations-rent / sold-buy,
        suffixed with '-status' when the URL came via status_only), while
        immoweb uses the same <status>-<kind>[-<place>] convention the
        spider derives from its URL (available-buy / available-rent-brussels)
      - the platform job key (e.g. 862318-1-348) when running on Zyte,
        tying the file to the exact job in Dash

    e.g. funda_sold-buy-status_862318-1-348_2026-09-09T19-00-48+00-00.json
    or   immoweb_available-rent-brussels_862318-1-348_<time>.json
    """
    crawl_url = params.get("status_only") or params.get("extra_url") or ""
    if getattr(spider, "name", "") == "immoweb":
        # Immoweb searches carry no koop/huur or availability params; the
        # label + region logic in the spider's __init__ runs before the feed
        # opens, so its attributes are read here. Region routes the country
        # folder (luxembourg → lu, everything else → be).
        label = params.get("job") or getattr(spider, "label", "") or "search"
        country = "lu" if getattr(spider, "region", "") == "luxembourg" else "be"
    else:
        # The crawl URL arrives as extra_url (full mode) or status_only
        # (status + address records); the label describes the URL's content.
        label = params.get("job") or _label_from_url(crawl_url)
        if params.get("status_only") and not params.get("job"):
            label = f"{label}-status" if label else "status"
        country = "nl"
    jobkey = os.environ.get("SHUB_JOBKEY", "").replace("/", "-")
    return {
        **params,
        "bucket": spider.settings.get(
            "FUNDA_GCS_BUCKET", "real-estate-forecasting-raw"
        ),
        "country": country,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "fileid": "_".join(p for p in (params.get("name"), label, jobkey) if p),
    }
