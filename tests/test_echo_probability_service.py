import importlib
import threading
import time
import unittest
from test_echo_probability import DEFAULT_TEMPLATE, MAIN, SUBS


class ProbabilityServiceTests(unittest.TestCase):
    def setUp(self):
        try:
            self.module = importlib.import_module('echo_probability_service')
        except ModuleNotFoundError as error:
            self.fail(f'Missing nonblocking probability service: {error}')

    def test_pending_computation_is_nonblocking_and_latest_request_wins(self):
        from echo_probability import calculate_tuning_probability
        started, release = threading.Event(), threading.Event()
        calls = []
        def slow(*args):
            calls.append(args[-1])
            started.set()
            release.wait(5)
            return calculate_tuning_probability(*args)
        service = self.module.TuningProbabilityService(calculate=slow)
        try:
            start = time.perf_counter()
            state = service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, 40)
            self.assertEqual(state.status, 'pending')
            self.assertLess(time.perf_counter()-start, .1)
            self.assertTrue(started.wait(1))
            for target in range(41, 61):
                self.assertEqual(service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, target).status, 'pending')
            self.assertEqual(len(calls), 1, 'Intermediate requests must not queue unbounded work')
            release.set()
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                state = service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, 60)
                if state.status == 'ready':
                    break
                time.sleep(.005)
            self.assertEqual(state.status, 'ready')
            self.assertEqual(state.result.target_score, 60)
            self.assertEqual(calls, [40, 60])
            self.assertEqual(service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, 60), state)
        finally:
            release.set()
            service.close()

    def test_invalid_rows_do_not_schedule_computation(self):
        calls = []
        service = self.module.TuningProbabilityService(calculate=lambda *args: calls.append(args))
        try:
            state = service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS + SUBS[:1], 40)
            self.assertEqual(state.status, 'invalid')
            self.assertTrue(state.reason)
            self.assertEqual(calls, [])
        finally:
            service.close()

    def test_background_failure_has_safe_status_and_close_is_idempotent(self):
        def fail(*args):
            raise RuntimeError('failure')
        service = self.module.TuningProbabilityService(calculate=fail)
        service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, 40)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            state = service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, 40)
            if state.status != 'pending':
                break
            time.sleep(.005)
        self.assertEqual(state.status, 'error')
        self.assertIsNone(state.result)
        service.close()
        service.close()
        self.assertEqual(service.request(DEFAULT_TEMPLATE, 4, MAIN, SUBS, 40).status, 'closed')


if __name__ == '__main__':
    unittest.main()
