class BaseExtractor:
    """Base interface for all Vortex media extractors."""
    
    def can_handle(self, url: str) -> bool:
        """Returns True if this extractor can handle the given URL."""
        raise NotImplementedError
        
    def extract(self, url: str, cookies_path: str = None) -> tuple[list[dict], str]:
        """Extracts media items and page title from the given URL.
        
        Returns:
            tuple: (media_items_list, page_title)
        """
        raise NotImplementedError
