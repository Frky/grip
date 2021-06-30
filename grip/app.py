from __future__ import print_function, unicode_literals

import base64
import json
import mimetypes
import os
import posixpath
import re
import sys
import threading
import time
from traceback import format_exc
try:
    from urlparse import urlparse
except ImportError:
    from urllib.parse import urlparse
try:
    str_type = basestring
except NameError:
    str_type = str

import requests
from flask import (
    Flask, Response, abort, redirect, render_template, request,
    send_from_directory, url_for)

from . import __version__
from .browser import start_browser_when_ready
from .constants import (
    DEFAULT_GRIPHOME, DEFAULT_GRIPURL)
from .exceptions import AlreadyRunningError, ReadmeNotFoundError
from .readers import DirectoryReader
from .renderers import ReadmeRenderer


class Grip(Flask):
    """
    A Flask application that can serve the specified file or directory
    containing a README.
    """
    def __init__(self, source=None, renderer=None,
                 render_wide=None, render_inline=None, title=None,
                 autorefresh=None, quiet=None, grip_url=None,
                 static_url_path=None, instance_path=None, **kwargs):
        # Defaults
        if source is None or isinstance(source, str_type):
            source = DirectoryReader(source)
        if render_wide is None:
            render_wide = False
        if render_inline is None:
            render_inline = False

        # Defaults from ENV
        if grip_url is None:
            grip_url = os.environ.get('GRIPURL')
            if grip_url is None:
                grip_url = DEFAULT_GRIPURL
        grip_url = grip_url.rstrip('/')
        if static_url_path is None:
            static_url_path = posixpath.join(grip_url, 'static')
        if instance_path is None:
            instance_path = os.environ.get('GRIPHOME')
            if instance_path is None:
                instance_path = DEFAULT_GRIPHOME
        instance_path = os.path.abspath(os.path.expanduser(instance_path))

        # Flask application
        super(Grip, self).__init__(
            __name__, static_url_path=static_url_path,
            instance_path=instance_path, **kwargs)
        self.config.from_object('grip.settings')
        self.config.from_pyfile('settings_local.py', silent=True)
        self.config.from_pyfile(
            os.path.join(instance_path, 'settings.py'), silent=True)

        # Defaults from settings
        if autorefresh is None:
            autorefresh = self.config['AUTOREFRESH']
        if quiet is None:
            quiet = self.config['QUIET']

        # Thread-safe event to signal to the polling threads to exit
        self._run_mutex = threading.Lock()
        self._shutdown_event = None

        # Parameterized attributes
        self.autorefresh = autorefresh
        self.reader = source
        self.renderer = renderer
        self.render_wide = render_wide
        self.render_inline = render_inline
        self.title = title
        self.quiet = quiet

        # Overridable attributes
        if self.renderer is None:
            renderer = self.default_renderer()
            if not isinstance(renderer, ReadmeRenderer):
                raise TypeError(
                    'Expected Grip.default_renderer to return a '
                    'ReadmeRenderer instance, got {0}.'.format(type(renderer)))
            self.renderer = renderer

        # Add missing content types
        self.add_content_types()

        # Construct routes
        asset_route = posixpath.join(grip_url, 'asset', '')
        asset_subpath = posixpath.join(asset_route, '<path:subpath>')
        refresh_route = posixpath.join(grip_url, 'refresh', '')
        refresh_subpath = posixpath.join(refresh_route, '<path:subpath>')
        rate_limit_route = posixpath.join(grip_url, 'rate-limit-preview')

        # Initialize views
        self.add_url_rule('/', 'render', self._render_page)
        self.add_url_rule('/<path:subpath>', 'render', self._render_page)
        self.add_url_rule(refresh_route, 'refresh', self._render_refresh)
        self.add_url_rule(refresh_subpath, 'refresh', self._render_refresh)
        self.add_url_rule(rate_limit_route, 'rate_limit',
                          self._render_rate_limit_page)
        self.errorhandler(403)(self._render_rate_limit_page)

    def _render_page(self, subpath=None):
        # Normalize the subpath
        normalized = self.reader.normalize_subpath(subpath)
        if normalized != subpath:
            return redirect(normalized)

        # Get the contextual or overridden title
        title = self.title
        if title is None:
            filename = self.reader.filename_for(subpath)
            title = ' - '.join([filename or '', 'Grip'])

        # Read the Readme text or asset
        try:
            text = self.reader.read(subpath)
        except ReadmeNotFoundError:
            abort(404)

        # Return binary asset
        if self.reader.is_binary(subpath):
            mimetype = self.reader.mimetype_for(subpath)
            return Response(text, mimetype=mimetype)

        # Render the Readme content
        try:
            content = self.renderer.render(text)
        except requests.HTTPError as ex:
            if ex.response.status_code == 403:
                abort(403)
            raise

        # Inline favicon asset
        favicon = None
        if self.render_inline:
            favicon_url = url_for('static', filename='favicon.ico')
            favicon = self._to_data_url(favicon_url, 'image/x-icon')

        autorefresh_url = (url_for('refresh', subpath=subpath)
                           if self.autorefresh
                           else None)

        return render_template(
            'index.html', title=title, content=content, favicon=favicon,
            user_content=self.renderer.user_content,
            wide_style=self.render_wide, style_urls=[],
            styles=[], autorefresh_url=autorefresh_url)

    def _render_refresh(self, subpath=None):
        if not self.autorefresh:
            abort(404)

        # Normalize the subpath
        normalized = self.reader.normalize_subpath(subpath)
        if normalized != subpath:
            return redirect(normalized)

        # Get the full filename for display
        filename = self.reader.filename_for(subpath)

        # Check whether app is running
        shutdown_event = self._shutdown_event
        if not shutdown_event or shutdown_event.is_set():
            return ''

        def gen():
            last_updated = self.reader.last_updated(subpath)
            try:
                while not shutdown_event.is_set():
                    time.sleep(0.3)

                    # Check for update
                    updated = self.reader.last_updated(subpath)
                    if updated == last_updated:
                        continue
                    last_updated = updated
                    # Notify user that a refresh is in progress
                    if not self.quiet:
                        print(' * Change detected in {0}, refreshing'
                              .format(filename))
                    yield 'data: {0}\r\n\r\n'.format(
                        json.dumps({'updating': True}))
                    # Binary assets not supported
                    if self.reader.is_binary(subpath):
                        return
                    # Read the Readme text
                    try:
                        text = self.reader.read(subpath)
                    except ReadmeNotFoundError:
                        return
                    # Render the Readme content
                    try:
                        content = self.renderer.render(text)
                    except requests.HTTPError as ex:
                        if ex.response.status_code == 403:
                            abort(403)
                        raise
                    # Return the Readme content
                    yield 'data: {0}\r\n\r\n'.format(
                        json.dumps({'content': content}))
            except GeneratorExit:
                pass

        return Response(gen(), mimetype='text/event-stream')

    def _render_rate_limit_page(self, exception=None):
        """
        Renders the rate limit page.
        """
        return render_template('limit.html', is_authenticated=False), 403

    def _download(self, url, binary=False):
        if urlparse(url).netloc:
            r = requests.get(url)
            return r.content if binary else r.text

        with self.test_client() as c:
            r = c.get(url)
            charset = r.mimetype_params.get('charset', 'utf-8')
            data = c.get(url).data
            return data if binary else data.decode(charset)

    def _to_data_url(self, url, content_type):
        asset = self._download(url, binary=True)
        asset64_bytes = base64.b64encode(asset)
        asset64_string = asset64_bytes.decode('ascii')
        return 'data:{0};base64,{1}'.format(content_type, asset64_string)

    def _match_asset(self, match):
        url = match.group(1)
        ext = os.path.splitext(url)[1][1:]
        return 'url({0})'.format(
            self._to_data_url(url, 'font/' + ext))

    def _get_styles(self, style_urls, asset_url_path):
        """
        Gets the content of the given list of style URLs and
        inlines assets.
        """
        styles = []
        for style_url in style_urls:
            urls_inline = STYLE_ASSET_URLS_INLINE_FORMAT.format(
                asset_url_path.rstrip('/'))
            asset_content = self._download(style_url)
            content = re.sub(urls_inline, self._match_asset, asset_content)
            styles.append(content)

        return styles

    def default_renderer(self):
        """
        Returns the default renderer using the current config.

        This is only used if renderer is set to None in the constructor.
        """
        return OfflineRenderer(api_url=self.config['API_URL'])

    def default_asset_manager(self):
        """
        Returns the default asset manager using the current config.

        This is only used if asset_manager is set to None in the constructor.
        """
        cache_path = None
        cache_directory = self.config['CACHE_DIRECTORY']
        if cache_directory:
            cache_directory = cache_directory.format(version=__version__)
            cache_path = os.path.join(self.instance_path, cache_directory)
        return OfflineAssetManager(cache_path, self.config['STYLE_URLS'])

    def add_content_types(self):
        """
        Adds the application/x-font-woff and application/octet-stream
        content types if they are missing.

        Override to add additional content types on initialization.
        """
        mimetypes.add_type('application/x-font-woff', '.woff')
        mimetypes.add_type('application/octet-stream', '.ttf')

    def clear_cache(self):
        raise NotImplemented

    def render(self, route=None):
        """
        Renders the application and returns the HTML unicode that would
        normally appear when visiting in the browser.
        """
        if route is None:
            route = '/'
        with self.test_client() as c:
            response = c.get(route, follow_redirects=True)
            encoding = response.charset
            return response.data.decode(encoding)

    def run(self, host=None, port=None, debug=None, use_reloader=None,
            open_browser=False):
        """
        Starts a server to render the README.
        """
        if host is None:
            host = self.config['HOST']
        if port is None:
            port = self.config['PORT']
        if debug is None:
            debug = self.debug
        if use_reloader is None:
            use_reloader = self.config['DEBUG_GRIP']

        # Verify the server is not already running and start
        with self._run_mutex:
            if self._shutdown_event:
                raise AlreadyRunningError()
            self._shutdown_event = threading.Event()

        # Open browser
        browser_thread = (
            start_browser_when_ready(host, port, self._shutdown_event)
            if open_browser else None)

        # Run local server
        super(Grip, self).run(host, port, debug=debug,
                              use_reloader=use_reloader,
                              threaded=True)

        # Signal to the polling and browser threads that they should exit
        if not self.quiet:
            print(' * Shutting down...')
        self._shutdown_event.set()

        # Wait for browser thread to finish
        if browser_thread:
            browser_thread.join()

        # Cleanup
        self._shutdown_event = None
