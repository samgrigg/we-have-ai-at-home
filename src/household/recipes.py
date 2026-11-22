"""Bounded recipe data extraction and public-only, DNS-pinned HTTPS fetching."""

import html
import http.client
import ipaddress
import json
import re
import socket
import ssl
import subprocess
import sys
import time
from contextlib import closing
from fractions import Fraction
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

MAX_BYTES = 2_000_000


class RecipeError(ValueError):
    pass


def public_addresses(url):
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
            or len(url) > 2048
        ):
            raise ValueError()
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            raise ValueError()
        # Queries can contain credentials; support clean recipe permalinks only.
        if parsed.query or host.lower() == "localhost" or host.endswith("."):
            raise ValueError()
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise ValueError()
        return host, addresses
    except (ValueError, OSError) as exc:
        raise RecipeError("Use a public HTTPS recipe permalink without query parameters.") from exc


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the checked IP, but authenticate the original hostname with TLS.
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def _fetch_recipe(url):
    deadline = time.monotonic() + 25
    try:
        for _ in range(4):
            host, addresses = public_addresses(url)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RecipeError("Recipe page timed out. Paste the ingredients instead.")
            parsed = urlsplit(url)
            with closing(PinnedHTTPSConnection(host, addresses[0], min(8, remaining))) as conn:
                conn.request(
                    "GET",
                    parsed.path or "/",
                    headers={
                        "User-Agent": "HouseholdRecipeImporter/1.0",
                        "Accept": "text/html,application/xhtml+xml",
                        "Accept-Encoding": "identity",
                    },
                )
                response = conn.getresponse()
                if response.status in (301, 302, 303, 307, 308):
                    location = response.getheader("Location")
                    if not location:
                        raise RecipeError("Recipe redirect is missing its destination.")
                    url = urljoin(url, location)
                    continue
                if response.status != 200:
                    raise RecipeError(
                        "Recipe site blocked access or is unavailable. Paste the "
                        "ingredients instead."
                    )
                content_type = response.getheader("Content-Type", "").split(";")[0].strip().lower()
                if content_type not in ("text/html", "application/xhtml+xml"):
                    raise RecipeError("That link is not an HTML recipe page.")
                if response.getheader("Content-Encoding", "identity").lower() != "identity":
                    raise RecipeError("Unsupported page encoding. Paste the ingredients instead.")
                chunks = []
                size = 0
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise RecipeError("Recipe page timed out. Paste the ingredients instead.")
                    # Bound every body read, including slow streaming responses.
                    if conn.sock:
                        conn.sock.settimeout(min(8, remaining))
                    chunk = response.read1(min(65536, MAX_BYTES + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise RecipeError(
                            "Recipe page is too large. Paste the ingredients instead."
                        )
                result = extract_recipe(b"".join(chunks).decode("utf-8", errors="replace"))
                return {**result, "source_url": url}
        raise RecipeError("Too many recipe redirects. Paste the ingredients instead.")
    except RecipeError:
        raise
    except (OSError, http.client.HTTPException, UnicodeError) as exc:
        raise RecipeError(
            "Could not read that recipe page. Paste the ingredients instead."
        ) from exc


class RecipeScripts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.parts = []
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower() == "application/ld+json"
            self.parts = []

    def handle_data(self, data):
        if self.active:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.active:
            self.scripts.append("".join(self.parts))
            self.active = False


def clean_text(value, limit):
    if not isinstance(value, str):
        raise RecipeError("Recipe contains unsupported ingredient data.")
    text = " ".join(html.unescape(re.sub("<[^>]*>", "", value)).split())
    if not text or len(text) > limit:
        raise RecipeError(
            "Recipe ingredient text is missing or too long. Paste ingredients instead."
        )
    return text


def extract_recipe(document):
    parser = RecipeScripts()
    parser.feed(document)
    for script in parser.scripts:
        try:
            data = json.loads(script)
        except (ValueError, RecursionError):
            continue
        pending = [data]
        visited = 0
        while pending and visited < 2000:
            node = pending.pop()
            visited += 1
            if isinstance(node, list):
                pending.extend(reversed(node))
                continue
            if not isinstance(node, dict):
                continue
            types = node.get("@type", [])
            if isinstance(types, str):
                types = [types]
            if isinstance(types, list) and "Recipe" in types:
                ingredients = node.get("recipeIngredient")
                if not isinstance(ingredients, list) or not 1 <= len(ingredients) <= 60:
                    raise RecipeError(
                        "Recipe has no supported ingredient list. Paste ingredients instead."
                    )
                recipe_yield = node.get("recipeYield", "Not specified")
                if isinstance(recipe_yield, list):
                    recipe_yield = ", ".join(str(v) for v in recipe_yield)
                return {
                    "title": clean_text(str(node.get("name") or "Recipe"), 160),
                    "yield": clean_text(str(recipe_yield), 100),
                    "ingredients": [clean_text(i, 120) for i in ingredients],
                }
            pending.extend(reversed(list(node.values())))
    raise RecipeError("No structured recipe ingredients found. Paste the ingredients instead.")


UNICODE_FRACTIONS = {
    "¼": "1/4",
    "½": "1/2",
    "¾": "3/4",
    "⅓": "1/3",
    "⅔": "2/3",
    "⅛": "1/8",
    "⅜": "3/8",
    "⅝": "5/8",
    "⅞": "7/8",
}
NUMBER = r"(?:\d+\s+\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
QUANTITY = re.compile(r"^(" + NUMBER + r")(?:\s*[-–]\s*(" + NUMBER + r"))?(?=\s|$)")


def scale_ingredient(text, multiplier):
    if multiplier == 1:
        return text, False
    expanded = text
    for glyph, value in UNICODE_FRACTIONS.items():
        expanded = re.sub(r"(\d)" + glyph, r"\1 " + value, expanded).replace(glyph, value)
    match = QUANTITY.match(expanded)
    if not match:
        return text, True

    def scaled(value):
        amount = sum((Fraction(part) for part in value.split()), Fraction()) * Fraction(
            str(multiplier)
        )
        whole = amount.numerator // amount.denominator
        remainder = amount - whole
        return str(whole) if not remainder else (f"{whole} " if whole else "") + str(remainder)

    try:
        prefix = scaled(match[1])
        if match[2]:
            prefix += " - " + scaled(match[2])
        result = prefix + expanded[match.end() :]
        if len(result) > 120:
            raise ValueError()
        # Package sizes and quantities inside parentheses are deliberately not multiplied.
        return result, bool(re.search(r"\d", expanded[match.end() :]))
    except (ValueError, ZeroDivisionError):
        return text, True


def fetch_recipe(url):
    # Kill the reader at a wall-clock deadline, including DNS/TLS/header trickling.
    # No database credentials, API keys or household configuration go to the child.
    import os

    child_env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "SYSTEMROOT", "SSL_CERT_FILE", "SSL_CERT_DIR"}
    }
    try:
        result = subprocess.run(
            [sys.executable, "-m", "household.recipes"],
            input=json.dumps(url),
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
            env=child_env,
        )
        payload = json.loads(result.stdout)
        if result.returncode or "error" in payload:
            raise RecipeError(
                payload.get("error", "Could not read recipe. Paste ingredients instead.")
            )
        return payload
    except subprocess.TimeoutExpired as exc:
        raise RecipeError("Recipe page timed out. Paste the ingredients instead.") from exc
    except (OSError, ValueError) as exc:
        if isinstance(exc, RecipeError):
            raise
        raise RecipeError("Could not read recipe. Paste the ingredients instead.") from exc


if __name__ == "__main__":
    try:
        print(json.dumps(_fetch_recipe(json.loads(sys.stdin.read(8192)))))
    except RecipeError as exc:
        print(json.dumps({"error": str(exc)}))
        sys.exit(1)
    except Exception:
        print(json.dumps({"error": "Could not read recipe. Paste the ingredients instead."}))
        sys.exit(1)
