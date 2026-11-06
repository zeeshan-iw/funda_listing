# Automatically created by: shub deploy

from setuptools import setup, find_packages

setup(
    name         = 'project',
    version      = '1.0',
    packages     = find_packages(include=['funda_listing*']),
    entry_points = {'scrapy': ['settings = funda_listing.settings']},
)
