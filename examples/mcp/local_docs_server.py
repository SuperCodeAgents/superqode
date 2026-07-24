"""Small local MCP server used by the MCP HarnessSpec example."""

from pathlib import Path

from fastmcp import FastMCP


DOCS_ROOT = Path(__file__).resolve().parents[2] / "docs"
mcp = FastMCP("superqode-local-docs")


@mcp.tool
def search_docs(query: str, limit: int = 5) -> list[dict[str, str]]:
    """Search SuperQode Markdown documentation and return matching excerpts."""
    needle = query.strip().casefold()
    if not needle:
        return []

    matches: list[dict[str, str]] = []
    for path in sorted(DOCS_ROOT.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        offset = text.casefold().find(needle)
        if offset < 0:
            continue
        start = max(0, offset - 120)
        end = min(len(text), offset + len(query) + 240)
        excerpt = " ".join(text[start:end].split())
        matches.append(
            {
                "path": str(path.relative_to(DOCS_ROOT.parent)),
                "excerpt": excerpt,
            }
        )
        if len(matches) >= max(1, min(limit, 20)):
            break
    return matches


if __name__ == "__main__":
    mcp.run(transport="stdio")
