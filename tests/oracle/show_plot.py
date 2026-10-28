"""Stub de la capa de gráficos (nunca se usa en el test diferencial)."""
class DrawPlot(object):
    def __init__(self, *a, **k):
        pass
    def show(self):
        pass
    def plot_design(self):
        return None, {}, {}
    def plot_offtarget(self):
        return None, []
