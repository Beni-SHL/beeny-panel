"""Cache public, versioned code/assets without caching private panel responses."""
from pathlib import Path, PurePosixPath
from flask import request

PREFIXES = ('css/', 'js/', 'fonts/', 'vendor/', 'brand/', 'flags/')
EXTENSIONS = {'.css', '.js', '.woff', '.woff2', '.ttf', '.otf', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.gif'}

def public_asset(filename):
    path = PurePosixPath(filename)
    return (filename.startswith(PREFIXES) and '..' not in path.parts
            and '\\' not in filename and path.suffix.lower() in EXTENSIONS)

def register(app):
    version = (Path(__file__).parent / 'VERSION').read_text().strip()

    @app.before_request
    def serve_public_asset():
        filename = str((request.view_args or {}).get('filename', ''))
        # These assets are already public (including on login). Avoid session/DB
        # tracking for every font, icon and program; private routes stay unchanged.
        if request.endpoint == 'static' and request.method in {'GET', 'HEAD'} and public_asset(filename):
            return app.send_static_file(filename)

    @app.url_defaults
    def asset_version(endpoint, values):
        if endpoint == 'static' and public_asset(str(values.get('filename', ''))):
            values.setdefault('v', version)

    @app.after_request
    def public_asset_cache(response):
        filename = str((request.view_args or {}).get('filename', ''))
        if (request.endpoint == 'static' and public_asset(filename)
                and request.args.get('v') == version and response.status_code in {200, 304}):
            response.cache_control.public = True
            response.cache_control.no_cache = None
            response.cache_control.max_age = 31536000
            response.cache_control.immutable = True
        return response
