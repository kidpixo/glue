import logging

import numpy as np
try:
    import plotly
except ImportError:
    plotly = None

from ..config import exporters, settings
from ..qt.widgets import ScatterWidget, HistogramWidget


SYM = {'o': 'circle', 's': 'square', '+': 'cross', '^': 'triangle-up',
       '*': 'cross'}


def _sanitize(*arrs):
    mask = np.ones(arrs[0].shape, dtype=np.bool)
    for a in arrs:
        mask &= (~np.isnan(a))
    return tuple(a[mask].ravel() for a in arrs)


def _stack_horizontal(layout):
    layout['xaxis']['domain'] = [0, 0.45]
    layout['xaxis2']['domain'] = [0.55, 1]
    layout['yaxis2']['anchor'] = 'x2'


def _grid_2x23(layout):
    opts = {
        'xaxis': {'domain': [0, 0.45]},
        'yaxis': {'domain': [0, 0.45]},
        'xaxis2': {"domain": [0.55, 1]},
        'yaxis2': {"domain": [0, 0.45],
                   "anchor": "x2"
                   },
        'xaxis3': {
            "domain": [0, 0.45],
            "anchor": "y3"
        },
        'yaxis3': {
            "domain": [0.55, 1],
        },
        'xaxis4': {
            "domain": [0.55, 1],
            "anchor": "y4",
        },
        'yaxis4': {
            "domain": [0.55, 1],
            "anchor": "x4"
        }
    }
    for k, v in opts.items():
        if k not in layout:
            continue
        layout[k].update(**v)


def _axis(log=False, lo=0, hi=1, title=''):
    if log:
        if lo < 0:
            lo = 1e-3
        if hi < 0:
            hi = 1e-3
        lo = np.log10(lo)
        hi = np.log10(hi)

    return dict(type='log' if log else 'linear',
                rangemode='normal',
                range=[lo, hi], title=title)


def _fix_legend_duplicates(traces, layout):
    """Prevent repeat entries in the legend"""
    seen = set()
    for t in traces:
        key = (t.get('name'), t.get('marker', {}).get('color'))
        if key in seen:
            t['showlegend'] = False
        else:
            seen.add(key)


def _color(style):
    color = int(style.color[1:], base=16)
    r = color / 256 / 256
    g = color / 256 % 256
    b = color % 256
    a = style.alpha
    return 'rgba(%i, %i, %i, %0.1f)' % (r, g, b, a)


def export_scatter(viewer):
    """Export a scatter viewer to a list of
    plotly-formatted data dictionaries"""
    traces = []
    xatt, yatt = viewer.xatt, viewer.yatt
    for layer in viewer.layers:
        if not layer.visible:
            continue
        l = layer.layer
        marker = dict(symbol=SYM.get(l.style.marker, 'circle'),
                      color=_color(l.style),
                      size=l.style.markersize)

        x, y = _sanitize(l[xatt], l[yatt])
        trace = dict(x=x, y=y,
                     type='scatter',
                     mode='markers',
                     marker=marker,
                     name=l.label)

        traces.append(trace)

    xaxis = _axis(log=viewer.xlog, lo=viewer.xmin, hi=viewer.xmax,
                  title=viewer.xatt.label)
    yaxis = _axis(log=viewer.ylog, lo=viewer.ymin, hi=viewer.ymax,
                  title=viewer.yatt.label)

    return traces, xaxis, yaxis


def export_histogram(viewer):
    traces = []
    att = viewer.component
    ymax = 1e-3
    for artist in viewer.layers:
        if not artist.visible:
            continue
        layer = artist.layer
        x, y = _sanitize(artist.x[:-1], artist.y)
        trace = dict(
            name=layer.label,
            type='bar',
            marker=dict(color=_color(layer.style)),
            x=x,
            y=y)
        traces.append(trace)
        ymax = max(ymax, artist.y.max())

    xlabel = att.label
    xmin, xmax = viewer.xmin, viewer.xmax
    if viewer.xlog:
        xlabel = 'Log ' + xlabel
        xmin = np.log10(xmin)
        xmax = np.log10(xmax)
    xaxis = _axis(lo=xmin, hi=xmax, title=xlabel)
    yaxis = _axis(log=viewer.ylog, lo=0 if not viewer.ylog else 1e-3,
                  hi=ymax * 1.05)

    return traces, xaxis, yaxis


def build_plotly_call(app):
    args = []
    layout = {'showlegend': True, 'barmode': 'overlay',
              'title': 'Autogenerated by Glue'}
    dispatch = {ScatterWidget: export_scatter,
                HistogramWidget: export_histogram
                }

    ct = 1
    for tab in app.viewers:
        for viewer in tab:
            if hasattr(viewer, '__plotly__'):
                p, xaxis, yaxis = viewer.__plotly__()
            else:
                assert type(viewer) in dispatch
                p, xaxis, yaxis = dispatch[type(viewer)](viewer)

            xaxis['zeroline'] = False
            yaxis['zeroline'] = False

            suffix = '' if ct == 1 else '%i' % ct
            layout['xaxis' + suffix] = xaxis
            layout['yaxis' + suffix] = yaxis
            if ct > 1:
                yaxis['anchor'] = 'x' + suffix
                for item in p:
                    item['xaxis'] = 'x' + suffix
                    item['yaxis'] = 'y' + suffix
            ct += 1
            args.extend(p)

    nplot = sum(len(tab) for tab in app.viewers)
    if nplot == 2:
        _stack_horizontal(layout)
    if nplot > 2:
        _grid_2x23(layout)

    _fix_legend_duplicates(args, layout)
    return args, dict(layout=layout)


def can_save_plotly(application):
    """
    Check whether an application can be exported to plotly

    Raises an exception if not
    """
    if not plotly:
        raise ValueError("Plotly Export requires the plotly python library. "
                         "Please install first")

    user = application.get_setting('PLOTLY_USER')
    apikey = application.get_setting('PLOTLY_APIKEY')
    if not user or not apikey:
        raise ValueError("Plotly username and API Key required. "
                         "Please enter them in File->Edit Settings")

    for tab in application.viewers:
        for viewer in tab:
            if hasattr(viewer, '__plotly__'):
                continue

            if not isinstance(viewer, (ScatterWidget, HistogramWidget)):
                raise ValueError("Plotly Export cannot handle viewer: %s"
                                 % type(viewer))

    if len(application.viewers) != 1:
        raise ValueError("Plotly Export only supports a single tab. "
                         "Please close other tabs to export")

    nplot = sum(len(t) for t in application.viewers)
    if nplot == 0:
        raise ValueError("Plotly Export requires at least one plot")

    if nplot > 4:
        raise ValueError("Plotly Export supports at most 4 plots")


def save_plotly(application, label):
    """Save a Glue session to a plotly plot

    This is currently restricted to 1-4 scatterplots or histograms

    :param application: Glue application to save
    :param path: Label for the exported plot
    """
    user = application.get_setting('PLOTLY_USER')
    apikey = application.get_setting('PLOTLY_APIKEY')

    args, kwargs = build_plotly_call(application)
    kwargs['filename'] = label

    logging.getLogger(__name__).debug(args, kwargs)

    py = plotly.plotly(user, key=apikey)
    py.plot(args, **kwargs)


exporters.add('Plotly', save_plotly, can_save_plotly, outmode='label')
settings.add('PLOTLY_USER', '')
settings.add('PLOTLY_APIKEY', '')
