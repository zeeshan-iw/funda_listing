BOT_NAME = "funda_listing"

SPIDER_MODULES = ["funda_listing.spiders"]
NEWSPIDER_MODULE = "funda_listing.spiders"

ZYTE_API_KEY = "69b3fdca86744152a8bd1d48757d0e67"

ADDONS = {
    "scrapy_zyte_api.Addon": 500,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy_poet.InjectionMiddleware": 543,   # 👈 moved here from SPIDER_MIDDLEWARES
}

# Remove SPIDER_MIDDLEWARES entirely

COOKIES_ENABLED = False

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"