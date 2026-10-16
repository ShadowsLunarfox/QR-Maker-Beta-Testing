import unittest

from qr_maker.history import History


class HistoryTests(unittest.TestCase):
    def test_undo_redo_and_editing_after_undo(self):
        history = History({"color": "black"})
        history.push({"color": "blue"})
        history.push({"color": "red"})
        self.assertEqual(history.undo(), {"color": "blue"})
        self.assertEqual(history.redo(), {"color": "red"})
        history.undo()
        history.push({"color": "green"})
        self.assertFalse(history.can_redo)
        self.assertEqual(history.undo(), {"color": "blue"})

    def test_duplicate_snapshots_and_mutation_do_not_corrupt_history(self):
        state = {"options": {"opacity": 100}}
        history = History(state)
        history.push(state)
        self.assertFalse(history.can_undo)
        state["options"]["opacity"] = 50
        history.push(state)
        previous = history.undo()
        previous["options"]["opacity"] = 1
        self.assertEqual(history.redo()["options"]["opacity"], 50)
        self.assertEqual(history.undo()["options"]["opacity"], 100)

    def test_history_is_bounded(self):
        history = History(0, limit=3)
        for number in range(1, 10):
            history.push(number)
        self.assertEqual(len(history.states), 3)
        self.assertEqual(history.undo(), 8)
        self.assertEqual(history.undo(), 7)
        self.assertFalse(history.can_undo)


if __name__ == "__main__":
    unittest.main()
