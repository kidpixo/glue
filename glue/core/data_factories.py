""" Factory methods to build Data objects from files"""

"""
Implementation notes:

Each factory method conforms to the folowing structure, which
helps the GUI Frontend easily load data:

1) The first argument is a file name to open

2) The return value is a Data object

3) The function has a .label attribute that describes (in human
language) what kinds of files it understands

4) The function has a callable .identifier attribute that returns
whether it can handle a requested filename and keyword set

5) The function is added to the __factories__ list

6) Optionally, the function is registered to open a given extension by
default by calling set_default_factory

Putting this together, the simplest data factory code looks like this::

    def dummy_factory(file_name):
        return glue.core.Data()
    dummy_factory.label = "Foo file"
    dummy_factory.identifier = has_extension('foo FOO')
    __factories__.append(dummy_factory)
    set_default_factory("foo", dummy_factory)
"""
import os

import numpy as np

from .data import Component, Data, CategoricalComponent
from .io import extract_data_fits, extract_data_hdf5
from .util import file_format, as_list
from .coordinates import coordinates_from_header, coordinates_from_wcs
from ..external.astro import fits


__all__ = ['load_data', 'gridded_data', 'casalike_cube',
           'tabular_data', 'img_data', 'auto_data']
__factories__ = []
_default_factory = {}


def _extension(path):
    # extract the extension type from a path
    #  test.fits -> fits
    #  test.fits.gz -> fits.gz (special case)
    #  a.b.c.fits -> fits
    _, path = os.path.split(path)
    if '.' not in path:
        return ''
    stems = path.split('.')[1:]

    # special case: test.fits.gz -> fits.gz
    if len(stems) > 1 and any(x == stems[-1]
                              for x in ['gz', 'gzip', 'bz', 'bz2']):
        return '.'.join(stems[-2:])
    return stems[-1]


def has_extension(exts):
    """
    A simple default filetype identifier function

    It returns a function that tests whether its input
    filename contains a particular extension

    Inputs
    ------
    exts : str
      A space-delimited string listing the extensions
      (e.g., 'txt', or 'txt csv fits')

    Returns
    -------
    A function suitable as a factory identifier function
    """

    def tester(x, **kwargs):
        return _extension(x) in set(exts.split())
    return tester


def is_hdf5(filename):
    # All hdf5 files begin with the same sequence
    with open(filename) as infile:
        return infile.read(8) == '\x89HDF\r\n\x1a\n'


def is_fits(filename):
    try:
        with fits.open(filename):
            return True
    except IOError:
        return False


class LoadLog(object):

    """
    This class attaches some metadata to data created
    from load_data, so that the data can be re-constructed
    when loading saved state. It's only meant to be used
    within load_data
    """

    def __init__(self, path, factory, kwargs):
        self.path = os.path.abspath(path)
        self.factory = factory
        self.kwargs = kwargs
        self.components = []
        self.data = []

    def _log_component(self, component):
        self.components.append(component)

    def _log_data(self, data):
        self.data.append(data)

    def log(self, obj):
        if isinstance(obj, Component):
            self._log_component(obj)
        elif isinstance(obj, Data):
            self._log_data(obj)
        obj._load_log = self

    def id(self, component):
        return self.components.index(component)

    def component(self, index):
        return self.components[index]

    def __gluestate__(self, context):
        return dict(path=self.path,
                    factory=context.do(self.factory),
                    kwargs=[list(self.kwargs.items())])

    @classmethod
    def __setgluestate__(cls, rec, context):
        fac = context.object(rec['factory'])
        kwargs = dict(*rec['kwargs'])
        d = load_data(rec['path'], factory=fac, **kwargs)
        return as_list(d)[0]._load_log


def load_data(path, factory=None, **kwargs):
    """Use a factory to load a file and assign a label.

    This is the preferred interface for loading data into Glue,
    as it logs metadata about how data objects relate to files
    on disk.

    :param path: Path to a file
    :param factory: factory function to use. Defaults to :func:`auto_data`

    Extra keywords are passed through to factory functions
    """
    factory = factory or auto_data
    d = factory(path, **kwargs)
    lbl = data_label(path)

    log = LoadLog(path, factory, kwargs)
    for item in as_list(d):
        item.label = lbl
        log.log(item)
        for cid in item.primary_components:
            log.log(item.get_component(cid))
    return d


def data_label(path):
    """Convert a file path into a data label, by stripping out
    slashes, file extensions, etc."""
    _, fname = os.path.split(path)
    name, _ = os.path.splitext(fname)
    return name


def set_default_factory(extension, factory):
    """Register an extension that should be handled by a factory by default

    :param extension: File extension (do not include the '.')
    :param factory: The factory function to dispatch to
    """
    for ex in extension.split():
        _default_factory[ex] = factory


def get_default_factory(extension):
    """Return the default factory function to read a given file extension.

    :param extension: The extension to lookup

    :rtype: A factory function, or None if the extension has no default
    """
    try:
        return _default_factory[extension]
    except KeyError:
        return None


def find_factory(filename, **kwargs):
    from ..config import data_factory

    # on first pass, only try the default factory
    default = _default_factory.get(_extension(filename))
    for func, _, identifier in data_factory:
        if func is auto_data:
            continue
        if (func is default) and identifier(filename, **kwargs):
            return func

    # if that fails, try everything
    for func, _, identifier in data_factory:
        if func is auto_data:
            continue
        if identifier(filename, **kwargs):
            return func


def auto_data(filename, *args, **kwargs):
    """Attempt to automatically construct a data object"""
    fac = find_factory(filename, **kwargs)
    if fac is None:
        raise KeyError("Don't know how to open file: %s" % filename)
    return fac(filename, *args, **kwargs)

auto_data.label = 'Auto'
auto_data.identifier = lambda x: True
__factories__.append(auto_data)


def gridded_data(filename, format='auto', **kwargs):
    """
    Construct an n - dimensional data object from ``filename``. If the
    format cannot be determined from the extension, it can be
    specified using the ``format`` option. Valid formats are 'fits' and
    'hdf5'.
    """
    result = Data()

    # Try and automatically find the format if not specified
    if format == 'auto':
        format = file_format(filename)

    # Read in the data
    if is_fits(filename):
        arrays = extract_data_fits(filename, **kwargs)
        header = fits.getheader(filename)
        result.coords = coordinates_from_header(header)
    elif is_hdf5(filename):
        arrays = extract_data_hdf5(filename, **kwargs)
    else:
        raise Exception("Unkonwn format: %s" % format)

    for component_name in arrays:
        comp = Component.autotyped(arrays[component_name])
        result.add_component(comp, component_name)
    return result


def is_gridded_data(filename, **kwargs):
    if is_hdf5(filename):
        return True

    if is_fits(filename):
        with fits.open(filename) as hdulist:
            for hdu in hdulist:
                if not isinstance(hdu, (fits.PrimaryHDU, fits.ImageHDU)):
                    return False
            return True
    return False


gridded_data.label = "FITS/HDF5 Image"
gridded_data.identifier = is_gridded_data
__factories__.append(gridded_data)
set_default_factory('fits', gridded_data)
set_default_factory('hd5', gridded_data)
set_default_factory('hdf5', gridded_data)


def casalike_cube(filename, **kwargs):
    """
    This provides special support for 4D CASA - like cubes,
    which have 2 spatial axes, a spectral axis, and a stokes axis
    in that order.

    Each stokes cube is split out as a separate component
    """
    result = Data()
    with fits.open(filename, **kwargs) as hdulist:
        array = hdulist[0].data
        header = hdulist[0].header
    result.coords = coordinates_from_header(header)
    for i in range(array.shape[0]):
        result.add_component(array[[i]], label='STOKES %i' % i)
    return result


def is_casalike(filename, **kwargs):
    """
    Check if a file is a CASA like cube,
    with (P, P, V, Stokes) layout
    """
    if not is_fits(filename):
        return False
    with fits.open(filename) as hdulist:
        if len(hdulist) != 1:
            return False
        if hdulist[0].header['NAXIS'] != 4:
            return False

        from astropy.wcs import WCS
        w = WCS(hdulist[0].header)

    ax = [a.get('coordinate_type') for a in w.get_axis_types()]
    return ax == ['celestial', 'celestial', 'spectral', 'stokes']


casalike_cube.label = 'CASA PPV Cube'
casalike_cube.identifier = is_casalike


def _ascii_identifier_v02(origin, args, kwargs):
    # this works for astropy v0.2
    if isinstance(args[0], basestring):
        return args[0].endswith(('csv', 'tsv', 'txt', 'tbl', 'dat',
                                 'csv.gz', 'tsv.gz', 'txt.gz', 'tbl.gz',
                                 'dat.gz'))
    else:
        return False


def _ascii_identifier_v03(origin, *args, **kwargs):
    # this works for astropy v0.3
    return _ascii_identifier_v02(origin, args, kwargs)


def tabular_data(*args, **kwargs):
    """
    Build a data set from a table. We restrict ourselves to tables
    with 1D columns.

    All arguments are passed to
        astropy.table.Table.read(...).
    """
    from distutils.version import LooseVersion
    from astropy import __version__
    if LooseVersion(__version__) < LooseVersion("0.2"):
        raise RuntimeError("Glue requires astropy >= v0.2. Please update")

    result = Data()

    # Read the table
    from astropy.table import Table

    # Add identifiers for ASCII data
    from astropy.io import registry
    if LooseVersion(__version__) < LooseVersion("0.3"):
        registry.register_identifier('ascii', Table, _ascii_identifier_v02,
                                     force=True)
    else:
        registry.register_identifier('ascii', Table, _ascii_identifier_v03,
                                     force=True)
        # Clobber the identifier
        # added in astropy/astropy/pull/1935
        registry.register_identifier('ascii.csv', Table, lambda *a, **k: False,
                                     force=True)

    # Import FITS compatibility (for Astropy 0.2.x)
    from ..external import fits_io

    table = Table.read(*args, **kwargs)

    # Loop through columns and make component list
    for column_name in table.columns:
        c = table[column_name]
        u = c.units

        if table.masked:
            # fill array for now
            try:
                c = c.filled(fill_value=np.nan)
            except ValueError:  # assigning nan to integer dtype
                c = c.filled(fill_value=-1)

        nc = Component.autotyped(c, units=u)
        result.add_component(nc, column_name)

    return result

tabular_data.label = "Catalog"
tabular_data.identifier = has_extension('xml vot csv txt tsv tbl dat fits '
                                        'xml.gz vot.gz csv.gz txt.gz tbl.bz '
                                        'dat.gz fits.gz')

__factories__.append(tabular_data)
set_default_factory('xml', tabular_data)
set_default_factory('vot', tabular_data)
set_default_factory('csv', tabular_data)
set_default_factory('txt', tabular_data)
set_default_factory('tsv', tabular_data)
set_default_factory('tbl', tabular_data)
set_default_factory('dat', tabular_data)


def panda_process(indf):
    """
    Build a data set from a table using pandas. This attempts to respect
    categorical data input by letting pandas.read_csv infer the type

    """

    result = Data()
    for name, column in indf.iteritems():
        if (column.dtype == np.object) | (column.dtype == np.bool):
            # pandas has a 'special' nan implementation and this doesn't
            # play well with np.unique
            c = CategoricalComponent(column.fillna(np.nan))
        else:
            c = Component(column.values)
        result.add_component(c, name)

    return result


def panda_read_excel(path, sheet='Sheet1', **kwargs):
    """ A factory for reading excel data using pandas.
    :param path: path/to/file
    :param sheet: The sheet to read
    :param kwargs: All other kwargs are passed to pandas.read_excel
    :return: core.data.Data object.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError('Pandas is required for Excel input.')

    indf = pd.read_excel(path, sheet, **kwargs)
    return panda_process(indf)

panda_read_excel.label = "Excel"
panda_read_excel.identifier = has_extension('xls xlsx')
__factories__.append(panda_read_excel)
set_default_factory('xls', panda_read_excel)
set_default_factory('xlsx', panda_read_excel)


def pandas_read_table(path, **kwargs):
    """ A factory for reading tabular data using pandas
    :param path: path/to/file
    :param kwargs: All kwargs are passed to pandas.read_csv
    :returns: :class:`glue.core.data.Data` object
    """
    import pandas as pd

    # iterate over common delimiters to search for best option
    delimiters = kwargs.pop('delimiter', [None] + list(',|\t '))

    fallback = None

    for d in delimiters:
        try:
            indf = pd.read_csv(path, delimiter=d, **kwargs)

            # ignore files parsed to empty dataframes
            if len(indf) == 0:
                continue

            # only use files parsed to single-column dataframes
            # if we don't find a better strategy
            if len(indf.columns) < 2:
                fallback = indf
                continue

            return panda_process(indf)

        except pd._parser.CParserError:
            continue

    if fallback is not None:
        return panda_process(fallback)
    raise IOError("Could not parse %s using pandas" % path)

pandas_read_table.label = "Pandas Table"
pandas_read_table.identifier = has_extension('csv csv txt tsv tbl dat')
__factories__.append(pandas_read_table)


img_fmt = ['jpg', 'jpeg', 'bmp', 'png', 'tiff', 'tif']


def img_loader(file_name):
    """Load an image to a numpy array, using either PIL or skimage

    :param file_name: Path of file to load
    :rtype: Numpy array
    """
    try:
        from skimage.io import imread
        return np.asarray(imread(file_name))
    except ImportError:
        pass

    try:
        from PIL import Image
        return np.asarray(Image.open(file_name))
    except ImportError:
        raise ImportError("Reading %s requires PIL or scikit-image" %
                          file_name)


def img_data(file_name):
    """Load common image files into a Glue data object"""
    result = Data()

    data = img_loader(file_name)
    data = np.flipud(data)
    shp = data.shape

    comps = []
    labels = []

    # split 3 color images into each color plane
    if len(shp) == 3 and shp[2] in [3, 4]:
        comps.extend([data[:, :, 0], data[:, :, 1], data[:, :, 2]])
        labels.extend(['red', 'green', 'blue'])
        if shp[2] == 4:
            comps.append(data[:, :, 3])
            labels.append('alpha')
    else:
        comps = [data]
        labels = ['PRIMARY']

    # look for AVM coordinate metadata
    try:
        from pyavm import AVM
        avm = AVM(str(file_name))  # avoid unicode
        wcs = avm.to_wcs()
    except:
        pass
    else:
        result.coords = coordinates_from_wcs(wcs)

    for c, l in zip(comps, labels):
        result.add_component(c, l)

    return result

img_data.label = "Image"
img_data.identifier = has_extension(' '.join(img_fmt))
for i in img_fmt:
    set_default_factory(i, img_data)

__factories__.append(img_data)
__factories__.append(casalike_cube)
