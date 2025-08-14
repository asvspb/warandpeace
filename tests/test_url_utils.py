import pytest

from src.url_utils import canonicalize_url


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            "HTTP://EXAMPLE.com:80/Path//To/?b=2&a=1&utm_source=x#frag",
            "https://example.com/Path/To?a=1&b=2",
        ),
        (
            "https://example.com:443/",
            "https://example.com/",
        ),
        (
            "http://example.com/page/?ref=abc&x=1",
            "https://example.com/page?x=1",
        ),
        (
            "https://example.com/path///",
            "https://example.com/path",
        ),
        (
            "https://example.com",
            "https://example.com/",
        ),
    ],
)
def test_canonicalize_url(raw, expected):
    assert canonicalize_url(raw) == expected
