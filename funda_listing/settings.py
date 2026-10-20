import os

BOT_NAME = "funda_listing"

SPIDER_MODULES = ["funda_listing.spiders"]
NEWSPIDER_MODULE = "funda_listing.spiders"

# Zyte injects this automatically into Scrapy Cloud jobs; locally export it
# in the shell instead of committing it to the repo.
ZYTE_API_KEY = os.environ.get("ZYTE_API_KEY")

ADDONS = {
    "scrapy_zyte_api.Addon": 500,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy_poet.InjectionMiddleware": 543,
}

COOKIES_ENABLED = False

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"

EXTENSIONS = {
    "funda_listing.gcs_creds.GCSCredentials": 0,
}

# Local-development defaults. On Zyte, Dash merges the Spider Settings fields
# (FUNDA_GCS_BUCKET, FUNDA_GCS_PROJECT_ID, GCP_SA_KEY_B64) into the job's
# settings at runtime, overriding these — see uri_params.py and gcs_creds.py.
GCS_PROJECT_ID = "real-estate-forecasting-484115"
FUNDA_GCS_BUCKET = "real-estate-forecasting-raw"

FEED_URI_PARAMS = "funda_listing.uri_params.uri_params"

# %(bucket)s, %(country)s, %(date)s and %(fileid)s are filled by uri_params;
# %(time)s is a Scrapy built-in. %(fileid)s is spider-name + optional job
# label + optional Zyte job key, e.g. funda_available-buy_862318-1-348.
# %(country)s follows the crawl URL: funda.nl → nl, immoweb.be → be, and an
# immoweb.be ?countries=LU search → lu (immoweb has no .lu site — Grand-Duchy
# listings live on immoweb.be behind that filter).
FEEDS = {
    "gs://%(bucket)s/country=%(country)s/actor=zyte/ingestion_date=%(date)s/"
    "%(fileid)s_%(time)s.json": {
        "format": "json",
    },
}
