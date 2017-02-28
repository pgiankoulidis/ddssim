
#include <iostream>

#include "method.hh"
#include "tods.hh"
#include "results.hh"

using std::cout;
using std::endl;
using namespace dds;
using namespace dds::tods;


/************************************
 *
 *  TODS method
 *
 ************************************/

tods::network::network(const projection& _proj, double _theta, 
	const set<stream_id>& _streams)
: 	star_network<network, coordinator, node>(CTX.metadata().source_ids()),
	streams(_streams), 
	proj(_proj), theta(_theta)
{

}

tods::network::network(const projection& _proj, double _theta)
: network(_proj, _theta, CTX.metadata().stream_ids())
{
	k = CTX.metadata().source_ids().size();

	setup();

	// callback to process new record
	on(START_RECORD, [&](){ process_record(); });
	on(RESULTS, [&](){ output_results(); });
}


tods::network::~network()
{
}


void tods::network::process_record()
{
	const dds_record& rec = CTX.stream_record();
	sites[rec.hid]->update(rec.sid, rec.key, rec.sop);
}

double tods::network::maximum_error() const
{
	double eps = proj.epsilon();
	return eps + pow(1+eps,2.0)*(2.* theta + theta*theta);
}

void tods::network::output_results()
{
	comm_results.netname = "TODS";
	comm_results.max_error = maximum_error();
	comm_results.sites = k;
	comm_results.streams = CTX.metadata().stream_ids().size();
	comm_results.local_viol = 0;
	this->comm_results_fill_in();
	comm_results.emit_row();
}

/************************************
 *
 *  TODS coordinator
 *
 ************************************/

coordinator::coordinator(network* m)
: process(m)
{
	for(stream_id sid : m->streams)
		stream_state[sid] = new coord_stream_state(m->proj);
}


coordinator::~coordinator()
{
	for(auto i : stream_state)
		delete i.second;
}

oneway coordinator::update(source_id hid, stream_id sid, 
	const node_stream_state& nss)
{
	stream_state[sid]->Etot += nss.dE;
}


/************************************
 *
 *  TODS node
 *
 ************************************/


node::node(network* m, source_id hid)
: local_site(m, hid), coord(this, m->hub)
{
	for(stream_id sid : m->streams)
		stream_state[sid] = new node_stream_state(m->proj, m->theta, m->k);
}

void node::setup_connections()
{
	coord <<= ( ((network*)_net)->hub );
}

node::~node()
{
	for(auto i : stream_state)
		delete i.second;	
}


void node::update(stream_id sid, key_type key, stream_op op)
{
	// skip the record!
	if(net()->streams.find(sid)==net()->streams.end()) return;

	// get the state
	auto nss = stream_state[sid];
	// add update
	nss->update(key, (op==stream_op::INSERT)? 1.0 : -1.0);
	// check local condition
	if(! nss->local_condition()) {
		coord.update(site_id(), sid, *nss);
		nss->flush();
	}
}

node_stream_state::node_stream_state(projection proj, double theta, size_t k) 
: E(proj), dE(proj), delta_updates(0), 
	norm_X_2(0.0), norm_dE_2(0.0),
	theta_2_over_k(theta*theta/k)
{ }


void node_stream_state::update(key_type key, double freq) 
{
	// 1. Update the current state
	dE.update(key, freq);
	
	// 2. Update  ||dE||^2 incrementally
	dot_inc(norm_dE_2, dE.delta);
	
	// 3. Update ||dE+E||^2 incrementally
	//
	//  In the following, X = E + dE  
	//
	delta_vector DX = dE.delta;
	DX += E;
	dot_inc(norm_X_2, DX);

	// 4. Record the update
	delta_updates++;
}

/// check local condition
bool node_stream_state::local_condition() const
{
	return norm_dE_2 < theta_2_over_k * norm_X_2;
}

/// flush dE to E
void node_stream_state::flush() 
{
	// 1. Update E
	E += dE;
	// the line below is not mathematically necessary, but may be good for accuracy
	norm_X_2 = dot(E);

	// 2. Update dE
	(sketch&)dE = 0.0;  // the cast is necessary, since isketch does not have = op
	norm_dE_2 = 0.0;

	// 3. Reset the update counter
	delta_updates = 0;
}

size_t node_stream_state::byte_size() const
{
	compressed_sketch sk { dE, delta_updates };
	return sk.byte_size();
}

