BOT_NAME = "funda_listing"

SPIDER_MODULES = ["funda_listing.spiders"]
NEWSPIDER_MODULE = "funda_listing.spiders"

ZYTE_API_KEY = "69b3fdca86744152a8bd1d48757d0e67"

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

GCS_PROJECT_ID = "real-estate-forecasting-484115"
FEED_URI_PARAMS = "funda_listing.uri_params.uri_params"

FEEDS = {
    "gs://real-estate-forecasting-raw/country=nl/actor=zyte/ingestion_date=%(date)s/%(name)s_%(time)s.json": {
        "format": "json",
    },
}