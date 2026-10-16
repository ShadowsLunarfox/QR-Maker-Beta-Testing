"""Bounded edit history, independent of Tk and persistent settings."""

from copy import deepcopy


class History:
    def __init__(self, initial, limit=100):
        self.states = [deepcopy(initial)]
        self.position = 0
        self.limit = limit

    @property
    def can_undo(self):
        return self.position > 0

    @property
    def can_redo(self):
        return self.position < len(self.states) - 1

    def push(self, state):
        if state == self.states[self.position]:
            return
        del self.states[self.position + 1:]
        self.states.append(deepcopy(state))
        if len(self.states) > self.limit:
            del self.states[0]
        self.position = len(self.states) - 1

    def undo(self):
        if self.can_undo:
            self.position -= 1
        return deepcopy(self.states[self.position])

    def redo(self):
        if self.can_redo:
            self.position += 1
        return deepcopy(self.states[self.position])
