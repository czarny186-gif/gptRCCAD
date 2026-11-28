import unittest
from unittest.mock import Mock

from rccad.jobs import JobManager
from rccad.studio import _Work


class JobsTests(unittest.TestCase):
    def test_tracks_work_with_priorities_revision_and_final_states(self):
        manager = JobManager(lambda: 12)
        pool = Mock()
        queue = manager.bind('Test', pool)
        work = _Work(lambda: 42, 'Example')
        queue.start(work, -2)
        pool.start.assert_called_once_with(work, -2)
        self.assertEqual(manager.report()['active'][0]['state'], 'queued')
        work.run()
        self.assertFalse(manager.active)
        completed = manager.report()['recent'][0]
        self.assertEqual((completed['revision'], completed['priority'], completed['state']), (12, -2, 'completed'))
        self.assertIsNotNone(completed['duration_ms'])

        def fail():
            raise ValueError('problem')

        bad = _Work(fail)
        queue.start(bad)
        bad.run()
        self.assertEqual(manager.completed[-1].state, 'failed')
        stale = _Work(lambda: None)
        queue.start(stale)
        stale.job.discarded = True
        stale.run()
        self.assertEqual(manager.completed[-1].state, 'discarded')
