"""Stub del popup Qt: devuelve los main targets indicados por env var."""
import os, json
class ListSelection(object):
    def __init__(self, items, *a, **k):
        self.items = items
    def exec_(self):
        return True
    def get_seletced(self, items):
        sel = os.environ.get("SIFI_MAIN_TARGETS", "")
        return [x for x in sel.split(",") if x]
