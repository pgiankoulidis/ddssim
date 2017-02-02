
#include "method.hh"
#include "mathlib.hh"

using namespace dds;

context dds::CTX;



output_file* context::open(FILE* f, bool owner) 
{
	output_file* of = new output_file(f, owner);
	result_files.push_back(of);
	return of;
}

output_file* context::open(const string& path, open_mode mode) 
{
	output_file* of = new output_file(path, mode);
	result_files.push_back(of);
	return of;
}

void context::close_result_files()
{
	for(auto f : result_files) {
		delete f;
	}
	result_files.clear();
}


void context::run()
{
	basic_control::run();
}



dataset::dataset() 
: src(0) 
{
	ON(INIT, [&](){ create(); });
}

dataset::~dataset()
{
	if(src) delete src;
}

void dataset::clear() 
{ 
	if(src) { 
		delete src; 
		src=0; 
	} 
}

void dataset::load(data_source* _src) 
{ 
	clear(); 
	src = _src; 
}
	
void dataset::set_max_length(size_t n) { _max_length = n; }
void dataset::hash_streams(stream_id h) { _streams = h; }
void dataset::hash_sources(source_id s) { _sources = s; }
void dataset::set_time_window(timestamp Tw) { _time_window = Tw; }

void dataset::create() {
	using boost::none;
	
	if(!src) {
		throw std::runtime_error("no source");
	}

	// apply filters
	if(_max_length != none)
		src = filtered_ds(src, max_length(_max_length.value()));
	if(_streams != none)
		src = filtered_ds(src, 
			modulo_attr(&dds_record::sid, _streams.value()));
	if(_sources != none)
		src = filtered_ds(src, 
			modulo_attr(&dds_record::hid, _sources.value()));

	// apply window
	if(_time_window != none)
		src = time_window(src, _time_window.value());

	CTX.data_feed(src);
	src=0;
}

