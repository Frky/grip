from __future__ import print_function, unicode_literals

import json
import sys
from abc import ABCMeta, abstractmethod

import requests

try:
    import markdown
    from .vendor.mdx_urlize import UrlizeExtension
except ImportError:
    markdown = None
    UrlizeExtension = None

from .patcher import patch
from .vendor.six import add_metaclass


@add_metaclass(ABCMeta)
class ReadmeRenderer(object):
    """
    Renders the Readme.
    """
    def __init__(self, user_content=None, context=None):
        if user_content is None:
            user_content = False
        super(ReadmeRenderer, self).__init__()
        self.user_content = user_content
        self.context = context

    @abstractmethod
    def render(self, text, auth=None):
        """
        Renders the specified markdown content and embedded styles.
        """
        pass


class OfflineRenderer(ReadmeRenderer):
    """
    Renders the specified Readme locally using pure Python.

    Note: This is currently an incomplete feature.
    """
    def __init__(self, user_content=None, context=None):
        super(OfflineRenderer, self).__init__(user_content, context)

    def render(self, text, auth=None):
        """
        Renders the specified markdown content and embedded styles.
        """
        global markdown, UrlizeExtension
        if markdown is None:
            import markdown
        if UrlizeExtension is None:
            from .mdx_urlize import UrlizeExtension
        return markdown.markdown(text, extensions=[
            'fenced_code',
            # 'codehilite(css_class=highlight)',
            'toc',
            'tables',
            'sane_lists',
            # UrlizeExtension(),
        ])
