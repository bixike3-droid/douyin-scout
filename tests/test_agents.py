from scout.analyze import agents


def test_every_member_has_real_identity_and_prompts():
    ids = [member.id for member in agents.TEAM]
    assert len(ids) == len(set(ids))
    assert agents.DEFAULT_AGENT_ID in ids
    for member in agents.TEAM:
        assert member.name and member.role and member.persona and member.greeting
        assert member.icon in {"hub", "database", "focus", "video", "target", "history"}
        assert member.color.startswith("#") and len(member.color) == 7
        assert len(member.suggestions) >= 2
        assert all(suggestion.strip() for suggestion in member.suggestions)


def test_unknown_agent_falls_back_to_steward():
    assert agents.get(None).id == agents.DEFAULT_AGENT_ID
    assert agents.get("").id == agents.DEFAULT_AGENT_ID
    assert agents.get("不存在").id == agents.DEFAULT_AGENT_ID
    assert agents.get("audience").name == "受众分析师"
