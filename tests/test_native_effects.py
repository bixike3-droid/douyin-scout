"""原生效果小工具：颜色换算、平台开关、任务栏进度空转。"""
from scout.desktop.taskbar import (TBPF_INDETERMINATE, TBPF_NOPROGRESS, TaskbarProgress,
                                   state_code)
from scout.desktop.winapi import (available, backdrop_supported, border_colorref,
                                  set_border_color, system_animations_enabled)


def test_border_colorref_and_backdrop_gate():
    assert border_colorref("#3A3A41") == 0x413A3A
    assert border_colorref("#FFFFFF") == 0xFFFFFF
    assert backdrop_supported(22621) is True
    assert backdrop_supported(22000) is False
    assert backdrop_supported(19045) is False


def test_native_effects_are_safe_offscreen():
    assert available() is False                      # 测试跑在离屏平台
    assert system_animations_enabled() is True       # 离屏默认跟随开启
    assert set_border_color(0, "#000000") is False   # 无真实窗口：空转


def test_taskbar_state_mapping_and_offscreen_noop():
    assert state_code("busy") == TBPF_INDETERMINATE
    assert state_code("idle") == TBPF_NOPROGRESS
    assert state_code("unknown") == TBPF_NOPROGRESS
    progress = TaskbarProgress(None)
    progress.set_state("busy")                       # 离屏空转，不抛错
    progress.set_state("idle")
