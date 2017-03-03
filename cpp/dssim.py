#
# General-purpose library for distributed stream simulations
#

import sys
from dds import *
import pandas as pd
import numpy as np

def prepare_data():
	wcup = wcup_ds("/home/vsam/src/datasets/wc_day44")

	D = dataset()
	D.load(wcup)
	D.set_max_length(10000)
	D.set_time_window(3600)
	D.create()

def prepare_components(sids = None):
	components = []
	if sids is None:
		sids = list(CTX.metadata().stream_ids) # need to order them!
	else:
		sids = list(sids)
	sids.sort()
	for i in range(len(sids)):
		components.append(selfjoin_exact_method(sids[i]))
		components.append(selfjoin_agms_method(sids[i], 11, 1000))
		for j in range(i):
			components.append(twoway_join_exact_method(sids[j], sids[i]))
			components.append(twoway_join_agms_method(sids[j], sids[i], 11, 1000))

	r = progress_reporter(40)
	dss = data_source_statistics()
	components += [r,dss]
	return components


def execute(sids=None):
	prepare_data()
	components = prepare_components(sids)

	# prepare output
	wcout = CTX.open("wc_tseries.dat",open_mode.truncate)
	sout = output_pyfile(sys.stdout)

	CTX.timeseries.bind(wcout)
	print("timeseries=", CTX.timeseries.size())

	R = reporter()
	R.watch(network_comm_results)
	R.sample(CTX.timeseries, 1000)

	# run
	CTX.run()

	# cleanup
	CTX.close_result_files()


def execute_exp():

	wcup = wcup_ds("/home/vsam/src/datasets/wc_day44")

	D = dataset()
	D.load(wcup)
	D.hash_streams(1)
	D.set_max_length(10000)
	D.set_time_window(4*3600)
	D.create()

	# components
	proj = agms.projection(7, 500)
	C = [
		tods.network(proj, 0.1),
		gm2.network(0, proj, 0.1),
		selfjoin_exact_method(0),
		selfjoin_agms_method(0, proj)
	]

	R = reporter()

	# prepare output
	wcout = CTX.open("wc_tseries.dat",open_mode.truncate)
	print("timeseries=", CTX.timeseries.size())
	h5out = output_hdf5('testfile.h5')
	
	CTX.timeseries.bind(wcout)
	CTX.timeseries.bind(h5out)

	network_comm_results.bind(output_stdout)
	network_comm_results.bind(h5out)
	network_host_traffic.bind(h5out)
	network_interfaces.bind(h5out)

	R.watch(network_comm_results)
	R.watch(network_host_traffic)
	R.watch(network_interfaces)
	R.sample(CTX.timeseries, 1000)

	# run
	CTX.run()

	# cleanup
	CTX.close_result_files()
	print("Done")



def execute_generated():
	CTX.data_feed(uniform_data_source(5, 25, 1000, 1000))
	components = prepare_components()

	wcout = CTX.open("uni_tseries.dat",open_mode.truncate)
	sout = output_pyfile(sys.stdout)

	CTX.timeseries.bind(wcout)
	print("timeseries=", CTX.timeseries.size())

	repter = reporter(1000)

	# run
	CTX.run()

	# cleanup
	CTX.close_result_files()


def load_timeseries(fname):
	return pd.read_csv(fname)

def make_error_frame(df, singles=[], pairs=[], streams=set()):
	E = pd.DataFrame()
	stream_set = set(streams)
	for s in stream_set:
		for exc,est in singles:
			E['Err%d'%s] = relerr(df[exc%s], df[est%s])
		for s2 in stream_set:
			if s2>s:
				for exc,est in pairs:
					E['Err_%d_%d'%(s,s2)] = relerr(df[exc%(s,s2)], df[est%(s,s2)])
	return E


@np.vectorize
def relerr(xacc,xest): 
    if xacc==0.0:
        return 0.0
    else:
        return abs((xacc-xest)/xacc)


if __name__=='__main__':
	#execute()
	#execute_generated()
	execute_exp()
	pass

