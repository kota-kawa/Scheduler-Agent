import unittest
import datetime
from app import app, db, CustomTask, Routine

class SeedTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        with app.app_context():
            db.create_all()

    def test_seed_functionality(self):
        # 1. Reset
        resp = self.client.post('/api/evaluation/reset')
        if resp.status_code != 200:
            print(f"Reset Failed: {resp.get_json()}")
        self.assertEqual(resp.status_code, 200)

        # 2. Seed
        resp = self.client.post('/api/evaluation/seed')
        if resp.status_code != 200:
            print(f"Seed Failed: {resp.get_json()}")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        print(f"Seed Response: {data['message']}")

        # 3. Verify
        with app.app_context():
            today = datetime.date.today()
            tomorrow = today + datetime.timedelta(days=1)
            day_after = today + datetime.timedelta(days=2)

            # Check Custom Tasks
            task_tmrw = CustomTask.query.filter_by(date=tomorrow).all()
            task_da = CustomTask.query.filter_by(date=day_after).all()
            
            print(f"Tasks for tomorrow ({tomorrow}): {[t.name for t in task_tmrw]}")
            print(f"Tasks for day after ({day_after}): {[t.name for t in task_da]}")

            self.assertTrue(any(t.name == "Lunch with Alice" for t in task_tmrw))
            self.assertTrue(any(t.name == "Doctor Appointment" for t in task_tmrw))
            self.assertTrue(any(t.name == "Gym" for t in task_da))

            # Check Routine
            routine = Routine.query.filter_by(name="Daily Routine").first()
            self.assertIsNotNone(routine)
            self.assertEqual(len(routine.steps), 3)
            print(f"Routine '{routine.name}' has {len(routine.steps)} steps.")

if __name__ == '__main__':
    unittest.main()
