import json
from urllib.parse import parse_qs, urlsplit

from backend.app.services.wikipedia_discovery import WikipediaDiscovery


def test_wikipedia_search_is_fixed_bounded_and_extracts_plain_snippets():
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, maximum):
            assert maximum == 128_001
            return json.dumps(
                {
                    "query": {
                        "search": [
                            {
                                "title": "Elastic weight consolidation",
                                "snippet": "<span>Elastic weight</span> consolidation &amp; retention.",
                            },
                            {"title": "Continual learning", "snippet": "A field of machine learning."},
                            {"title": "Ignored third page", "snippet": "Not returned."},
                        ]
                    }
                }
            ).encode("utf-8")

    def opener(request, timeout):
        requests.append((request, timeout))
        return Response()

    results = WikipediaDiscovery(opener=opener).search("continual learning", limit=8)

    assert len(results) == 2
    assert results[0].url == "https://en.wikipedia.org/wiki/Elastic_weight_consolidation"
    assert results[0].snippet == "Elastic weight consolidation & retention."
    assert results[1].title == "Continual learning"
    request, timeout = requests[0]
    query = parse_qs(urlsplit(request.full_url).query)
    assert urlsplit(request.full_url).netloc == "en.wikipedia.org"
    assert query["srlimit"] == ["2"]
    assert query["srsearch"] == ["continual learning"]
    assert timeout == 8
