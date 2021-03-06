
#
#  Toolset for data source preparation
#

import h5py
import numpy as np
from bisect import bisect_left, bisect_right
from collections import namedtuple

dds_record_type = np.dtype([
    ('sid','i2'),
    ('hid','i2'),
    ('key','i4'),
    ('upd','i4'),
    ('ts', 'i4')
    ],
    align=True)


class metadata:
    """
    A python implementation of the metadata object in the dds
    package.
    """
    def __init__(self, length=None, 
            ts=None, te=None, 
            kmin=None, kmax=None, 
            sids=None, hids=None):
        """
        Create a new metadata object with the given fields.
        """
        self.length = length
        self.ts = ts
        self.te = te
        self.kmin = kmin
        self.kmax = kmax
        self.sids = sids
        self.hids = hids

    def clone(self,*args,**kwargs):
        """
        Return a deep copy of this metadata object.
        """
        newsid = np.array(self.sids) if self.sids is not None else None
        newhid = np.array(self.hids) if self.hids is not None else None
        return metadata(self.length, self.ts, self.te, self.kmin, self.kmax, newsid, newhid)

    # a copy is always "deep"
    __copy__ = clone
    __deepcopy__ = clone

    def hash_streams(self, nstreams):
        """
        Apply a hash on the stream ids
        """
        self.sids = np.unique(self.sids % nstreams)
        return self

    def hash_sources(self, n):
        """
        Apply a hash on the source ids
        """
        self.hids = np.unique(self.hids % n)    
        return self

    def time_shift(self, Tw):
        """
        Shift the timestamp range by Tw
        """
        self.ts += Tw
        self.te += Tw
        return self

    def merge(self, other):
        """
        Merge with another metadata object.

        The result will be the metadata object of the merged stream.
        """
        self.length += other.length
        self.ts = min(self.ts, other.ts)
        self.te = max(self.te, other.te)
        self.kmin = min(self.kmin, other.kmin)
        self.kmax = max(self.kmax, other.kmax)
        self.sids = np.unique(np.concatenate((self.sids, other.sids)))
        self.hids = np.unique(np.concatenate((self.hids, other.hids)))
        return self

    Metadata = namedtuple('Metadata',
        ('length','ts_range','key_range','streams','sources'))

    @property
    def as_tuple(self):
        """
        Return the attributes of this metadata object as a namedtuple, nice for
        printing.
        """
        return metadata.Metadata(
            self.length, 
            (self.ts, self.te), 
            (self.kmin, self.kmax), 
            self.sids, 
            self.hids)

    def __eq__(self, other):
        try:
            return (self.length==other.length and 
                self.ts == other.ts and self.te==other.te and
                self.kmin == other.kmin and self.kmax == other.kmax and
                set(self.sids) == set(other.sids) and
                set(self.hids) == set(other.hids))
        except:
            return False
    def __ne__(self, other):
        return not self==other


def analyze(data):
    """
    Return a metadata object for the given data.

    `data` should be an array in dds_record format.
    """
    m = metadata()
    m.length = data.size
    m.ts = min(data['ts'])
    m.te = max(data['ts'])
    m.kmin = min(data['key'])
    m.kmax = max(data['key'])
    m.sids = np.unique(data['sid'])
    m.hids = np.unique(data['hid'])
    assert m
    return m


#
# Unfortunately, numpy does not have a merge method to complement
# its very nice sort method. However, sorting turns out to be really
# slow... Therefore, to speed up on the alternative
# of 'concatenate and sort', we implement a multi-merge.
#
def merge_data(*D):
    """
    Merge a number of data arrays.

    The input is a sequence of data arrays. The function returns the merging
    of all of them.
    """

    from bisect import bisect_left

    # Remove empty arrays 
    D = [d for d in D if d.size>0]
    N = len(D)
    if N==0: # empty input?
        return np.array([], dtype=dds_record_type)
    D = tuple(D)

    # reserve the result array
    total_size = sum(d.size for d in D)   
    Result = np.zeros(total_size, dtype=dds_record_type)

    # use the timestamp range to split the data
    Time0 = min(d[0]['ts'] for d in D)
    Time1 = max(d[-1]['ts'] for d in D)+1

    # initial split is all one big slab
    Sinit0, Sinit1 = tuple(0 for d in D), tuple(len(d) for d in D)

    # cache a list with the ts attributes, for speed
    DT = tuple(d['ts'] for d in D)

    pos = 0  # position to append the next slice to Results
    def recursive_merge(T0, T1, S0, S1):
        # Recursive function to split a merge into a sequence of
        # small merges. 
        # Invariant:  Every slice S0[d]:S1[d] for d in [0:N) contains 
        # only records with timestamps in the range [T0,T1)
        nonlocal pos, Result, DT, D, N

        # compute slice sizes
        sizes = [b-a for a,b in zip(S0, S1)]

        SZ = sum(sizes)
        if sizes.count(0)>=N-1:
            # only one non-empty slice, just append it to Result
            # this is important, since the merged timestamp ranges
            # may not overlap, so we should get some huge chunks
            # processed by this case, cutting the recursion early!
            for d in range(N):
                if sizes[d]:
                    Result[pos:pos+SZ] = D[d][S0[d]:S1[d]]
                    break
            pos += SZ

        elif T1-T0 <= 1:
            # we just append the ranges to Results
            q = pos
            for d in range(N):
                if sizes[d]:
                    Result[q:q+sizes[d]] = D[d][S0[d]:S1[d]]
                    q += sizes[d]
            pos += SZ

        else:
            # split the time range in half (it will be T1-T0 >= 2!)
            Tm = (T0+T1)//2
            split = tuple(bisect_left(d, Tm) for d in DT)

            # recurse
            recursive_merge(T0, Tm, S0, split)
            recursive_merge(Tm, T1, split, S1)

    recursive_merge(Time0, Time1, Sinit0, Sinit1)
    assert pos==total_size
    return Result


def is_data_sorted(data):
    t = data['ts']
    return all(t[1:]-t[:-1] >= 0)



class ddstream_array:
    """
    Distributed Data Stream data manipulator.

    An instance of this class can transform a dataset by applying various
    transformations.
    """
    def __init__(self, data, metadata=None):
        self.data = data

        if not is_data_sorted(data):
            from warnings import warn
            warn("The data passed to ddstream_array was not sorted, sorting performed")
            data.sort(order='ts', kind='mergesort')

        if metadata is None:
            self.metadata = analyze(data)
        else:
            self.metadata = metadata
        self.attrs = {}

    def clone(self, *args, **kwargs):
        """
        Return a deep copy of this dataset.
        """
        return ddstream_array(np.array(self.data), self.metadata.clone())
    __deepcopy__ = clone
    # let __copy__ be done by default

    def hash_streams(self, nstreams):
        """
        Transform the dataset by hashing the stream ids
        """
        self.data['sid'] %= nstreams
        self.metadata.hash_streams(nstreams)
        return self

    def hash_sources(self, n):
        """
        Transform the dataset by hashing the source ids
        """
        self.data['hid'] %= n
        self.metadata.hash_sources(n)
        return self

    def negate(self):
        """
        Negate every update count on each record
        """
        self.data['upd'] = -self.data['upd']
        return self

    def time_shift(self, Tw):
        """
        Add a constant to every timestamp
        """
        self.data['ts'] += Tw
        self.metadata.time_shift(Tw)
        return self

    def merge(self, other):
        """
        Merge another dataset into this dataset.
        """
        # self.data = np.concatenate((self.data, other.data))
        # self.data.sort(order='ts', kind='mergesort')
        self.data = merge_data(self.data, other.data)
        self.metadata.merge(other.metadata)
        return self

    def time_window(self, Tw):
        """
        Transform the dataset by applying a time window.

        In particular, the stream is constructed by adding, for
        each record r, a new record r' with its timestamp increased
        by Tw and its update count negated.
        """
        return self.merge(self.clone().time_shift(Tw).negate())


    @property
    def tstart(self):
        """
        The start time of the dataset
        """
        return self.data[0]['ts']

    @property
    def tend(self):
        """
        The end time of the dataset (timestamp of last record plus one)
        """
        return self.data[-1]['ts']+1

    @property
    def tlen(self):
        """
        The difference self.tend-self.tstart
        """
        return self.data[-1]['ts']-self.data[0]['ts']+1

    def time_index(self, t):
        """
        Return the index corresponding to the given timestamp.

        This function returns the smallest integer i>=0, such that all records with
        index less than i have timestamp less than t.

        Note that this index belongs to [0,len(self)], that is, it may be past-the-end.
        """
        ts = self.data['ts']
        return bisect_left(ts,t)


    def __len__(self):
        """
        Return the length of the dataset
        """
        return len(self.data)

    def __getitem__(self, slc):
        """
        Return a new dataset with the slice of the data defined. 

        The metadata of the new dataset is adjusted only with respect to
        the timestamp range, but the key range, stream ids and sources are
        kept the same, although some values may not appear in the data
        of the new dataset.
        """
        if not isinstance(slc,slice):
            slc = slice(slc,slc+1)
        newdata = np.array(self.data[slc])
        newmeta = self.metadata.clone()
        newmeta.length = newdata.size
        newmeta.ts = newdata[0]['ts']
        newmeta.te = newdata[-1]['ts']
        return ddstream_array(newdata, newmeta)


    def to_hdf(self, loc, name="ddstream", compression="gzip"):
        """
        Save this stream to an HDF5 dataset.

        `loc` must be either (a) a string denoting a path, or (b) an
        h5py.Group instance (with h5py.File being also legal).

        `name` should be a string.

        If a dataset (or other object) by this name already exists, it
        will be deleted first

        Format:
        The dataset is written as a chunked array. The metadata is added as
        attributes to this array.
        """

        if not isinstance(loc, h5py.Group):
            # treat it as a string
            loc = h5py.File(loc)
        if name in loc: del loc[name]

        ds = loc.create_dataset(name, data=self.data, compression=compression)
        ds.attrs.create("key_range", 
            np.array([self.metadata.kmin, self.metadata.kmax], dtype=np.int32))
        ds.attrs.create("ts_range", 
            np.array([self.metadata.ts, self.metadata.te], dtype=np.int32))
        ds.attrs.create("stream_ids", 
            np.array(self.metadata.sids, dtype=np.int16))
        ds.attrs.create("source_ids", 
            np.array(self.metadata.hids, dtype=np.int16))

        for aname,aval in self.attrs.items():
            if aname in ("key_range", "ts_range", "stream_ids", "source_ids"):
                from warnings import warn 
                warn("From ddstream_array.to_hdf: Ignoring user-defined attribute '"
                    +aname+"' with a value of "+str(aval))
                continue

            # try to support some standard stuff
            if isinstance(aval, (list,tuple)):
                aval = np.array(aval)

            # we may fail writing a user attribute, but we should not let this
            # stop us!!
            try:
                ds.attrs[aname] = aval
            except Exception as e:
                print("Failed to save attribute ",aname,"=",aval)

        ds.file.flush()  # make sure!
        return ds

    def to_ddstream_dataset(self, loc, name="ddstream", compression="gzip"):
        """
        Save this array to an HDF5 dataset and return a handle on the dataset.
        """

        # First save it, then create an object from the dataset.
        # This is a bit roundabout, but excercises all the code.
        # Eventually, I will merge the codes...
        self.to_hdf(loc, name, compression)
        return ddstream_dataset(loc, name)


    def __repr__(self):
        return "<%s of length %d>" %( self.__class__.__name__,self.metadata.length)






class ddstream_dataset:
    """
    Distributed Data Stream HDF5 dataset.

    An instance of this class can transform a dataset by applying various
    transformations, but the data remains as an HDF5 file on disk.

    The API is similar to ddstream_array, with one major difference: many
    methods will return a new dataset, instead of modifying this one.

    Furthermore, this object does not have a separate metadata object; the
    metadata attributes are available only as properties.
    """

    def __init__(self, loc, name="ddstream", data=None, overwrite=False, 
                                                            compression="gzip"):
        """
        Open or create a new ddstream dataset

        loc can be either a string, or an h5py.Group. It if is a stream,
        it is treated as a filename and a new h5py.File is opened with mode 'a'.

        name should be a string, with a default value of "ddstream". 

        data is the data array of the dataset, or None. If data is not None, 
        a new dataset is created, else an existing dataset is sought. If there is
        already an object with this name in the file, an error is raised, unless
        the overwrite option is True

        overwrite is a bool. If True, a new dataset will be allowed to overwrite
        an existing object by this name.
        """
        if isinstance(loc, str):
            # loc is a file path
            loc = h5py.File(loc)

        if data is None:
            # existing dataset should be found
            dset = loc[name]
            self.check_dataset(dset)
        else:
            # a new dataset should be created
            if data.dtype != dds_record_type or len(data.shape)!=1:
                raise ValueError("invalid data provided for new dataset")
            # but check for existing name
            if name in loc:
                if overwrite:
                    del loc[name]
                else:
                    raise RuntimeError("name of new dataset is already in use")
            dset = loc.create_dataset(name, data=data, compression=compression)
            self.decorate_dataset(dset)

        self.dset = dset
        loc.file.flush()


    @staticmethod
    def check_dataset(dset):
        """
        Check the format of a dataset object and raise exceptions if
        problems are found
        """
        if dset.dtype != dds_record_type:
            raise ValueError("dtype does not match a stream dataset:",dset.dtype)
        for attr in ('ts_range', 'key_range', 'stream_ids', 'source_ids'):
            if attr not in dset.attrs:
                raise NameError("missing compulsory attribute:",attr)

    @staticmethod
    def decorate_dataset(dset):
        """
        Add metadata attributes to an existing HDF5 dataset already prepared on disk
        """
        # create metadata attributes
        key = dset[:,'key']
        dset.attrs.create("key_range", 
            np.array([np.min(key), np.max(key)], dtype=np.int32))
        del key

        dset.attrs.create("ts_range", 
            np.array([dset[0,'ts'], dset[-1,'ts']], dtype=np.int32))

        dset.attrs.create("stream_ids", np.unique(dset[:,'sid']))
        dset.attrs.create("source_ids", np.unique(dset[:,'hid']))


    def clone(self, name=None, parent=None):
        """
        Make a new dataset which is a copy of this one.

        `name` is the name of the new dataset. If None, the name of this
        dataset is used

        `parent` is the location (Group or File) of the new dataset. 
        If None, the location of this dataset is used. Note that the location
        need not be in the same file as this dataset

        It is an error if both name and parent are None
        """
        if name is None and parent is None:
            raise ValueError("in clone, one of `parent` or `name` must be provided")
        if parent is None:
            parent = self.dset.parent
        if name is None:
            name = self.dset.name.split('/')[-1]
        dset = self.dset.file.copy(self.dset, parent, name=name)

    #
    # metadata as properties
    #
    @property
    def length(self):
        """
        Metadata property
        """
        return self.dset.len()
    @property
    def ts_range(self):
        """
        Metadata property
        """
        return self.dset.attrs['ts_range']
    @property
    def mintime(self):
        """
        Metadata property
        """
        return self.dset.attrs['ts_range'][0]
    @property
    def maxtime(self):
        """
        Metadata property
        """
        return self.dset.attrs['ts_range'][1]
    @property
    def key_range(self):
        """
        Metadata property
        """
        return self.dset.attrs['key_range']
    @property
    def minkey(self):
        """
        Metadata property
        """
        return self.dset.attrs['key_range'][0]
    @property
    def maxkey(self):
        """
        Metadata property
        """
        return self.dset.attrs['key_range'][1]
    @property
    def stream_ids(self):
        """
        Metadata property
        """
        return self.dset.attrs['stream_ids']
    @property
    def source_ids(self):
        """
        Metadata property
        """
        return self.dset.attrs['source_ids']

    def hash_streams(self, nstreams):
        """
        Transform the dataset by hashing the stream ids
        """
        nsid = np.unique( self.sids % nstreams )
        self.dset[:,'sid'] = self.dset[:,'sid'] % nstreams
        self.dset.attrs['stream_ids'] = nsid
        return self

    def hash_sources(self, n):
        """
        Transform the dataset by hashing the source ids
        """
        nhid = np.unique( self.hids % n )
        self.dset[:,'hid'] = self.dset[:,'hid'] % n
        self.dset.attrs['source_ids'] = nhid
        return self

    def negate(self):
        """
        Negate every update count on each record
        """
        self.dset[:,'upd'] = - self.dset[:,'upd'] 
        return self

    def time_shift(self, Tw):
        """
        Add a constant to every timestamp
        """
        self.dset[:,'ts'] = self.dset[:,'ts'] + Tw
        self.dset.attrs['ts_range'] = self.ts_range + Tw
        return self

    def merge(self, other):
        """
        Merge another dataset into this dataset.
        """
        raise NotImplementedError

    def time_window(self, Tw):
        """
        Transform the dataset by applying a time window.

        In particular, the stream is constructed by adding, for
        each record r, a new record r' with its timestamp increased
        by Tw and its update count negated.
        """
        raise NotImplementedError


    @property
    def tstart(self):
        """
        The start time of the dataset (from data, not from `ts_range`).
        Normally, this should be equal to self.mintime
        """
        return self.dset[0,'ts']

    @property
    def tend(self):
        """
        The end time of the dataset (timestamp of last record plus one).
        Normally, this should be equal to self.maxtime+1
        """
        return self.dset[-1,'ts']+1

    @property
    def tlen(self):
        """
        The difference self.tend-self.tstart
        """
        return self.dset[-1,'ts']-self.dset[0,'ts']+1


    def time_index(self, t):
        """
        Return the index corresponding to the given timestamp.

        This function returns the smallest integer i>=0, such that all records with
        index less than i have timestamp less than t.

        Note that this index belongs to [0,self.length], that is, it may be past-the-end.
        """
        ts = self.dset[:,'ts']
        return bisect_left(ts,t)


    def __len__(self):
        """
        Return the length of the dataset
        """
        return self.dset.len()

    def __getitem__(self, slc):
        """
        Return a slice of the underlying dataset
        """
        return self.dset[slc]


    def to_ddstream_array(self):
        """
        A convenience method to build a ddstream_array.
        """
        newarr = ddstream_array(self[:])
        # add all the attributes of this dataset, except the standard ones!
        for a in self.dset.attrs:
            if a not in ('ts_range', 'key_range', 'stream_ids', 'source_ids'):
                newarr.attrs[a] = self.dset.attrs[a]

        # done
        return newarr



    def get_metadata(self):
        """
        Make a metadata object out of the attributes of this dataset.
        """
        length = self.dset.len()
        kmin, kmax = self.key_range
        ts, te = self.ts_range
        sids = self.stream_ids
        hids = self.source_ids
        return metadata(length=length, kmin=kmin, kmax=kmax, ts=ts, te=te, 
            sids=sids, hids=hids)

    def __repr__(self):
        return "<%s(%s) of length %d>" %( self.__class__.__name__,self.dset.name,self.dset.len())




def from_hdf(loc, name="ddstream"):
    if isinstance(loc, str):
        # loc is a file path
        loc = h5py.File(loc)

    if name is None:
        # assume loc is a h5py.Dataset
        dset = loc
    else:
        # assume loc is a h5py.Group
        dset = loc[name]

    # get the data
    data = dset[:]
    if data.dtype != dds_record_type or len(data.shape)!=1:
        raise ValueError("the object read is not of the right dtype or shape")
    # get the metadata
    length = data.shape[0]
    ts, te = dset.attrs['ts_range']
    kmin, kmax = dset.attrs['key_range']
    sids = dset.attrs['stream_ids']
    hids = dset.attrs['source_ids']
    m = metadata(length=length, ts=ts, te=te, kmin=kmin, kmax=kmax, sids=sids, hids=hids)

    dssa = ddstream_array(data, m)

    # add user attributes

    ignored_names = {
        # my own metadata
        'ts_range','key_range','stream_ids','source_ids',
        # tables names
        'CLASS','VERSION','TITLE','NROWS',
        'FIELD_0_NAME','FIELD_1_NAME','FIELD_2_NAME','FIELD_3_NAME','FIELD_4_NAME',
        'FIELD_0_FILL','FIELD_1_FILL','FIELD_2_FILL','FIELD_3_FILL','FIELD_4_FILL'
    }

    for aname, aval in dset.attrs.items():
        if aname in ingored_names:
            continue
        dssa.attrs[aname] = aval

    return dssa



#########################################
#
#  Big data manipulation
#
#########################################


class _dset_seq_scan:
    """
    Helper class for sequential scanning of large datasets
    """
    def __init__(self, dset, buffer_size= 1<<16):
        self.buffer_size = buffer_size      # the size to read each time
        self.dset = dset                    # the dataset to scan
        self.read_pos = 0                   # the next read position

        self.fill_buffer()

    def fill_buffer(self):
        """
        Read the next buffer from the dataset
        """
        read_size = min(len(self.dset)-self.read_pos, self.buffer_size)
        if read_size==0:
            self.buffer = None
        else:
            self.buffer = self.dset[self.read_pos: self.read_pos+read_size]
            self.read_pos += read_size
        return read_size


class _dset_seq_merge_scan(_dset_seq_scan):
    """
    Helper class for scanning sequentially for merging (timestamp-wise)
    """

    def __init__(self, dset, Tw, buffer_size= 1<<16):
        self.Tw = Tw
        super().__init__(dset, buffer_size)

    def fill_buffer(self):
        """
        Fill the buffer and prepare:
        - negate and time-shift if Tw is defined
        - add timestamp index for fast location of netx timestamp block
        """
        super().fill_buffer()
        if self.buffer is not None:
            self.pos = 0
            if self.Tw is not None:
                self.buffer['upd'] = -self.buffer['upd']
                self.buffer['ts'] = self.buffer['ts']+self.Tw
            self.buffer_ts = self.buffer['ts']
            self.ts = self.buffer_ts[0]


    def __lt__(self, other):
        """
        Compare scanners on the scan head's timestamp. This allows to put
        a bunch of scanners in a heapq list
        """
        return self.ts < other.ts

    def move_block(self, app):
        """
        Write one block of records with minimum timestamp
        """

        # find block of equal timestamps
        numelem = bisect_right(self.buffer_ts, self.buffer_ts[self.pos], self.pos)-self.pos
        # write to output
        app.write(self.buffer, self.pos, numelem)
        # update position
        self.pos += numelem
        if self.pos == self.buffer.size:
            self.fill_buffer()
        else:
            self.ts = self.buffer_ts[self.pos]
        return numelem


class _dset_seq_output:
    """
    Helper class to pre-allocate and fill sequentially a dataset
    """
    def __init__(self, loc, name, total_size, compression):
        """
        Create an empty dataset of the given `total_size` and
        prepare to fill it sequentially
        """
        self.dset = loc.create_dataset(name, shape=(total_size,), dtype=dds_record_type,
                 compression=compression)
        self.curpos = 0

        self.buffer_size = 1<<22
        self.buffer = np.empty(self.buffer_size, dtype=dds_record_type)
        self.pos = 0

    def write(self, buf, pos, nelem):
        while nelem:
            nw = min(self.buffer_size-self.pos, nelem)
            self.buffer[self.pos:self.pos+nw] = buf[pos : pos+nw]
            nelem -= nw
            pos += nw
            self.pos +=nw
            if self.pos == self.buffer.size:
                self.flush()

    def flush(self):
        self.dset[self.curpos : self.curpos+self.pos] = self.buffer[:self.pos]
        self.curpos += self.pos
        self.pos = 0




def cascade_merge(loc, name, dsets, Tw=None, compression="gzip"):
    """
    Create a dataset by merging a number of datasets, possibly applying a time window.

    `loc` is an h5py.Group or a path (string)

    `name`  is the name of the new dataset

    dsets is a sequence of ddstream_dataset objects

    Tw is the size of the interval of the time window. It is assumed that
        Tw is less than the duration of the first dataset, although this
        is not checked

    A new dataset is created at location, with the given name
    """

    # Check the arguments

    import logging
    logger = logging.getLogger("dsrctool.cascade_merge")

    if isinstance(loc,str):
        logger.info("Using file '%s'",loc)
        loc = h5py.File(loc)

    logger.info("Merging into dataset '%s'",name)
    for d in dsets:
        logger.info("--> %s",d.dset.name)

    # create the list of scans
    scanners = [_dset_seq_merge_scan(d,None) for d in dsets]

    # add window scanners for deletions
    if Tw is not None:
        scanners += [_dset_seq_merge_scan(d, Tw) for d in dsets]

    # compute the total merged size    
    total_size = sum(s.dset.length for s in scanners)

    # allocate the output
    out_dset = _dset_seq_output(loc, name, total_size, compression=compression)

    from heapq import heapify, heappush, heappop, heapreplace

    heapify(scanners)

    actual_size = 0
    THRES = 1<<20
    next_report = THRES
    while scanners:
        actual_size += scanners[0].move_block(out_dset)
        if actual_size>=next_report:
            logger.info("Merged %d of %d records (%5.1f %%)", 
                actual_size,total_size, 100.*actual_size/total_size)
            next_report += THRES
        if scanners[0].buffer is not None:
            heapreplace(scanners, scanners[0])
        else:
            heappop(scanners)
    logger.info("Merged %d of %d records", actual_size,total_size)

    out_dset.flush()
    assert actual_size==total_size

    out_dset.dset.file.flush()

    logger.info("Decorating new dataset %s", out_dset.dset)
    ddstream_dataset.decorate_dataset(out_dset.dset)


    return ddstream_dataset(loc, name)





############################################
# 
# Native data sources
#
############################################

wcup_native_type = np.dtype([
    ('timestamp','>u4'),
    ('clientID','>u4'),
    ('objectID','>u4'),
    ('size','>u4'),
    ('method','u1'),
    ('status','u1'),
    ('type','u1'),
    ('server','u1')
    ])

def read_wcup_native(fname):
    """ 
    Read a file of native WordCup data and return an array. 
    """
    return np.fromfile(fname, wcup_native_type, -1, '')

def from_wcup(data, sid_field='type', key_field='clientID'):
    """
    Given an array of native WorldCup data, return an array in
    dds_record format.

    The `sid_field` denotes the name of the field to be used for stream_id.
    Good values are 'type' (the default), 'method' and 'status'

    The key_field denotes the `dds_record` key field. Good values
    are 'clientID' (the default) and 'objectID'.

    `data` can be either an np.array (as created by `read_wcup_native()`) or
    a string denoting a path to a file.
    """

    filename = None
    if not isinstance(data, np.ndarray):
        assert isinstance(data, str)
        filename = data
        data = read_wcup_native(filename)

    dset = np.zeros( data.size, dtype=dds_record_type)
    dset['sid'] = data[sid_field]
    dset['hid'] = data['server']
    dset['ts'] = data['timestamp']
    dset['key'] = data[key_field]
    dset['upd'] = 1
    dsa = ddstream_array(dset)

    # add some annotations
    dsa.attrs["origin"] = filename if filename is not None else "wcup"
    dsa.attrs["sid_field"] = sid_field
    dsa.attrs["key_field"] = key_field
    return dsa


def from_cdad():
    import pandas as pd
    from datetime import datetime

    def date_parser(day, mom):
        if not isinstance(day,str):
            raise ValueError

        Y,M,D = map(int, day.split('-'))
        h,m,s = map(int, mom.split(':'))

        return int(datetime(2000+Y,M,D,h,m,s).timestamp())

    d = pd.read_table('/home/vsam/src/datasets/wifi_crawdad_sorted',
        header=None,
        engine='c',
        index_col=False,
        names=[
        'siteString',
        'day',
        'moment',
        'parent',
        'aid',
        'state',
        'shortRet',
        'longRet',
        'strength',
        'quality',
        'mac',
        'classId',
        'srcPkts',
        'srcOct',
        'srcErrPkts',
        'srcErrOct',
        'dstPkts',
        'dstOct',
        'dstErrPkts',
        'dstErrOct',
        'dstMaxRetryErr',
        'ip'
        ],
        dayfirst=False,
        date_parser = date_parser,
        infer_datetime_format=True,
        parse_dates={'timestamp': [1,2]}
        #,nrows=10000
        ).sort_values(by='timestamp')

    arr = np.empty(len(d), dtype=dds_record_type)


    unique_parents = set(d['parent'])
    i = 0
    pmap = {}
    for s in unique_parents:
        pmap[s] = i
        i+=1

    arr['hid'] = np.array(list(map(lambda x: pmap[x] ,  d['parent'] )), dtype=np.int32 )
    arr['sid'] = d['aid'] % 2
    arr['key'] = d['longRet']
    arr['upd'] = 1
    arr['ts'] = d['timestamp']
    
    return ddstream_array(arr)


