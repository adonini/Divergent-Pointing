import h5py
import numpy as np
from astropy.table import Table, vstack
import tables
from tables import open_file
import os
import pandas as pd

import ctapipe
from ctapipe.io import HDF5TableReader
from ctapipe.io.containers import MCHeaderContainer
from ctapipe.io import HDF5TableWriter
from eventio import Histograms
from eventio.search_utils import yield_toplevel_of_type
from ctapipe.io.containers import Container, Field


__all__ = ['read_simu_info_hdf5',
           'read_simu_info_merged_hdf5',
           'get_dataset_keys',
           'write_simtel_energy_histogram',
           'write_mcheader',
           'write_array_info',
           'check_thrown_events_histogram',
           'check_mcheader',
           'check_metadata',
           'read_metadata',
           'auto_merge_h5files',
           'smart_merge_h5files',
           'global_metadata',
           'add_global_metadata',
           'write_subarray_tables',
           'write_metadata',
           'write_dataframe',
           'write_dl2_dataframe'
           ]



class ExtraMCInfo(Container):
    obs_id = Field(0, "MC Run Identifier")

class ExtraImageInfo(Container):
    """ attach the tel_id """
    tel_id = Field(0, "Telescope ID")
    event_id = Field(0, "event ID")
    obs_id = Field(0, "obs ID")

class EventInfo(Container):
    event_id = Field(0, "telescope ID")
    obs_id = Field(0, "obs ID")


class ThrownEventsHistogram(Container):
    """ 2D histogram from SimTel files """
    obs_id = Field(-1, 'MC run ID')
    hist_id = Field(-1, 'Histogram ID')
    num_entries = Field(-1, 'Number of entries in the histogram')
    bins_energy = Field(None, 'array of energy bin lower edges, as in np.histogram')
    bins_core_dist = Field(None, 'array of core-distance bin lower edges, as in np.histogram')
    histogram = Field(None, "array of histogram entries, size (n_bins_x, n_bins_y)")

    def fill_from_simtel(self, hist):
        """ fill from a SimTel Histogram entry"""
        self.hist_id = hist['id']
        self.num_entries = hist['entries']
        xbins = np.linspace(hist['lower_x'], hist['upper_x'], hist['n_bins_x'] + 1)
        ybins = np.linspace(hist['lower_y'], hist['upper_y'], hist['n_bins_y'] + 1)
        self.bins_core_dist = xbins
        self.bins_energy = 10 ** ybins
        self.histogram = hist['data']
        self.meta['hist_title'] = hist['title']
        self.meta['x_label'] = 'Log10 E (TeV)'
        self.meta['y_label'] = '3D Core Distance (m)'


class MetaData(Container):
    """
    Some metadata
    """
    SOURCE_FILENAMES = Field([], "filename of the source file")
    LSTCHAIN_VERSION = Field(None, "version of lstchain")
    CTAPIPE_VERSION = Field(None, "version of ctapipe")
    CONTACT = Field(None, "Person or institution responsible for this data product")




def read_simu_info_hdf5(filename):
    """
    Read simu info from an hdf5 file

    Returns
    -------
    `ctapipe.containers.MCHeaderContainer`
    """

    with HDF5TableReader(filename) as reader:
        mcheader = reader.read('/simulation/run_config', MCHeaderContainer())
        mc = next(mcheader)

    return mc


def read_simu_info_merged_hdf5(filename):
    """
    Read simu info from a merged hdf5 file.
    Check that simu info are the same for all runs from merged file
    Combine relevant simu info such as num_showers (sum)
    Note: works for a single run file as well

    Parameters
    ----------
    filename: path to an hdf5 merged file

    Returns
    -------
    `ctapipe.containers.MCHeaderContainer`

    """
    with open_file(filename) as file:
        simu_info = file.root['simulation/run_config']
        colnames = simu_info.colnames
        colnames.remove('num_showers')
        colnames.remove('shower_prog_start')
        colnames.remove('detector_prog_start')
        for k in colnames:
            assert np.all(simu_info[:][k] == simu_info[0][k])
        num_showers = simu_info[:]['num_showers'].sum()

    combined_mcheader = read_simu_info_hdf5(filename)
    combined_mcheader['num_showers'] = num_showers
    return combined_mcheader


def get_dataset_keys(filename):
    """
    Return a list of all dataset keys in a HDF5 file

    Parameters
    ----------
    filename: str - path to the HDF5 file

    Returns
    -------
    list of keys
    """
    dataset_keys = []
    def walk(name, obj):
        if type(obj) == h5py._hl.dataset.Dataset:
            dataset_keys.append(name)

    with h5py.File(filename, 'r') as file:
        file.visititems(walk)

    return dataset_keys


def get_stacked_table(filenames_list, node):
    """
    Stack tables at node from each file in files

    Parameters
    ----------
    filenames_list: list of paths
    node: str

    Returns
    -------
    `astropy.table.Table`
    """
    try:
        files = [open_file(filename) for filename in filenames_list]
    except:
        print("Can't open files")

    table_list = [Table(file.root[node][:]) for file in files]
    [file.close() for file in files]

    return vstack(table_list)


def stack_tables_h5files(filenames_list, output_filename='merged.h5', keys=None):
    """
    In theory similar to auto_merge_h5files but slower. Keeping it for reference.
    Merge h5 files produced by lstchain using astropy.
    A list of keys (corresponding to file nodes) that need to be included in the merge can be given.
    If None, all tables in the file will be merged.

    Parameters
    ----------
    filenames_list: list of str
    output_filename: str
    keys: None or list of str
    """

    keys = get_dataset_keys(filenames_list[0]) if keys is None else keys

    for k in keys:
        merged_table = get_stacked_table(filenames_list, k)
        merged_table.write(output_filename, path=k, append=True)



def auto_merge_h5files(file_list, output_filename='merged.h5', nodes_keys=None):
    """
    Automatic merge of HDF5 files.
    A list of nodes keys can be provided to merge only these nodes. If None, all nodes are merged.

    Parameters
    ----------
    file_list: list of path
    output_filename: path
    nodes_keys: list of path
    """

    if nodes_keys is None:
        keys = get_dataset_keys(file_list[0]) if nodes_keys is None else nodes_keys
    groups = set([k.split('/')[0] for k in keys])

    f1 = open_file(file_list[0])
    merge_file = open_file(output_filename, 'w')

    nodes = {}
    for g in groups:
        nodes[g] = f1.copy_node('/', name=g, newparent=merge_file.root, newname=g, recursive=True)


    for filename in file_list[1:]:
        with open_file(filename) as file:
            for k in keys:
                try:
                    merge_file.root[k].append(file.root[k].read())
                except:
                    print("Can't append node {} from file {}".format(k, filename))

    merge_file.close()


def merging_check(file_list):
    """
    Check that a list of hdf5 files are compatible for merging regarding:
     - array info
     - MC simu info
     - MC histograms
     - metadata

    Parameters
    ----------
    file_list: list of paths to hdf5 files
    """
    assert len(file_list) > 1, "The list of files is too short"

    filename0 = file_list[0]
    array_info0 = read_array_info(filename0)
    mcheader0 = read_simu_info_hdf5(filename0)
    thrown_events_hist0 = read_simtel_energy_histogram(filename0)
    metadata0 = read_metadata(filename0)
    for filename in file_list[1:]:
        mcheader = read_simu_info_hdf5(filename)
        thrown_events_hist = read_simtel_energy_histogram(filename)
        metadata = read_metadata(filename)
        check_metadata(metadata0, metadata)
        check_mcheader(mcheader0, mcheader)
        check_thrown_events_histogram(thrown_events_hist0, thrown_events_hist)
        for ii, table in read_array_info(filename).items():
            assert (table == array_info0[ii]).all()


def smart_merge_h5files(file_list, output_filename='merged.h5'):
    """
    Check that HDF5 files are compatible for merging and merge them

    Parameters
    ----------
    file_list: list of paths to hdf5 files
    output_filename: path to the merged file
    """
    merging_check(file_list)
    auto_merge_h5files(file_list, output_filename)

    # Merge metadata
    metadata0 = read_metadata(file_list[0])
    for file in file_list[1:]:
        metadata = read_metadata(file)
        check_metadata(metadata0, metadata)
        metadata0.SOURCE_FILENAMES.extend(metadata.SOURCE_FILENAMES)
    write_metadata(metadata0, output_filename)


def write_simtel_energy_histogram(source, output_filename, obs_id=None, filters=None, metadata={}):
    """
    Write the energy histogram from a simtel source to a HDF5 file

    Parameters
    ----------
    source: `ctapipe.io.event_source`
    output_filename: str
    obs_id: float, int, str or None
    """
    # Writing histograms
    with HDF5TableWriter(filename=output_filename, group_name="simulation", mode="a", filters=filters) as writer:
        writer.meta = metadata
        for hist in yield_toplevel_of_type(source.file_, Histograms):
            pass
        # find histogram id 6 (thrown energy)
        thrown = None
        for hist in source.file_.histograms:
            if hist['id'] == 6:
                thrown = hist

        thrown_hist = ThrownEventsHistogram()
        thrown_hist.fill_from_simtel(thrown)
        thrown_hist.obs_id = obs_id
        if metadata is not None:
            add_global_metadata(thrown_hist, metadata)
        writer.write('thrown_event_distribution', [thrown_hist])


def read_simtel_energy_histogram(filename):
    """
    Read the simtel energy histogram from a HDF5 file.

    Parameters
    ----------
    filename: path

    Returns
    -------
    `lstchain.io.lstcontainers.ThrownEventsHistogram`
    """
    with HDF5TableReader(filename=filename) as reader:
        histtab = reader.read('/simulation/thrown_event_distribution', ThrownEventsHistogram())
        hist = next(histtab)
    return hist


def write_mcheader(mcheader, output_filename, obs_id=None, filters=None, metadata={}):
    """
    Write the mcheader from an event container to a HDF5 file

    Parameters
    ----------
    output_filename: str
    event: `ctapipe.io.DataContainer`
    """

    extramc = ExtraMCInfo()
    extramc.prefix = ''  # get rid of the prefix
    if metadata is not None:
        add_global_metadata(mcheader, metadata)
        add_global_metadata(extramc, metadata)

    with HDF5TableWriter(filename=output_filename, group_name="simulation", mode="a", filters=filters) as writer:
        extramc.obs_id = obs_id
        writer.write("run_config", [extramc, mcheader])


def write_array_info(event, output_filename):
    """
    Write the array info to a HDF5 file
        - layout info is writen in '/instrument/subarray/layout'
        - optics info is writen in '/instrument/telescope/optics'
        - camera info is writen in '/instrument/telescope/camera/{camera}' for each camera in the array

    Parameters
    ----------
    event: `ctapipe.io.DataContainer`
    output_filename: str
    """

    serialize_meta = True

    sub = event.inst.subarray
    sub.to_table().write(
        output_filename,
        path="/instrument/subarray/layout",
        serialize_meta=serialize_meta,
        append=True
    )
    sub.to_table(kind='optics').write(
        output_filename,
        path='/instrument/telescope/optics',
        append=True,
        serialize_meta=serialize_meta
    )
    for telescope_type in sub.telescope_types:
        ids = set(sub.get_tel_ids_for_type(telescope_type))
        if len(ids) > 0:  # only write if there is a telescope with this camera
            tel_id = list(ids)[0]
            camera = sub.tel[tel_id].camera
            camera.to_table().write(
                output_filename,
                path=f'/instrument/telescope/camera/{camera}',
                append=True,
                serialize_meta=serialize_meta,
            )


def read_array_info(filename):
    """
    Read array information from HDF5 file.

    Parameters
    ----------
    filename: path

    Returns
    -------
    dict
    """
    array_info = dict()
    with open_file(filename) as file:
        array_info['layout'] = Table(file.root['/instrument/subarray/layout'].read())
        array_info['optics'] = Table(file.root['/instrument/telescope/optics'].read())
        for camera in file.root['/instrument/telescope/camera/']:
            if type(camera) is tables.table.Table:
                array_info[camera.name] = Table(camera.read())
    return array_info


def check_mcheader(mcheader1, mcheader2):
    """
    Check that the information in two mcheaders are physically consistent.

    Parameters
    ----------
    mcheader1: `ctapipe.io.containers.MCHeaderContainer`
    mcheader2: `ctapipe.io.containers.MCHeaderContainer`

    Returns
    -------

    """
    assert mcheader1.keys() == mcheader2.keys()
    # It does not matter that the number of simulated showers is the same
    keys = list(mcheader1.keys())
    keys.remove('num_showers') #should not be checked
    keys.remove('run_array_direction') #specific comparison

    for k in keys:
        assert mcheader1[k] == mcheader2[k]
    assert (mcheader1['run_array_direction'] == mcheader2['run_array_direction']).all()


def check_thrown_events_histogram(thrown_events_hist1, thrown_events_hist2):
    """
    Check that two ThrownEventsHistogram class are compatible with each other

    Parameters
    ----------
    thrown_events_hist1: `lstchain.io.lstcontainers.ThrownEventsHistogram`
    thrown_events_hist2: `lstchain.io.lstcontainers.ThrownEventsHistogram`
    """
    assert thrown_events_hist1.keys() == thrown_events_hist2.keys()
    # It does not matter that the number of simulated showers is the same
    keys = ['bins_energy', 'bins_core_dist']
    for k in keys:
        assert (thrown_events_hist1[k] == thrown_events_hist2[k]).all()


def write_metadata(metadata, output_filename):
    """
    Write metadata to a HDF5 file

    Parameters
    ----------
    source: `ctapipe.io.event_source`
    output_filename: path
    """
    # One cannot write strings with ctapipe HDF5Writer and Tables can write only fixed length string
    # So this metadata is written in the file attributes
    with open_file(output_filename, mode='a') as file:
        for k, item in metadata.as_dict().items():
            if k in file.root._v_attrs and type(item) is list:
                attribute = file.root._v_attrs[k].extend(metadata[k])
                file.root._v_attrs[k] = attribute
            else:
                file.root._v_attrs[k] = metadata[k]



def read_metadata(filename):
    """
    Read metadata from a HDF5 file

    Parameters
    ----------
    filename: path
    """
    metadata = MetaData()
    with open_file(filename) as file:
        for k in metadata.keys():
            try:
                metadata[k] = file.root._v_attrs[k]
            except:
                # this ensures retro and forward reading compatibility
                print("Metadata {} does not exist in file {}".format(k, filename))
    return metadata


def check_metadata(metadata1, metadata2):
    """
    Check that to MetaData class are compatible with each other

    Parameters
    ----------
    metadata1: `lstchain.io.MetaData`
    metadata2: `lstchain.io.MetaData`
    """
    assert metadata1.keys() == metadata2.keys()
    keys = ['LSTCHAIN_VERSION']
    for k in keys:
        assert metadata1[k] == metadata2[k]


def global_metadata(source):
    """
    Get global metadata container

    Returns
    -------
    `lstchain.io.lstcontainers.MetaData`
    """
    metadata = MetaData()
    metadata.CTAPIPE_VERSION = ctapipe.__version__
    metadata.CONTACT = 'Divergent Pointing group'
    metadata.SOURCE_FILENAMES.append(os.path.basename(source.input_url))

    return metadata


def add_global_metadata(container, metadata):
    """
    Add global metadata to a container in container.meta

    Parameters
    ----------
    container: `ctapipe.io.containers.Container`
    metadata: `lstchain.io.lstchainers.MetaData`
    """
    meta_dict = metadata.as_dict()
    for k, item in meta_dict.items():
        container.meta[k] = item


def write_subarray_tables(writer, event, metadata=None):
    """
    Write subarray tables info to a HDF5 file

    Parameters
    ----------
    writer: `ctapipe.io.HDF5Writer`
    event: `ctapipe.io.containers.DataContainer`
    metadata: `lstchain.io.lstcontainers.MetaData`
    """
    if metadata is not None:
        add_global_metadata(event.dl0, metadata)
        add_global_metadata(event.mc, metadata)
        add_global_metadata(event.trig, metadata)

    writer.write(table_name="subarray/mc_shower", containers=[event.dl0, event.mc])
    writer.write(table_name="subarray/trigger", containers=[event.dl0, event.trig])


def write_dataframe(dataframe, outfile, table_path):
    """
    Write a pandas dataframe to a HDF5 file using pytables formatting.

    Parameters
    ----------
    dataframe: `pandas.DataFrame`
    outfile: path
    table_path: str - path to the table to write in the HDF5 file
    """
    with pd.HDFStore(outfile, mode='a') as store:
        path, table_name = table_path.rsplit('/', maxsplit=1)
        store.append(path, dataframe,
                     format='table',
                     data_columns=True)
        store.get_node(os.path.join(path, 'table'))._f_rename(table_name)


def write_dl2_dataframe(dataframe, outfile):
    """
    Write DL2 dataframe to a HDF5 file

    Parameters
    ----------
    dataframe: `pandas.DataFrame`
    outfile: path
    """
    dl2_params_lstcam = 'dl2/event/telescope/parameters/LST_LSTCam'
    write_dataframe(dataframe, outfile=outfile, table_path=dl2_params_lstcam)


def add_column_table(table, ColClass, col_label, values):
    """
    Add a column to an pytable Table

    Parameters
    ----------
    table: `tables.table.Table`
    ColClass: `tables.atom.MetaAtom`
    col_label: str
    values: list or `numpy.ndarray`

    Returns
    -------
    `tables.table.Table`
    """
    # Step 1: Adjust table description
    d = table.description._v_colobjects.copy()  # original description
    d[col_label] = ColClass()  # add column

    # Step 2: Create new temporary table:
    newtable = tables.Table(table._v_file.root, '_temp_table', d, filters=table.filters)  # new table
    table.attrs._f_copy(newtable)  # copy attributes
    # Copy table rows, also add new column values:
    for row, value in zip(table, values):
        newtable.append([tuple(list(row[:]) + [value])])
    newtable.flush()

    # Step 3: Move temporary table to original location:
    parent = table._v_parent  # original table location
    name = table._v_name  # original table name
    table.remove()  # remove original table
    newtable.move(parent, name)  # move temporary table to original location

    return newtable