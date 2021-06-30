from __future__ import print_function, unicode_literals

import errno
import os
import posixpath
import re
import sys
import shutil
from abc import ABCMeta, abstractmethod
try:
    from urlparse import urljoin
except ImportError:
    from urllib.parse import urljoin

import requests
from flask import safe_join

from .vendor.six import add_metaclass


@add_metaclass(ABCMeta)
class ReadmeAssetManager(object):
    """
    Manages the style and font assets rendered with Readme pages.

    Set cache_path to None to disable caching.
    """
    def __init__(self, cache_path, style_urls=None):
        super(ReadmeAssetManager, self).__init__()
        self.cache_path = cache_path
        self.style_urls = list(style_urls) if style_urls else []
        self.styles = []

    def _stip_url_params(self, url):
        return url.rsplit('?', 1)[0].rsplit('#', 1)[0]

    def clear(self):
        """
        Clears the asset cache.
        """
        if self.cache_path and os.path.exists(self.cache_path):
            shutil.rmtree(self.cache_path)

    def cache_filename(self, url):
        """
        Gets a suitable relative filename for the specified URL.
        """
        # FUTURE: Use url exactly instead of flattening it here
        url = posixpath.basename(url)
        return self._stip_url_params(url)

    @abstractmethod
    def retrieve_styles(self, asset_url_path):
        """
        Get style URLs from the source HTML page and specified cached asset
        URL path.
        """
        pass


class OfflineAssetManager(ReadmeAssetManager):
    """
    Reads the styles used for rendering Readme pages.

    Set cache_path to None to disable caching.
    """
    def __init__(self, cache_path, style_urls=None):
        super(OfflineAssetManager, self).__init__(cache_path, style_urls)

    def _get_style_urls(self, asset_url_path):
        """
        Gets the specified resource and parses all style URLs and their
        assets in the form of the specified patterns.
        """
        raise NotImplemented

    def _get_cached_style_urls(self, asset_url_path):
        """
        Gets the URLs of the cached styles.
        """
        raise NotImplemented

    def _cache_contents(self, style_urls, asset_url_path):
        """
        Fetches the given URLs and caches their contents
        and their assets in the given directory.
        """
        raise NotImplemented

    def retrieve_styles(self, asset_url_path):
        """
        Get style URLs from the source HTML page and specified cached
        asset base URL.
        """
        raise NotImplemented
