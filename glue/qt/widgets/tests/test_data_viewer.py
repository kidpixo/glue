# pylint: disable=I0011,W0613,W0201,W0212,E1101,E1103

from ....core import Data, DataCollection
from ..histogram_widget import HistogramWidget
from ..scatter_widget import ScatterWidget
from ..image_widget import ImageWidget
from ...glue_application import GlueApplication

from . import simple_session

import pytest
from mock import MagicMock

ALL_WIDGETS = [HistogramWidget, ScatterWidget, ImageWidget]


def setup_function(func):
    import os
    os.environ['GLUE_TESTING'] = 'True'


@pytest.mark.parametrize(('widget'), ALL_WIDGETS)
def test_unregister_on_close(widget):
    unreg = MagicMock()
    session = simple_session()
    hub = session.hub

    w = widget(session)
    w.unregister = unreg
    w.register_to_hub(hub)
    w.close()
    unreg.assert_called_once_with(hub)


@pytest.mark.parametrize(('widget'), ALL_WIDGETS)
def test_single_draw_call_on_create(widget):
    d = Data(x=[[1, 2], [3, 4]])
    dc = DataCollection([d])
    app = GlueApplication(dc)

    try:
        from glue.qt.widgets.mpl_widget import MplCanvas
        draw = MplCanvas.draw
        MplCanvas.draw = MagicMock()

        app.new_data_viewer(widget, data=d)

        # each Canvas instance gives at most 1 draw call
        selfs = [c[0][0] for c in MplCanvas.draw.call_arg_list]
        assert len(set(selfs)) == len(selfs)
    finally:
        MplCanvas.draw = draw
