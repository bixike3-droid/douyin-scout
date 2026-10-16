"""Durable workflow steps and immutable handoffs, scoped to an account database."""
from __future__ import annotations

import json
import os

from ..util import iso


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class WorkflowLease:
    """OS-owned account lock: released even if the application crashes."""
    def __init__(self, state_dir):
        self.path = state_dir / "team-workflow.lock"
        self.handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+b")
        if self.path.stat().st_size == 0:
            self.handle.write(b"0")
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            raise ValueError("当前账号已有团队任务正在执行，请等待完成后再继续") from None
        return self

    def __exit__(self, *exc):
        self.handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        finally:
            self.handle.close()


class Workflows:
    def __init__(self, db):
        self.db = db

    def create(self, conversation_id, user_message_id, request, workflow, version, account_key, options, steps):
        now = iso()
        with self.db.transaction():
            cur = self.db.conn.execute(
                "INSERT INTO workflow_runs(conversation_id,user_message_id,request,workflow,version,account_key,options_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (conversation_id, user_message_id, request, workflow, version, account_key, encode(options), now, now))
            run_id = cur.lastrowid
            self.db.execute_many(
                "INSERT INTO workflow_steps(run_id,position,name,agent,updated_at) VALUES(?,?,?,?,?)",
                [(run_id, index, name, agent, now) for index, (name, agent) in enumerate(steps)])
        return self.get(run_id)

    def get(self, run_id):
        row = self.db.query_one("SELECT * FROM workflow_runs WHERE id=?", (run_id,))
        if row is None:
            raise ValueError("协作任务不存在")
        run = dict(row)
        run["options"] = json.loads(run.pop("options_json"))
        run["steps"] = self.db.rows_as_dicts("SELECT * FROM workflow_steps WHERE run_id=? ORDER BY position", (run_id,))
        for step in run["steps"]:
            step["checkpoint"] = json.loads(step.pop("checkpoint_json"))
        run["artifacts"] = self.db.rows_as_dicts("SELECT * FROM workflow_artifacts WHERE run_id=? ORDER BY id", (run_id,))
        for artifact in run["artifacts"]:
            artifact["content"] = json.loads(artifact.pop("content_json"))
            artifact["input"] = json.loads(artifact.pop("input_json"))
        return run

    def latest(self, conversation_id):
        # A running preview may still be using the schema from before the upgrade.
        if not self.db.query_one("SELECT 1 FROM sqlite_master WHERE type='table' AND name='workflow_runs'"):
            return None
        row = self.db.query_one("SELECT id FROM workflow_runs WHERE conversation_id=? ORDER BY id DESC LIMIT 1", (conversation_id,))
        return self.get(row[0]) if row else None

    def state(self, run_id, status, error=""):
        self.db.execute("UPDATE workflow_runs SET status=?,error=?,updated_at=? WHERE id=?", (status, error, iso(), run_id))

    def begin_step(self, step_id):
        self.db.execute("UPDATE workflow_steps SET status='running',attempts=attempts+1,error='',updated_at=? WHERE id=?", (iso(), step_id))

    def step_state(self, step_id, status, error=""):
        self.db.execute("UPDATE workflow_steps SET status=?,error=?,updated_at=? WHERE id=?", (status, error, iso(), step_id))

    def checkpoint(self, step_id, value):
        self.db.execute("UPDATE workflow_steps SET checkpoint_json=?,updated_at=? WHERE id=?", (encode(value), iso(), step_id))

    def artifact(self, run_id, step_id, kind, content, inputs, reply=None):
        cur = self.db.conn.execute(
            "INSERT INTO workflow_artifacts(run_id,step_id,kind,content_json,input_json,model,prompt_tokens,completion_tokens,duration_ms,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (run_id, step_id, kind, encode(content), encode(inputs), reply.model if reply else "",
             reply.prompt_tokens if reply else 0, reply.completion_tokens if reply else 0,
             reply.duration_ms if reply else 0, iso()))
        return cur.lastrowid

    def save_report(self, run_id, conversation_id, version, system, inputs, output, reply):
        from ..util import sha256_bytes
        payload = encode(inputs)
        cur = self.db.conn.execute(
            "INSERT INTO enterprise_reports(created_at,prompt_version,system_prompt,model,input_digest,input_json,output_json,prompt_tokens,completion_tokens,duration_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (iso(), version, system, reply.model, sha256_bytes(payload.encode()), payload, encode(output),
             reply.prompt_tokens, reply.completion_tokens, reply.duration_ms))
        self.db.execute("UPDATE workflow_runs SET report_id=? WHERE id=?", (cur.lastrowid, run_id))
        self.db.execute("UPDATE conversations SET report_id=? WHERE id=?", (cur.lastrowid, conversation_id))
        return cur.lastrowid

    def finish_user_message(self, message_id, status):
        self.db.execute("UPDATE conversation_messages SET status=? WHERE id=?", (status, message_id))

    def snapshot(self, *, works_limit=30, days=None):
        """Freeze inputs in one read transaction; subsequent stages never re-read live rows."""
        from .enterprise import EnterpriseStore
        from .collection import clean_metrics
        from datetime import timedelta
        from ..util import utcnow
        with self.db.transaction():
            store = EnterpriseStore(self.db)
            profile = store.profile()
            works = store.works(limit=works_limit if not days else 10000)
            if days:
                cutoff = int((utcnow() - timedelta(days=days)).timestamp())
                works = [w for w in works if w.get("create_time") is not None and w["create_time"] >= cutoff][:works_limit]
            ids = [w["aweme_id"] for w in works]
            placeholders = ",".join("?" for _ in ids)
            users = self.db.rows_as_dicts(
                "SELECT u.*,COUNT(DISTINCT i.aweme_id) AS interaction_works FROM users u "
                "JOIN v_valid_interactions i ON i.sec_uid=u.sec_uid "
                f"WHERE i.aweme_id IN ({placeholders}) GROUP BY u.sec_uid ORDER BY interaction_works DESC,u.sec_uid", ids) if ids else []
            coverage = self.db.rows_as_dicts("SELECT kind,target,state,item_count,updated_at,error FROM collection_coverage ORDER BY kind,target")
            identity = self.db.query_one("SELECT cursor FROM cursor_state WHERE name='self_sec_uid'")
        buckets = {"<100": 0, "100-999": 0, "1000-9999": 0, ">=10000": 0, "未知": 0}
        for user in users:
            count = clean_metrics(user).get("follower_count")
            key = "未知" if count is None else "<100" if count < 100 else "100-999" if count < 1000 else "1000-9999" if count < 10000 else ">=10000"
            buckets[key] += 1
        audience = {"users": len(users), "repeat_users": sum(u["interaction_works"] >= 2 for u in users),
                    "follower_buckets": buckets,
                    "missing_profiles": sum(not u.get("nickname") or clean_metrics(u).get("follower_count") is None for u in users)}
        limitations = ["仅使用本次快照中的已采集样本；未观看视频，点赞者不等于客户。",
                       "互动时间是程序观察时间，不能当成真实点赞发生时间；不能据此声称覆盖某段时间的全部点赞。",
                       "缺失指标保持未知；不同来源或时间的指标不直接相除或归因。"]
        if not profile["account_confirmed"]:
            limitations.append("尚未确认采集账号与企业的关联，账号作品不能直接证明企业传播效果。")
        if not works:
            limitations.append("本次范围内没有本人作品，作品诊断和受众分析无法成立。")
        if not users:
            limitations.append("本次作品样本没有有效互动者关联，不能形成受众画像。")
        if coverage and any(c["state"] not in ("full", "empty") for c in coverage):
            limitations.append("部分采集为抽样或未完整完成，不能将样本视为全量。")
        scope = f"近 {days} 天发布的至多 {works_limit} 条本人作品" if days else f"本机最新至多 {works_limit} 条本人作品（未限定发布日期）"
        profile = {**profile, "request": profile.get("request", "")}
        evidence = [{"id": "E1", "kind": "用户提供的企业资料，未经独立核实", "data": profile},
                    {"id": "S1", "kind": "本机样本范围与数据质量", "data": {"scope": scope, "works": len(works), "coverage": coverage}},
                    {"id": "A1", "kind": "所选作品的有效互动者统计，非客户统计", "data": audience}]
        if profile["feedback"]:
            evidence.append({"id": "E2", "kind": "用户记录的执行反馈，未经独立核实", "data": profile["feedback"]})
        if profile["baseline_report_id"]:
            with self.db.transaction():
                baseline = store.report(profile["baseline_report_id"])
            evidence.append({"id": "E3", "kind": "历史方案，仅为建议，不代表实际效果", "data": baseline["output"]})
        for index, work in enumerate(works, 1):
            evidence.append({"id": f"W{index}", "kind": "当前采集账号的本人作品及指标", "data": {
                key: work.get(key) for key in ("aweme_id", "description", "create_time", "digg_count", "comment_count", "share_count", "play_count", "content_notes", "metric_sources")}})
        for index, user in enumerate(users[:20], 1):
            cleaned = clean_metrics(user)
            evidence.append({"id": f"U{index}", "kind": "有效互动者公开资料样本，不能推断消费能力或到店意愿", "data": {
                "nickname": cleaned.get("nickname"), "signature": str(cleaned.get("signature") or "")[:200],
                "follower_count": cleaned.get("follower_count"), "interaction_works": user["interaction_works"]}})
        return {"captured_at": iso(), "account_uid": identity[0] if identity else "", "scope": scope,
                "works_count": len(works), "audience": audience, "evidence": evidence, "limits": limitations}
