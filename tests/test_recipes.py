import json

import pytest

from household.recipes import RecipeError, extract_recipe, public_addresses, scale_ingredient


def page(data):
    return '<html><script type="application/ld+json">' + json.dumps(data) + "</script></html>"


def test_extracts_recipe_from_nested_graph_and_decodes_text():
    recipe = extract_recipe(
        page(
            {
                "@graph": [
                    {
                        "@type": ["Thing", "Recipe"],
                        "name": "Soup &amp; beans",
                        "recipeYield": ["4 servings"],
                        "recipeIngredient": ["1 lb chicken", "½ cup corn"],
                    }
                ]
            }
        )
    )
    assert recipe == {
        "title": "Soup & beans",
        "yield": "4 servings",
        "ingredients": ["1 lb chicken", "½ cup corn"],
    }


def test_unsupported_or_oversized_recipe_fails_clearly():
    for html in [
        "<html>not a recipe</html>",
        page({"@type": "Recipe", "recipeIngredient": ["x" * 121]}),
        page({"@type": "Recipe", "recipeIngredient": ["salt"] * 61}),
    ]:
        with pytest.raises(RecipeError):
            extract_recipe(html)


@pytest.mark.parametrize(
    "host",
    [
        "localhost",
        "127.0.0.1",
        "169.254.169.254",
        "[::1]",
        "user:pass@example.com",
        "example.com:8443",
    ],
)
def test_private_or_nonstandard_urls_rejected(host):
    with pytest.raises(RecipeError):
        public_addresses("https://" + host + "/recipe")


def test_all_dns_answers_must_be_public(monkeypatch):
    monkeypatch.setattr(
        "socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443)), (2, 1, 6, "", ("10.0.0.1", 443))],
    )
    with pytest.raises(RecipeError):
        public_addresses("https://recipes.example/soup")


@pytest.mark.parametrize(
    "text,multiplier,expected",
    [
        ("1 pound chicken", 2, "2 pound chicken"),
        ("1 1/2 cups broth", 2, "3 cups broth"),
        ("½ cup corn", 3, "1 1/2 cup corn"),
        ("1/4 - 1/2 cup sauce", 2, "1/2 - 1 cup sauce"),
        ("salt to taste", 2, "salt to taste"),
    ],
)
def test_quantity_scaling(text, multiplier, expected):
    assert scale_ingredient(text, multiplier)[0] == expected


def test_redirect_to_private_address_is_never_connected(monkeypatch):
    from household.recipes import _fetch_recipe

    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    connected = []

    class Connection:
        def __init__(self, host, address, timeout):
            connected.append(host)

        def request(self, *args, **kwargs):
            pass

        def close(self):
            pass

        def getresponse(self):
            return self

        status = 302

        def getheader(self, key, default=None):
            return "https://127.0.0.1/metadata" if key == "Location" else default

    monkeypatch.setattr("household.recipes.PinnedHTTPSConnection", Connection)
    with pytest.raises(RecipeError):
        _fetch_recipe("https://recipe.example/soup")
    assert connected == ["recipe.example"]


def test_reader_enforces_total_process_deadline(monkeypatch):
    import subprocess

    from household.recipes import fetch_recipe

    def timeout(*args, **kwargs):
        assert kwargs["timeout"] == 25
        raise subprocess.TimeoutExpired("reader", 25)

    monkeypatch.setattr("subprocess.run", timeout)
    with pytest.raises(RecipeError, match="timed out"):
        fetch_recipe("https://recipe.example/slow")
