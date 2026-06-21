import re
import ipaddress
import socket
import urllib.parse
from bs4 import BeautifulSoup
import httpx

def clean_text(text: str) -> str:
    """Basic text cleanup: normalize whitespaces, remove extra characters."""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_domain(url: str) -> str:
    """Extracts base domain from a URL (e.g. news.bbc.co.uk -> bbc.co.uk)."""
    try:
        parsed_url = urllib.parse.urlparse(url)
        domain = parsed_url.netloc
        if not domain:
            return ""
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""

def _is_safe_url(url: str) -> bool:
    """Blocks SSRF: rejects non-http schemes, private IPs, and metadata endpoints."""
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        hostname = parsed.hostname or ""
        if not hostname:
            return False
        # Resolve hostname and check for private/reserved ranges
        for info in socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM):
            addr = info[4][0]
            ip = ipaddress.ip_address(addr)
            if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
                return False
        return True
    except Exception:
        return False

async def scrape_url(url: str) -> dict:
    """Scrapes a URL to extract its title and a main text snippet."""
    result = {
        "url": url,
        "title": "",
        "snippet": "",
        "domain": extract_domain(url),
        "error": None
    }
    
    # SSRF protection: block private IPs, non-http schemes
    if not _is_safe_url(url):
        result["error"] = "URL rejected: unsafe scheme or private/internal address"
        return result
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=10.0) as client:
            response = await client.get(url)
            
            if response.status_code != 200:
                result["error"] = f"Failed to fetch content: Status code {response.status_code}"
                return result
                
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Extract title
            title_tag = soup.find("title")
            if title_tag:
                result["title"] = clean_text(title_tag.get_text())
            
            # Extract meta description or body paragraphs for snippet
            meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            if meta_desc and meta_desc.get("content"):
                result["snippet"] = clean_text(meta_desc.get("content"))
            else:
                # Fallback to first few paragraphs
                paragraphs = soup.find_all("p")
                p_texts = [clean_text(p.get_text()) for p in paragraphs if len(p.get_text().strip()) > 30]
                result["snippet"] = " ".join(p_texts[:2])[:300]
                
            # If still empty, use heading tags
            if not result["snippet"]:
                headings = soup.find_all(["h1", "h2", "h3"])
                h_texts = [clean_text(h.get_text()) for h in headings if h.get_text().strip()]
                result["snippet"] = " ".join(h_texts[:3])[:300]
                
    except Exception as e:
        result["error"] = f"Scraping error: {str(e)}"
        
    return result
