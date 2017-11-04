#ifndef __RESULTS_HH__
#define __RESULTS_HH__

#include "dsarch.hh"
#include "output.hh"
#include "method.hh"

namespace dds {


/**
	Statistics mixin for the metadata of the data source.
  */
struct dataset_results : private reactive
{
	column<string> dset_name        { "dset_name", 64, "%s" };
	column<timestamp> dset_window   { "dset_window", "%d" };
	column<size_t> dset_warmup      { "dset_warmup", "%zu" };
	column<size_t> dset_size        { "dset_size", "%zu" };	
	column<timestamp> dset_duration { "dset_duration", "%ld" };
	column<size_t> dset_streams		{ "dset_streams", "%zu"};
	column<size_t> dset_hosts		{ "dset_hosts", "%zu"};
	column<size_t> dset_bytes		{ "dset_bytes", "%zu"};

	dataset_results(result_table* table);
	void fill();
};


struct comm_results 
{
	column<size_t> total_msg 	{"total_msg", "%zu" };
	column<size_t> total_bytes 	{"total_bytes", "%zu" };
	column<double> traffic_pct  {"traffic_pct", "%.10g" };

	comm_results(result_table* table);
	void fill(basic_network* nw);
};



	
/**
	Statistics for each local stream.

	Generated by data_source_statistics
  */
struct local_stream_stats_t : result_table
{
	column<stream_id> 	sid			{this, "sid", "%hd" };
	column<source_id> 	hid 		{this, "hid", "%hd" };
	column<size_t>		stream_len 	{this, "stream_len", "%zu", 0 };
	local_stream_stats_t() : result_table("local_stream_stats") {}
};
extern local_stream_stats_t local_stream_stats;


/**
	Communication results for each network
  */
struct network_comm_results_t : result_table, comm_results
{
	column<string> netname   	{this, "netname", 64, "%s" };
	column<string> protocol     {this, "protocol", 64, "%s" };
	column<size_t> size         {this, "size", "%zu"};

	network_comm_results_t() 
		: result_table("network_comm_results"), comm_results(this) {}
	network_comm_results_t(const string& name) 
		: result_table(name), comm_results(this) {}
	void fill_columns(basic_network* nw);
};
extern network_comm_results_t network_comm_results;



struct gm_comm_results_t : result_table, dataset_results, comm_results
{

	column<string> name   	  	  {this, "name", 64, "%s" };
	column<string> protocol   	  {this, "protocol", 64, "%s" };
	column<double> max_error 	  {this, "max_error", "%.8g" };
	column<size_t> statevec_size  {this, "statevec_size", "%zu" };
	
	column<size_t> sites     	  {this, "sites", "%zu" };
	column<size_t> sid   	  	  {this, "sid", "%zu" };
	
	column<size_t> rounds 			{this, "rounds", "%zu" };
	column<size_t> subrounds		{this, "subrounds", "%zu" };
	column<size_t> sz_sent			{this, "sz_sent", "%zu"};
	column<size_t> total_rbl_size	{this, "total_rbl_size", "%zu"};

	column<size_t> bytes_get_drift	{this, "bytes_get_drift", "%zu"};

	gm_comm_results_t() 
		: gm_comm_results_t("gm_comm_results")
	{}
	gm_comm_results_t(const string& name) ;
	
	template <typename StarNetwork>
	void fill(StarNetwork* nw)
	{
		comm_results::fill(nw);
		name = nw->name();
		protocol = nw->rpc().name();
		max_error = nw->beta;
		statevec_size = nw->proj.size();
		sites = nw->sites.size();
		sid = nw->sid;

		auto hub = nw->hub;
		rounds = hub->num_rounds;
		subrounds = hub->num_subrounds;
		sz_sent = hub->sz_sent;
		total_rbl_size = hub->total_rbl_size;

		// number of bytes received by get_drift()
		bytes_get_drift = chan_frame(nw)
			.endp(typeid(typename StarNetwork::site_type),"get_drift")
			.endp_rsp()
			.bytes();
	}
};
extern gm_comm_results_t gm_comm_results;



struct network_host_traffic_t : result_table
{
	// each row corresponds to a channel
	column<string> netname		{this, "netname", 64, "%s"};
	column<string> protocol   	{this, "protocol", 64, "%s" };
	column<host_addr> src 		{this, "src", "%d"};
	column<host_addr> dst 		{this, "dst", "%d"};
	column<rpcc_t>  endp		{this, "endp", "%u"};
	column<size_t>  msgs		{this, "msgs", "%zu"};
	column<size_t>  bytes		{this, "bytes", "%zu"};
	network_host_traffic_t() : result_table("network_host_traffic") {}
	void output_results(basic_network* nw);	
};
extern network_host_traffic_t network_host_traffic;

struct network_interfaces_t : result_table
{
	// each row corresponds to a host interface
	column<string> netname		{this, "netname", 64, "%s"};
	column<string> protocol   	{this, "protocol", 64, "%s" };
	column<rpcc_t> rpcc 		{this, "rpcc", "%hu"};
	column<string> iface 		{this, "iface", 64, "%s"};
	column<string> method 		{this, "method", 64, "%s"};
	column<bool>   oneway		{this, "oneway", "%c"};
	network_interfaces_t() : result_table("network_interfaces") {}
	void output_results(basic_network* nw);	
};
extern network_interfaces_t network_interfaces;

} // end namespace dds

#endif
