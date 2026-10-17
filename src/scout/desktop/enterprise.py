"""Native enterprise brief, editable decisions and sourced metric entry."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLineEdit,
    QPlainTextEdit, QPushButton, QCheckBox, QComboBox, QTabWidget, QScrollArea, QSplitter,
    QFileDialog, QMessageBox)
from .components import card, text
from ..analyze.enterprise import render_output, export_report
from ..store.enterprise import METRICS
from ..util import local_tz, parse_iso


class EnterprisePage(QWidget):
    save_requested = Signal(object)
    generate_requested = Signal(bool)
    report_requested = Signal(int)
    revision_requested = Signal(object)
    metrics_requested = Signal(object)
    metric_vision_requested = Signal(str, str)
    notice = Signal(str)

    def __init__(self):
        super().__init__()
        self.profile_dirty = False
        self.report_dirty = False
        self.loaded = False
        self.current_report = None
        self.applying = False
        self.fields = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        intro, intro_layout = card("从作品表现到内容决策", "填写企业资料 → 复盘作品 → 生成建议 → 人工复核 → 执行后记录反馈")
        intro_layout.addWidget(text("企业目标：通过自媒体吸引散客。作品互动是内容表现证据，实际引流效果需要咨询、预约或到店记录支持。", "muted"))
        layout.addWidget(intro)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.tabs.addTab(self._profile_page(), "企业资料")
        self.tabs.addTab(self._report_page(), "传播决策")
        self.tabs.addTab(self._metrics_page(), "作品数据补录")

    def _profile_page(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        grid = QGridLayout()
        entries = [("name", "企业名称", "初家汤·竹梦村"), ("location", "经营地点", "实际地点"),
                   ("goal", "企业传播目标", "例如：通过自媒体吸引散客咨询"),
                   ("audience", "目标客群与依据", "未确定时留空，由分析列为待验证项"),
                   ("features", "已确认的文旅特色", "填写实地核实的特色与体验，避免泛泛宣传"),
                   ("offer", "主要产品与体验", "当前实际提供的体验；价格、时间、预约方式只填已确认信息"),
                   ("constraints", "执行条件与限制", "人员、预算、拍摄条件、接待能力、允许发布的渠道"),
                   ("source", "资料来源与确认时间", "例如：运营方访谈日期、产品资料名称"),
                   ("feedback", "执行反馈与下轮复盘", "记录执行了哪项建议、对应作品、统计周期、咨询/预约结果与来源；未知请写未知")]
        for index, (key, title, placeholder) in enumerate(entries):
            title_label = text(title, "sectionTitle")
            title_label.setFixedWidth(180)
            grid.addWidget(title_label, index, 0)
            field = QPlainTextEdit() if key in ("features", "offer", "constraints", "feedback") else QLineEdit()
            if isinstance(field, QPlainTextEdit):
                field.setFixedHeight(78)
                field.setObjectName("enterpriseField")
            field.setPlaceholderText(placeholder)
            field.textChanged.connect(self._profile_changed)
            self.fields[key] = field
            grid.addWidget(field, index, 1)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        self.feedback_report = QComboBox()
        self.feedback_report.addItem("记录执行反馈时，请选择对应报告", None)
        self.feedback_report.currentIndexChanged.connect(self._profile_changed)
        layout.addWidget(self.feedback_report)
        self.account_confirmed = QCheckBox("我确认当前账号的本人作品与竹梦村本次宣传相关，允许用于企业分析")
        self.account_confirmed.toggled.connect(self._profile_changed)
        footer = QWidget()
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 4, 0, 0)
        footer_layout.addWidget(self.account_confirmed)
        footer_layout.addWidget(text("首次进入未关联账号。关联确认后，当前账号作品才会进入企业分析。", "muted"))
        row = QHBoxLayout()
        self.save_profile_button = QPushButton("保存企业资料")
        self.save_profile_button.setObjectName("primary")
        self.save_profile_button.clicked.connect(lambda: self.save_requested.emit(self.profile_data()))
        row.addWidget(self.save_profile_button)
        row.addStretch()
        footer_layout.addLayout(row)
        layout.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(scroll, 1)
        container_layout.addWidget(footer)
        return container

    def _profile_changed(self, *args):
        if not self.applying:
            self.profile_dirty = True

    def profile_data(self):
        result = {key: field.toPlainText() if isinstance(field, QPlainTextEdit) else field.text()
                  for key, field in self.fields.items()}
        result["account_confirmed"] = self.account_confirmed.isChecked()
        result["baseline_report_id"] = self.feedback_report.currentData()
        return result

    def _report_page(self):
        pane = QWidget()
        layout = QVBoxLayout(pane)
        row = QHBoxLayout()
        self.report_select = QComboBox()
        self.report_select.setMinimumWidth(240)
        self.report_select.currentIndexChanged.connect(self._select_report)
        row.addWidget(self.report_select, 1)
        self.force = QCheckBox("重新生成")
        row.addWidget(self.force)
        self.generate_button = QPushButton("生成竹梦村传播建议")
        self.generate_button.setObjectName("primary")
        self.generate_button.clicked.connect(self._generate)
        row.addWidget(self.generate_button)
        layout.addLayout(row)
        layout.addWidget(text("使用自己的 DeepSeek 服务；企业资料、已关联作品的标题/统计及执行反馈会发送至该服务。相同输入默认复用报告。", "muted"))
        self.report_state = text("保存企业特色、推广产品和资料来源后，可生成建议。", "muted")
        layout.addWidget(self.report_state)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        left, left_layout = card("建议与人工稿", "可直接编辑；原始模型建议另行保存。")
        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText("这里将显示传播诊断、内容优化、选题及策略建议。")
        self.editor.textChanged.connect(self._report_changed)
        left_layout.addWidget(self.editor, 1)
        right, right_layout = card("输入依据", "证据编号对应本次生成时的资料快照。")
        self.evidence = QPlainTextEdit()
        self.evidence.setReadOnly(True)
        right_layout.addWidget(self.evidence, 1)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([650, 300])
        layout.addWidget(splitter, 1)
        self.reason = QLineEdit()
        self.reason.setPlaceholderText("修改或复核说明：核实了什么、改了什么、为什么")
        self.reason.textChanged.connect(self._review_changed)
        layout.addWidget(self.reason)
        row = QHBoxLayout()
        self.reviewed = QCheckBox("已人工核对本稿事实与执行条件")
        self.reviewed.toggled.connect(self._review_changed)
        row.addWidget(self.reviewed, 1)
        self.save_revision_button = QPushButton("保存人工稿")
        self.save_revision_button.clicked.connect(self._save_revision)
        row.addWidget(self.save_revision_button)
        self.export_button = QPushButton("导出决策记录")
        self.export_button.clicked.connect(self._export)
        row.addWidget(self.export_button)
        layout.addLayout(row)
        return pane

    def _generate(self):
        if self.profile_dirty:
            self.tabs.setCurrentIndex(0)
            self.notice.emit("请先保存企业资料，再生成建议")
        elif self._discard_report_changes():
            self.generate_requested.emit(self.force.isChecked())

    def _report_changed(self):
        if not self.applying:
            self.report_dirty = True
            self.reviewed.setChecked(False)
            self.report_state.setText("人工稿尚未保存；修改后需要重新复核")

    def _review_changed(self, *args):
        if not self.applying and self.current_report:
            self.report_dirty = True

    def _discard_report_changes(self):
        if not self.report_dirty:
            return True
        answer = QMessageBox.question(self, "人工稿尚未保存", "继续会放弃未保存的修改。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes

    def _select_report(self):
        report_id = self.report_select.currentData()
        if report_id is None or (self.current_report and report_id == self.current_report["id"]):
            return
        if self._discard_report_changes():
            self.report_requested.emit(report_id)
        elif self.current_report:
            self.report_select.blockSignals(True)
            self.report_select.setCurrentIndex(self.report_select.findData(self.current_report["id"]))
            self.report_select.blockSignals(False)

    def _save_revision(self):
        if self.current_report:
            self.revision_requested.emit({"report_id": self.current_report["id"], "content": self.editor.toPlainText(),
                "reason": self.reason.text(), "reviewed": self.reviewed.isChecked()})
        else:
            self.notice.emit("请先生成或选择推广报告")

    def _export(self):
        if not self.current_report:
            self.notice.emit("请先生成或选择推广报告")
            return
        if self.report_dirty:
            self.notice.emit("请先保存人工稿，避免导出旧版本")
            return
        target, _ = QFileDialog.getSaveFileName(self, "导出传播决策记录", f"竹梦村传播决策-{self.current_report['id']}.md", "Markdown (*.md)")
        if target:
            try:
                Path(target).write_text(export_report(self.current_report), encoding="utf-8")
                self.notice.emit("决策记录已导出，包含输入依据、原始建议和人工修改记录")
            except OSError as exc:
                self.notice.emit(f"导出失败：{exc}")

    def _metrics_page(self):
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.addWidget(text("接口缺少播放量时，可按后台真实数据补录。仅补录当前账号已有的本人作品；留空表示未知，0表示真实为零。", "muted"))
        self.work_select = QComboBox()
        layout.addWidget(self.work_select)
        grid = QGridLayout()
        self.metric_fields = {}
        for index, (key, title) in enumerate(zip(METRICS, ("播放量", "点赞量", "评论量", "转发量"))):
            field = QLineEdit()
            field.setMinimumHeight(40)
            field.setPlaceholderText("未知留空")
            self.metric_fields[key] = field
            grid.addWidget(text(title, "sectionTitle"), index // 2 * 2, index % 2)
            grid.addWidget(field, index // 2 * 2 + 1, index % 2)
        layout.addLayout(grid)
        self.metric_date = QLineEdit(datetime.now(local_tz()).date().isoformat())
        self.metric_date.setPlaceholderText("统计日期 YYYY-MM-DD")
        layout.addWidget(self.metric_date)
        self.metric_source = QLineEdit()
        self.metric_source.setPlaceholderText("来源：后台导出文件或截图名称（必填）")
        layout.addWidget(self.metric_source)
        self.metric_notes = QLineEdit()
        self.metric_notes.setPlaceholderText("内容说明/脚本摘要、统计口径及本次内容调整说明")
        layout.addWidget(self.metric_notes)
        vision_row = QHBoxLayout()
        self.vision_button = QPushButton("识别后台截图")
        self.vision_button.setToolTip("上传创作者中心截图，自动读出播放/点赞/评论/转发（需核对）")
        self.vision_button.clicked.connect(self._pick_metric_image)
        vision_row.addWidget(self.vision_button)
        self.vision_state = text("也可以用截图识别自动填入，保存前请逐项核对。", "muted")
        vision_row.addWidget(self.vision_state, 1)
        layout.addLayout(vision_row)
        self.metrics_button = QPushButton("保存指标快照")
        self.metrics_button.setObjectName("primary")
        self.metrics_button.clicked.connect(self._save_metrics)
        layout.addWidget(self.metrics_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(text("历史快照保留在下方；同一作品按统计日期取最新补录值，原始接口数据不被覆盖。", "muted"))
        self.metric_history = QPlainTextEdit()
        self.metric_history.setReadOnly(True)
        self.metric_history.setMinimumHeight(110)
        layout.addWidget(self.metric_history, 1)
        body.setMinimumHeight(590)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        return scroll

    def _pick_metric_image(self):
        if self.work_select.currentData() is None:
            self.notice.emit("请先选择作品，再识别截图")
            return
        target, _ = QFileDialog.getOpenFileName(self, "选择后台数据截图", "",
                                                "图片 (*.png *.jpg *.jpeg *.webp *.gif)")
        if not target:
            return
        self.vision_button.setEnabled(False)
        self.vision_state.setText("正在识别截图（约 10–30 秒，结果需人工核对）…")
        self.metric_vision_requested.emit(str(target), str(self.work_select.currentData()))

    def apply_metric_vision(self, result):
        """识别结果回填表单（不自动保存）：只填看清的字段，其余保留原值。"""
        self.vision_button.setEnabled(True)
        if not isinstance(result, dict) or not result.get("ok"):
            self.vision_state.setText((result or {}).get("error") or "识别失败")
            return
        data = result.get("data") or {}
        for key, field in self.metric_fields.items():
            value = data.get(key)
            if value is not None:
                field.setText(str(value))
        if data.get("collected_at"):
            self.metric_date.setText(data["collected_at"])
        self.metric_source.setText(f"AI 识别截图（{result.get('filename') or '请核对'}）")
        notes = [f"识别置信度：{data.get('confidence') or '未知'}"]
        if data.get("missing"):
            notes.append("未识别：" + "、".join(data["missing"]))
        if data.get("notes"):
            notes.append(data["notes"])
        existing = self.metric_notes.text().strip()
        self.metric_notes.setText("；".join(notes + ([existing] if existing else []))[:200])
        self.vision_state.setText("识别完成，请逐项核对后再保存快照")

    def _save_metrics(self):
        data = {"aweme_id": self.work_select.currentData(), "source": self.metric_source.text(),
                "measured_at": self.metric_date.text(), "notes": self.metric_notes.text()}
        try:
            for key, field in self.metric_fields.items():
                value = field.text().strip()
                data[key] = int(value) if value else None
        except ValueError:
            self.notice.emit("指标请填写整数；未知指标留空")
            return
        self.metrics_requested.emit(data)

    def apply_workspace(self, data, *, saved=False):
        self.applying = True
        if not self.loaded or saved or not self.profile_dirty:
            for key, field in self.fields.items():
                value = data["profile"][key]
                field.setPlainText(value) if isinstance(field, QPlainTextEdit) else field.setText(value)
            self.account_confirmed.setChecked(data["profile"]["account_confirmed"])
            self.profile_dirty = False
        self.loaded = True
        baseline_id = self.feedback_report.currentData() if self.profile_dirty else data["profile"].get("baseline_report_id")
        self.feedback_report.clear()
        self.feedback_report.addItem("记录执行反馈时，请选择对应报告", None)
        for report in data["reports"]:
            self.feedback_report.addItem(f"复盘报告 {report['id']} · {report_time(report['created_at'])}", report["id"])
        self.feedback_report.setCurrentIndex(max(0, self.feedback_report.findData(baseline_id)))
        current = self.work_select.currentData()
        self.work_select.clear()
        for work in data["works"]:
            self.work_select.addItem(f"{(work.get('description') or '无标题')[:55]} · {work['aweme_id']}", work["aweme_id"])
        found = self.work_select.findData(current)
        if found >= 0:
            self.work_select.setCurrentIndex(found)
        self.report_select.blockSignals(True)
        self.report_select.clear()
        for report in data["reports"]:
            self.report_select.addItem(f"报告 {report['id']} · {report_time(report['created_at'])}", report["id"])
        if self.current_report:
            self.report_select.setCurrentIndex(self.report_select.findData(self.current_report["id"]))
        self.report_select.blockSignals(False)
        self.metric_history.setPlainText("\n\n".join(
            f"{r['measured_at']} · {r['description'] or r['aweme_id']}\n"
            + " · ".join(f"{title}：{r[key] if r[key] is not None else '未知'}" for key, title in zip(METRICS, ("播放", "点赞", "评论", "转发")))
            + f"\n来源：{r['source']}\n备注：{r['notes']}" for r in data["metrics"]) or "暂无补录记录")
        self.applying = False
        if not self.current_report and data["reports"] and not getattr(self, "new_task_mode", False) and not getattr(self, "conversation_id", None):
            self.report_requested.emit(data["reports"][0]["id"])

    def apply_report(self, report):
        self.applying = True
        self.current_report = report
        last = report["revisions"][-1] if report["revisions"] else None
        self.editor.setPlainText(last["content"] if last else render_output(report["output"]))
        self.evidence.setPlainText(render_evidence(report["input"]))
        self.reviewed.setChecked(bool(last and last["reviewed"]))
        self.reason.clear()
        self.report_dirty = False
        self.report_select.blockSignals(True)
        self.report_select.setCurrentIndex(self.report_select.findData(report["id"]))
        self.report_select.blockSignals(False)
        self.report_state.setText(f"报告 {report['id']} · {report['model']} · {report['prompt_version']} · "
                                 + ("用户已复核" if last and last["reviewed"] else "待人工复核"))
        self.applying = False


def render_evidence(data):
    names = {"name": "企业", "location": "地点", "goal": "目标", "audience": "目标客群",
             "features": "文旅特色", "offer": "推广产品", "constraints": "执行限制", "source": "资料来源"}
    lines = []
    for item in data["evidence"]:
        lines.append(f"【{item['id']}】{item['kind']}")
        details = item["data"]
        if isinstance(details, str):
            lines.append(details)
        elif "metrics" in details:
            lines.append("作品：" + (details.get("description") or "无标题"))
            lines.append("作品标识：" + details["aweme_id"])
            for key, title in zip(METRICS, ("播放量", "点赞量", "评论量", "转发量")):
                value = details["metrics"].get(key)
                lines.append(f"{title}：{value if value is not None else '未获取'}")
                source = details["metric_sources"].get(key)
                if source:
                    lines.append(f"  来源：{source['source']} · {source['measured_at']}")
            if details.get("user_content_notes"):
                lines.append("人工说明：" + details["user_content_notes"])
        elif "prior_suggestions" in details:
            lines.append("历史稿复核状态：" + ("用户已复核" if details["human_reviewed"] else "未复核"))
            lines.append(details["prior_suggestions"])
        else:
            lines.extend(f"{names.get(key, key)}：{value or '未填写'}" for key, value in details.items())
        lines.append("")
    lines += ["【分析范围】"] + data["limits"]
    return "\n".join(lines)


def report_time(value):
    try:
        return parse_iso(value).astimezone(local_tz()).strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(value)
