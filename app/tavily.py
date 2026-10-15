"""Live web search through Tavily (https://tavily.com), used by the financing search."""
import httpx

from . import config


class SearchError(Exception):
    pass


def search(query: str, max_results: int = 6) -> list[dict]:
    """Returns [{"title", "url", "content"}]. Raises SearchError."""
    if not config.TAVILY_API_KEY:
        raise SearchError("Tavily is not set up (TAVILY_API_KEY is empty).")
    try:
        r = httpx.post("https://api.tavily.com/search", timeout=30,
                       headers={"Authorization": f"Bearer {config.TAVILY_API_KEY}"},
                       json={"query": query, "search_depth": "advanced", "max_results": max_results,
                             "include_answer": False})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise SearchError(f"Tavily search failed: {type(e).__name__}") from e
    return [{"title": x.get("title") or x["url"], "url": x["url"], "content": x.get("content") or ""}
            for x in r.json().get("results", []) if x.get("url")]
