from .twitter import TwitterExtractor
from .erome import EromeExtractor
from .pornhub import PornHubExtractor
from .xhamster import XHamsterExtractor
from .xvideos import XVideosExtractor
from .spankbang import SpankBangExtractor
from .redtube import RedTubeExtractor
from .generic import GenericExtractor

# Registered extractors in order of priority (specific plugins first, fallback last)
EXTRACTORS = [
    TwitterExtractor(),
    EromeExtractor(),
    PornHubExtractor(),
    XHamsterExtractor(),
    XVideosExtractor(),
    SpankBangExtractor(),
    RedTubeExtractor(),
    GenericExtractor()
]

def extract_media(url: str, cookies_path: str = None) -> tuple[list[dict], str]:
    """Orchestrates url analysis by matching url with the best available extractor."""
    for ext in EXTRACTORS:
        if ext.can_handle(url):
            try:
                media, title = ext.extract(url, cookies_path)
                if media:
                    return media, title
            except Exception as e:
                print(f"[extractors] Error using {ext.__class__.__name__}: {e}")
    return [], "VortexMedia"
