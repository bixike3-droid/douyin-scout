"""选择题块解析：AI 回复里的 ``choices`` JSON → 可点击选项数据。"""
from scout.desktop.choices import extract_choices


def test_extract_choices_parses_and_removes_block():
    text = ('分析如下。\n\n```choices\n'
            '{"questions":[{"title":"下一步","multi":false,"options":["深入方案 A","深入方案 B"]}]}\n'
            '```\n\n收尾一句。')
    cleaned, questions = extract_choices(text)
    assert questions == [{"title": "下一步", "multi": False, "options": ["深入方案 A", "深入方案 B"]}]
    assert "choices" not in cleaned and "分析如下" in cleaned and "收尾一句" in cleaned


def test_extract_choices_accepts_dict_options_and_multi():
    text = ('```choices\n{"questions":[{"title":"偏好","multi":true,'
            '"options":[{"label":"节奏快"},{"value":"画面强"}]}]}\n```')
    _, questions = extract_choices(text)
    assert questions == [{"title": "偏好", "multi": True, "options": ["节奏快", "画面强"]}]


def test_extract_choices_ignores_invalid_json():
    cleaned, questions = extract_choices("正文\n```choices\nnot json\n```")
    assert questions == [] and cleaned == "正文"


def test_extract_choices_limits_questions_and_options():
    block = ('{"questions":['
             '{"title":"一","options":["a","b","c","d","e"]},'
             '{"title":"二","options":["a","a"]},'
             '{"title":"三","options":["x","y"]}]}')
    _, questions = extract_choices(f"```choices\n{block}\n```")
    assert len(questions) == 2                       # 最多两个问题
    assert questions[0]["options"] == ["a", "b", "c", "d"]
    assert questions[1]["title"] == "三"            # 去重后不足两项的问题被丢弃
