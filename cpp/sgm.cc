
#include <algorithm>
#include <boost/range/adaptors.hpp>

#include "binc.hh"
#include "sgm.hh"

using namespace dds;
using namespace gm;
using namespace gm::sgm;


using binc::print;
using binc::elements_of;


/*
	Implements the traditional, Set-based Geometric Method and its variants
*/


/*********************************************
	node
*********************************************/

oneway node::reset(const safezone& newsz) 
{
	// reset the safezone object
	szone = newsz;

	// reset the drift vector
	U = 0.0;
	update_count = 0;
	zeta = szone(U);

	// reset round statistics
	round_local_updates = 0;
}


compressed_state_ref node::get_drift() 
{
	// getting the drift vector is done as getting the local statistic
	size_t upd = update_count;
	update_count = 0;
	return compressed_state_ref { U, upd };
}

void node::set_drift(compressed_state_ref newU) 
{
	U = newU.vec;
	// we do not change the update count update_count = newU.updates;
	zeta = szone(U);
	assert(zeta>0);
}


void node::update_stream() 
{
	assert(CTX.stream_record().hid == site_id());

	delta_vector delta = Q->delta_update(U, CTX.stream_record());
	if(delta.size()==0) return;

	update_count++;
	round_local_updates++;

	zeta = szone(delta, U);

	if(zeta <= 0)
		coord.local_violation(this);
}



void node::setup_connections()
{
	num_sites = coord.proc()->k;
}


/*********************************************
	coordinator
*********************************************/


// initialize a new round

void coordinator::start_round()
{

	for(auto n : net()->sites) {
		sz_sent ++;
		proxy[n].reset(safezone(safe_zone));
	}

	round_total_B = 0;
	num_rounds++;
	num_subrounds++;

	// this is zeroed here, but it is not zeroed in subsequent 
	// rebalances, only Ubal is zeroed !
	Ubal_updates = 0;
}	



// remote call on host violation

oneway coordinator::local_violation(sender<node_t> ctx)
{
	node_t* n = ctx.value;

	/* 
		In this function, we try to rebalance. If this fails, we
		restart the round.
	 */

	B.clear();
	Ubal = 0.0;

	if(k>1) {
		// attempt to rebalance		
		// get rebalancing set
		switch(cfg().rebalance_algorithm)
		{
			case rebalancing::none:
				rebalance_none(n);
				break;
			case rebalancing::random:
				rebalance_random(n);
				break;
			case rebalancing::random_limits:
				rebalance_random_limits(n);
				break;
			default:
				throw std::runtime_error("Unknown rebalancing algoritm");
		}
	} else {
		rebalance_none(nullptr);
	}
}


void coordinator::fetch_updates(node_t* node)
{
	compressed_state_ref cs = proxy[node].get_drift();
	Ubal += cs.vec;
	Ubal_updates += cs.updates;	
	total_updates += cs.updates;
}


void coordinator::rebalance_none(node_t* lvnode)
{
	Bcompl.clear();	
	for(auto n : node_ptr)	
		Bcompl.insert(n);
	finish_round();
}



void coordinator::rebalance_random(node_t* lvnode)
{
	Bcompl.clear();

	B.insert(lvnode);
	fetch_updates(lvnode);
	Ubal_admissible = false;
	assert(query->compute_zeta(Ubal) <= 0.0);

	// find a balancing set
	vector<node_t*> nodes;
	nodes.reserve(k);
	for(auto n : node_ptr) {
		if(B.find(n) == B.end())
			nodes.push_back(n);
	}
	assert(nodes.size()==k-1);

	// permute the order
	random_shuffle(nodes.begin(), nodes.end());
	assert(nodes.size()==k-1);
	assert(B.size()==1);
	assert(Bcompl.empty());

	double zbal = query->compute_zeta( Ubal/((double) B.size()) );
	for(auto n : nodes) {
		if(Ubal_admissible) {
			Bcompl.insert(n);
		} else {
			B.insert(n);
			fetch_updates(n);
			zbal = query->compute_zeta( Ubal/((double) B.size()) );
			Ubal_admissible =  (zbal>0.0) ? true : false;
		}
	}
	assert(B.size()+Bcompl.size() == k);

	// if it is a partial balancing set, rebalance, else finish round
	if(! Bcompl.empty()) {
		//print("  ->    GM Rebalancing ",B.size()," sites");
		assert(Ubal_admissible);
		assert(zbal > 0.0);
		assert(B.size()>1);
		rebalance();
	} else {
		//print("       GM Rebalancing failed, finishing round");
		finish_round();
	}
}

/*
  In order to reduce the cost of over-rebalancing, we impose 
  ad-hoc limits to 
  (a) the size of the rebalance set be up to ceil(k+2/2)
  k  max|B|
  2  2
  3  3
  4  3->  5  4
  6  4
  ...

  (b) \sum |B|  over a round to be <= k
  ... 
 */

void coordinator::rebalance_random_limits(node_t* lvnode)
{
	B.clear();
	Bcompl.clear();

	B.insert(lvnode);
	fetch_updates(lvnode);
	Ubal_admissible = false;
	assert(query->compute_zeta(Ubal) <= 0.0);

	// find a balancing set
	vector<node_t*> nodes;
	nodes.reserve(k);
	for(auto n : node_ptr) {
		if(B.find(n) == B.end())
			nodes.push_back(n);
	}
	assert(nodes.size()==k-1);

	// permute the order
	random_shuffle(nodes.begin(), nodes.end());
	assert(nodes.size()==k-1);
	assert(B.size()==1);
	assert(Bcompl.empty());

	double zbal = query->compute_zeta( Ubal/((double) B.size()) );
	//
	// The loop computes a rebalancing set B of minimum size, trying
	// in order each of the nodes in the random order selected.
	//
	for(auto n : nodes) {
		if(Ubal_admissible) {
			Bcompl.insert(n);
		} else {
			B.insert(n);
			fetch_updates(n);
			zbal = query->compute_zeta( Ubal/((double) B.size()) );
			Ubal_admissible =  (zbal>0.0) ? true : false;
		}
	}
	assert(B.size()+Bcompl.size() == k);

	// check conditions for finishing round
	bool fin = Bcompl.empty();

	// (a) check limit on |B|
	fin = fin ||  B.size() > (k+3)/2;

	// (b) check limit on  sum|B|
	fin = fin ||  (round_total_B + B.size()) > k;
	
	if(! fin) {
		//print("       GM Rebalancing ",B.size()," sites");
		assert(Ubal_admissible);
		assert(zbal > 0.0);
		assert(B.size()>1);
		rebalance();
	} else {
		//print("       GM Rebalancing failed, finishing round");
		finish_round();
	}
}



void coordinator::rebalance()
{
	Ubal /= B.size();

	assert(query->compute_zeta(Ubal) > 0);

	compressed_state_ref sbal { Ubal, Ubal_updates };

	for(auto n : B) {
		proxy[n].set_drift(sbal);
	}	

	round_total_B += B.size();
	
	assert(std::all_of(node_ptr.begin(), node_ptr.end(), [](auto n) { return n->zeta > 0; }));

	num_subrounds++; 
	total_rbl_size += B.size();
}



// initialize a new round

void coordinator::finish_round()
{
	// collect all data
	for(auto n : Bcompl) {
		fetch_updates(n);
	}
	Ubal /= (double)k;

#if 0
	trace_round(Ubal);
#endif

	// new round
	query->update_estimate(Ubal);
	start_round();
}

void coordinator::finish_rounds()
{
	rebalance_none(nullptr);
}

void coordinator::trace_round(const Vec& newE)
{
	Vec Enext = query->E + newE;
	double zeta_Enext = query->zeta(Enext);

	valarray<size_t> round_updates((size_t)0, k);

	for(size_t i=0; i<k; i++) 
	{
		auto ni = node_ptr[i];
		round_updates[i] += ni->round_local_updates;
	}

	// check the value of the next E wrt this safe zone
	double norm_dE = norm_L2(newE);

	print("GM Finish round : round updates=",round_updates.sum(),
		"zeta_E=",query->zeta_E, "zeta_E'=", zeta_Enext, zeta_Enext/query->zeta_E,
		"||dE||=", norm_dE, norm_dE/query->zeta_E, 
		//"minzeta_min=", minzeta_total, minzeta_total/(k*query->zeta_E),
		//"minzeta_min/zeta_E=",minzeta_min/query->zeta_E,
		" QEst=", query->Qest,
		" time=", (double)CTX.stream_count() / CTX.metadata().size() );

	// print elements
	print("                  : S= ",elements_of(round_updates));	
}


void coordinator::warmup()
{
	Vec dE(Q->state_vector_size());

	for(auto&& rec : CTX.warmup) 
		Q->update(dE, rec);

	query->update_estimate(dE/(double)k);
}



void coordinator::setup_connections()
{
	using boost::adaptors::map_values;
	proxy.add_sites(net()->sites);
	for(auto n : net()->sites) {
		node_index[n] = node_ptr.size();
		node_ptr.push_back(n);
	}
	k = node_ptr.size();
}



coordinator::coordinator(network_t* nw, continuous_query* _Q)
: 	process(nw), proxy(this), 
	Q(_Q), 
	query(Q->create_query_state()),
	k(0),
	Qest_series(nw->name()+".qest", "%.10g", [&]() { return query->Qest;} ),
	Ubal(0.0, Q->state_vector_size()),
	num_rounds(0), num_subrounds(0), sz_sent(0), total_rbl_size(0),
	total_updates(0)
{  
	safe_zone = query->safezone();
}


coordinator::~coordinator()
{
	delete safe_zone;
	delete query;
}

/*********************************************

	network

********************************************/


sgm::network::network(const string& _name, continuous_query* _Q)
: 	gm_network_t(_name, _Q)
{
	this->set_protocol_name("GM");
}

gm::p_component_type<network> sgm::sgm_comptype("SGM");

