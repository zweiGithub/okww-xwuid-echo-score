"""Host boundary checks with minimal stdlib stubs, no installed OKWW/Qt needed."""
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from test_echo_probability_overlay import panel

ROOT = Path(__file__).resolve().parents[1]


class HostTask:
    def __init__(self):
        self.default_config, self.config_type, self.config_description = {}, {}, {}
        self.config = {}


def module(name, **attrs):
    result = ModuleType(name)
    result.__dict__.update(attrs)
    return result


def load_module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'echo-score' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class HostIntegrationTests(unittest.TestCase):
    def setUp(self):
        stubs = {
            'ok.util.logger': module('ok.util.logger', Logger=SimpleNamespace(get_logger=lambda *args: SimpleNamespace())),
            'ok': module('ok', BaseTask=HostTask, TriggerTask=HostTask, og=SimpleNamespace()),
            'PySide6.QtCore': module('PySide6.QtCore', Qt=SimpleNamespace()),
            'PySide6.QtWidgets': module('PySide6.QtWidgets', QCompleter=object),
            'qfluentwidgets': module('qfluentwidgets', EditableComboBox=object, SwitchButton=object),
            'ok.ui.qt.tasks.TaskCard': module('ok.ui.qt.tasks.TaskCard', TaskCard=type('TaskCard', (), {'_echo_score_card_patch': True})),
        }
        self.patch = patch.dict(sys.modules, stubs)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_target_setting_defaults_and_validation(self):
        settings = load_module('echo_score_settings').EchoScoreSettingsTask()
        self.assertIn('显示调谐概率', settings.default_config)
        self.assertEqual(settings.default_config.get('目标评分'), 40.0)
        self.assertIsNone(settings.validate_config('目标评分', 100))
        for value in (-1, float('nan'), float('inf'), 'broken'):
            self.assertIsNotNone(settings.validate_config('目标评分', value))

    def test_ocr_task_passes_settings_to_nonblocking_service_and_closes_it(self):
        settings = load_module('echo_score_settings').EchoScoreSettingsTask()
        settings.config = dict(settings.default_config, **{'显示调谐概率': True, '目标评分': 100})
        task = load_module('echo_score_task').EchoScoreOverlayTask()
        self.assertTrue(hasattr(task, 'probability_service'))
        overlay = SimpleNamespace(draw=lambda *args: None, clear_draw=lambda *args: None)
        task._ensure_overlay = lambda: overlay
        task.get_overlay_view = lambda: overlay
        task.get_tasks = lambda: (settings,)
        task.width = task.height = 1000
        task.frame = SimpleNamespace(shape=(1000, 1000, 3))
        task.ocr = lambda **kwargs: panel()
        try:
            task.run()
            deadline = time.monotonic() + 2
            while '期望终分' not in task.painter.summary and time.monotonic() < deadline:
                time.sleep(.005)
                task.run()
            self.assertIn('目标≥100.00：0%', task.painter.summary)
            settings.config['显示调谐概率'] = False
            task.run()
            self.assertEqual(len(task.painter.summary.splitlines()), 3)
            settings.config['启用声骸评分'] = False
            task.run()
            self.assertEqual(task.painter.summary, '')
        finally:
            task.on_destroy()
        self.assertTrue(task.probability_service._closed)


if __name__ == '__main__':
    unittest.main()
