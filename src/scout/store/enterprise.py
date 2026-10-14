"""Account-scoped enterprise inputs and immutable decision/review evidence."""
from __future__ import annotations

import json
from datetime import date, datetime
from ..util import iso, local_tz
from .collection import clean_metrics

METRICS = ("play_count", "digg_count", "comment_count", "share_count")
DEFAULT_PROFILE = {
    "name": "初家汤·竹梦村", "location": "烟台市莱山区院格庄街道初家汤村",
    "goal": "通过自媒体吸引散客、增加客户", "audience": "", "features": "",
    "request": "",
    "offer": "", "constraints": "", "source": "", "feedback": "",
    "account_confirmed": False,
    "baseline_report_id": None,
}


class EnterpriseStore:
    def __init__(self, db):
        self.db = db

    def profile(self):
        row = self.db.query_one("SELECT data_json FROM enterprise_profile WHERE id=1")
        return {**DEFAULT_PROFILE, **(json.loads(row[0]) if row else {})}

    def save_profile(self, data):
        profile = {}
        for key, default in DEFAULT_PROFILE.items():
            value = data.get(key, default)
            if key == "baseline_report_id":
                if value is not None:
                    if isinstance(value, bool) or not isinstance(value, int):
                        raise ValueError("复盘报告编号格式错误")
                    self.report(value)
            elif key == "account_confirmed":
                if not isinstance(value, bool):
                    raise ValueError("账号关联确认必须为布尔值")
            else:
                if not isinstance(value, str) or len(value) > 6000:
                    raise ValueError(f"企业资料 {key} 格式错误或过长")
                value = value.strip()
            profile[key] = value
        if not profile["name"] or not profile["goal"]:
            raise ValueError("请填写企业名称与传播目标")
        if profile["feedback"] and profile["baseline_report_id"] is None:
            raise ValueError("填写执行反馈时，请选择对应的历史报告")
        self.db.upsert("enterprise_profile", ("id",), {
            "id": 1, "data_json": json.dumps(profile, ensure_ascii=False), "updated_at": iso()})
        return profile

    def works(self, limit=100):
        rows = self.db.rows_as_dicts("SELECT * FROM works WHERE is_mine=1 ORDER BY create_time DESC,aweme_id LIMIT ?", (limit,))
        return [self.enrich(row) for row in rows]

    def enrich(self, row):
        result = clean_metrics(row)
        result["metric_sources"] = {key: {"source": "接口采集", "measured_at": row.get("stats_fetched_at") or "时间未知"}
                                    for key in METRICS if result.get(key) is not None}
        manual = self.db.query_one("SELECT * FROM enterprise_metrics WHERE aweme_id=? ORDER BY measured_at DESC,id DESC LIMIT 1", (row["aweme_id"],))
        if manual:
            result["content_notes"] = manual["notes"]
            for key in METRICS:
                if manual[key] is not None:
                    result[key] = manual[key]
                    result["metric_sources"][key] = {"source": "人工补录：" + manual["source"], "measured_at": manual["measured_at"]}
        result["metric_note"] = "；".join(f"{key}: {value['source']} ({value['measured_at']})"
                                           for key, value in result["metric_sources"].items())
        return result

    def save_metrics(self, data):
        work = self.db.query_one("SELECT is_mine FROM works WHERE aweme_id=?", (data.get("aweme_id"),))
        if not work or not work["is_mine"]:
            raise ValueError("只能补录当前账号已有的本人作品")
        source = str(data.get("source") or "").strip()
        measured_at = str(data.get("measured_at") or "")
        if not source or len(source) > 1000:
            raise ValueError("请填写指标来源，如抖音后台截图名称")
        try:
            observed = date.fromisoformat(measured_at)
        except ValueError:
            raise ValueError("统计日期格式应为 YYYY-MM-DD") from None
        if observed > datetime.now(local_tz()).date():
            raise ValueError("统计日期不能晚于今天")
        values = []
        for key in METRICS:
            value = data.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 10**12):
                raise ValueError("指标须为非负整数，未知指标请留空")
            values.append(value)
        if all(value is None for value in values):
            raise ValueError("请至少填写一项真实指标")
        self.db.execute("INSERT INTO enterprise_metrics(aweme_id,measured_at,source,play_count,digg_count,comment_count,share_count,notes,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (data["aweme_id"], measured_at, source, *values, str(data.get("notes") or "")[:6000], iso()))

    def reports(self):
        rows = self.db.rows_as_dicts("SELECT r.id,r.created_at,r.model,r.prompt_version,r.input_json,"
            "(SELECT reviewed FROM enterprise_revisions v WHERE v.report_id=r.id ORDER BY v.id DESC LIMIT 1) AS reviewed "
            "FROM enterprise_reports r ORDER BY r.id DESC LIMIT 100")
        for row in rows:
            data = json.loads(row.pop("input_json"))["evidence"][0]["data"]
            row["title"] = data.get("request") or data.get("goal") or f"传播报告 {row['id']}"
        return rows

    def report(self, report_id):
        row = self.db.query_one("SELECT * FROM enterprise_reports WHERE id=?", (report_id,))
        if not row:
            raise ValueError("推广报告不存在")
        report = dict(row)
        report["input"] = json.loads(report["input_json"])
        report["output"] = json.loads(report["output_json"])
        report["revisions"] = self.db.rows_as_dicts("SELECT * FROM enterprise_revisions WHERE report_id=? ORDER BY id", (report_id,))
        return report

    def revise(self, report_id, content, reason, reviewed):
        self.report(report_id)
        if not isinstance(reviewed, bool):
            raise ValueError("人工复核状态必须为布尔值")
        if not isinstance(content, str) or not content.strip() or len(content) > 100000:
            raise ValueError("人工稿不能为空或过长")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 6000:
            raise ValueError("请填写修改或复核说明")
        self.db.execute("INSERT INTO enterprise_revisions(report_id,created_at,content,reason,reviewed) VALUES(?,?,?,?,?)",
                        (report_id, iso(), content, reason.strip(), int(bool(reviewed))))

    def metric_history(self):
        return self.db.rows_as_dicts("SELECT m.*,w.description FROM enterprise_metrics m JOIN works w ON w.aweme_id=m.aweme_id ORDER BY m.measured_at DESC,m.id DESC LIMIT 100")

    def workspace(self):
        from .conversation import Conversations
        return {"profile": self.profile(), "works": self.works(), "reports": self.reports(), "metrics": self.metric_history(),
                "conversations": Conversations(self.db).recent()}
