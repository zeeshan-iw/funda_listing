BOT_NAME = "funda_listing"

SPIDER_MODULES = ["funda_listing.spiders"]
NEWSPIDER_MODULE = "funda_listing.spiders"

ZYTE_API_KEY = "d252364d91504c58b97bdfc0b9b9a855"

ADDONS = {
    "scrapy_zyte_api.Addon": 500,
}

DOWNLOADER_MIDDLEWARES = {
    "scrapy_poet.InjectionMiddleware": 543,   # 👈 moved here from SPIDER_MIDDLEWARES
}

# Remove SPIDER_MIDDLEWARES entirely

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"