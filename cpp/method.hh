#ifndef __METHOD_HH___
#define __METHOD_HH___

#include <vector> 
#include <map>
#include <deque>
#include <list>

#include "dds.hh"
#include "eca.hh"
#include "data_source.hh"
#include "output.hh"

namespace dds {


using fileset_t = std::vector<output_file*>;


/**
	The CTX context object's type
  */
struct context : basic_control
{

	/// Each simulation generates one time series table
	time_series timeseries;

	// managed files for results
	fileset_t result_files;

	output_file* open(FILE* f, bool owner = false);
	output_file* open(const string& path, open_mode mode);
	void close_result_files();


	/// Must be default-constructible!
	context() {}

	/// Start the simulation
	void run();


};


///  The global context
extern context CTX;

/// Used to add ECA rules
template <typename Action>
inline auto ON(Event evt, const Action& action)
{
	return CTX.add_rule(evt, new action_function<Action>(action));
}

template <typename Condition, typename Action>
inline auto ON(Event evt, const Condition& cond, const Action& action)
{
	return CTX.add_rule(evt, 
		new condition_action<Condition, Action>(cond, action));
}

/// Used to emit an event
inline void emit(Event evt)
{
	CTX.emit(evt);
}

/**
	Reactive objects manage a set of rules conveniently.

	Use the \c on() member to add ECA rules, that will be
	cancelled when the object is destroyed.

	\note this class (and its subclasses) are non-copyable
	and non-movable. 
  */
struct reactive
{
	std::vector<eca_rule> eca_rules;

	reactive() { }
	reactive(const reactive&) = delete;
	reactive& operator=(const reactive&) = delete;
	reactive(reactive&&) = delete;
	reactive& operator=(reactive&&) = delete;

	virtual ~reactive() {
		for(auto rule : eca_rules) CTX.cancel_rule(rule);	
	}

	template <typename Action>
	inline eca_rule on(Event evt, const Action& action) {
		eca_rule rule = ON(evt, action);
		eca_rules.push_back(rule);
		return rule;
	}

	template <typename Condition, typename Action>
	inline eca_rule on(Event evt, const Condition& cond, const Action& action) {
		eca_rule rule = ON(evt, cond, action);
		eca_rules.push_back(rule);
		return rule;
	}
};

struct reporter : reactive
{
	reporter(size_t n_times) {
		on(REPORT, every_n_times(n_times), [&]() { handle(); });
	}
	void handle() {
		CTX.timeseries.emit_row();
	}
};

struct progress_reporter : reactive, progress_bar
{

	progress_reporter(FILE* _stream=stdout, 
		size_t _marks = 40, 
		const string& _msg = "") 
	: progress_bar(_stream, _marks, _msg)
	{
		on(START_STREAM, [&](){ start(CTX.ds_meta.size()); });
		on(START_RECORD, [&](){ tick(); });
		on(END_STREAM, [&](){ finish(); });
	}
};


/**
	A protocol is a simulation of a query answering method.

	This is the base class.
  */
class protocol : public reactive
{
public:
	virtual const basic_query& query() const = 0;
	virtual double current_estimate() const = 0;
};




} //end namespace dds

#endif