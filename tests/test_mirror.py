"""响应镜像的匹配与过滤测试。

这里的 bug 特别阴：过滤器写错了不会报错，只表现为"捕获 0、空返回"，
看上去像"这个页面没有接口"，实际上是自己的模式匹配没生效。
"""

from __future__ import annotations

from scout.session.mirror import DEFAULT_INCLUDE, CapturedResponse, _matches, looks_like_data

NOTICE_URL = (
    "https://www.douyin.com/aweme/v1/web/notice/"
    "?device_platform=webapp&aid=6383&notice_group=960&count=10"
)


def test_absolute_url_matches_leading_slash_pattern():
    """真实踩过的坑：/aweme/v1/web/* 匹配不上 https://... 开头的绝对 URL。

    fnmatch 是整串匹配，模式以 / 开头而 URL 以 https: 开头，永远不命中。
    结果采集器把所有响应都挡掉了，还一声不响。
    """
    assert _matches(NOTICE_URL, ("/aweme/v1/web/*",)) is True


def test_default_include_matches_notice_api():
    assert _matches(NOTICE_URL, DEFAULT_INCLUDE) is True


def test_substring_pattern_matches():
    assert _matches(NOTICE_URL, ("/aweme/v1/web/notice",)) is True


def test_non_matching_url_is_rejected():
    assert _matches("https://lf-douyin-pc-web.douyinstatic.com/x.js", ("/aweme/v1/",)) is False


def test_empty_pattern_list_means_capture_everything():
    assert _matches("https://anything", ()) is True


def test_empty_string_pattern_is_ignored():
    assert _matches(NOTICE_URL, ("", "/aweme/v1/")) is True


def test_star_prefixed_pattern_still_works():
    assert _matches(NOTICE_URL, ("*notice*",)) is True


# ── 静态资源过滤 ─────────────────────────────────────────────


def _resp(url, ct, resource_type=""):
    return CapturedResponse(url=url, status=200, content_type=ct, resource_type=resource_type)


def test_document_is_always_kept():
    """抖音会把数据 SSR 进 HTML，主文档必须保留。"""
    assert looks_like_data("text/html", "https://www.douyin.com/user/self", "document") is True


def test_js_and_css_are_skipped():
    assert looks_like_data("application/javascript", "https://x.com/a.js", "script") is False
    assert looks_like_data("text/css", "https://x.com/a.css", "stylesheet") is False


def test_json_is_kept():
    assert looks_like_data("application/json", "https://x.com/whatever", "xhr") is True


def test_protobuf_is_kept():
    assert looks_like_data("application/x-protobuf", "https://imapi.douyin.com/v1/x", "xhr") is True


def test_notice_api_kept_even_without_json_content_type():
    assert looks_like_data("", NOTICE_URL, "xhr") is True


def test_is_data_uses_resource_type():
    doc = _resp("https://www.douyin.com/user/self", "text/html", "document")
    js = _resp("https://x.com/a.js", "application/javascript", "script")
    assert doc.is_data is True
    assert js.is_data is False


def test_api_path_strips_query():
    assert _resp(NOTICE_URL, "application/json").api_path == "/aweme/v1/web/notice/"
