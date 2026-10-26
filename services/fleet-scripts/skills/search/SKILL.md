---
name: search
description: Search the web (SearXNG JSON API) for a fact you are unsure of; two searches per question, then decide.
---
# Web search

```
curl -s "http://searxng.search.svc.cluster.local:8080/search?q=<query>&format=json" | python3 -c 'import sys,json; [print(r["title"], r["url"], r.get("content","")[:200]) for r in json.load(sys.stdin)["results"][:8]]'
```
Two searches per question, then decide. Never browse to a search engine's own page.
