"""Persisted host setting controls the existing trigger interval."""
import unittest
from types import SimpleNamespace

import test_echo_probability_host as host
import test_echo_realtime as realtime

KEY='读取间隔（毫秒）'


class IntervalSettingTests(unittest.TestCase):
    setUp=host.HostIntegrationTests.setUp
    make_task=realtime.RealtimeTests.make_task

    def test_visible_integer_setting_defaults_and_uses_native_range(self):
        settings=host.load_module('echo_score_settings').EchoScoreSettingsTask()
        self.assertEqual(settings.default_config.get(KEY),1000)
        self.assertIs(type(settings.default_config[KEY]),int)
        self.assertFalse(settings.config_type[KEY].get('hidden',False))
        self.assertEqual(settings.config_type[KEY]['min'],1)
        self.assertEqual(settings.config_type[KEY]['max'],2147483647)
        self.assertIn('负载',settings.config_description[KEY])

    def test_settings_validate_positive_integer_milliseconds(self):
        settings=host.load_module('echo_score_settings').EchoScoreSettingsTask()
        for value in (1,250,1500,99999999,2147483647):
            self.assertIsNone(settings.validate_config(KEY,value),value)
        for value in (True,False,0,-1,1.5,1500.0,'1500','bad',None,float('inf'),float('nan'),2147483648):
            self.assertIsNotNone(settings.validate_config(KEY,value),repr(value))

    def test_saved_setting_mapping_applies_next_run_without_restarting(self):
        task=self.make_task()
        settings=host.load_module('echo_score_settings').EchoScoreSettingsTask()
        settings.config=dict(settings.default_config)
        task.get_tasks=lambda:[settings]
        # Exercise the same config object that the host settings widget edits.
        del task._settings
        for milliseconds,seconds in ((1500,1.5),(250,.25)):
            settings.config[KEY]=milliseconds;self.calls.clear();task.run()
            self.assertEqual(task.trigger_interval,seconds)
            self.assertEqual(self.calls,[{'frame':task.frame}])
            self.assertIs(task._settings(),settings.config)

    def test_off_on_and_missing_overlay_still_apply_saved_interval(self):
        task=self.make_task();self.settings[KEY]=1500
        self.settings['启用声骸评分']=False;task.run()
        self.assertEqual(task.trigger_interval,1.5)
        self.assertEqual(self.calls,[])
        self.settings[KEY]=250;self.settings['启用声骸评分']=True;task.run()
        self.assertEqual(task.trigger_interval,.25)
        self.calls.clear();task._ensure_overlay=lambda:None
        self.settings[KEY]=2000;task.run()
        self.assertEqual(task.trigger_interval,2)
        self.assertEqual(self.calls,[])

    def test_missing_or_invalid_stored_value_safely_falls_back(self):
        task=self.make_task()
        self.assertEqual(task.trigger_interval,1)

        for value in (None,True,0,-20,'bad','250',250.5,float('inf'),10**400):
            self.settings[KEY]=value;task.trigger_interval=.001;task.run()
            self.assertEqual(task.trigger_interval,1)
        self.settings.pop(KEY);task.trigger_interval=.25;task.run()
        self.assertEqual(task.trigger_interval,1)

    def test_ui_save_shortens_long_interval_before_next_run_and_wakes_host(self):
        task=self.make_task()
        settings=host.load_module('echo_score_settings').EchoScoreSettingsTask()
        settings.config=dict(settings.default_config)
        settings.config[KEY]=600000
        settings.get_tasks=lambda:[task]
        callbacks=[];wake=[]
        widget=SimpleNamespace(spin_box=SimpleNamespace(valueChanged=SimpleNamespace(connect=callbacks.append)))
        card=SimpleNamespace(config_widget_by_key={KEY:widget})
        # The host's public method only wakes for a trigger task, never queues it.
        task.executor=SimpleNamespace(enqueue_onetime_task=lambda t:wake.append(t) or False)
        settings._install_interval_listener(card)
        self.assertEqual(task.trigger_interval,600)
        self.assertEqual(len(callbacks),1)
        self.assertEqual(self.calls,[])
        settings.config[KEY]=250  # Native widget saves the validated value first.
        callbacks[0](250)
        self.assertEqual(task.trigger_interval,.25)
        self.assertIs(wake[-1],task)
        self.assertEqual(self.calls,[])
        settings._install_interval_listener(card)
        self.assertEqual(len(callbacks),1)
