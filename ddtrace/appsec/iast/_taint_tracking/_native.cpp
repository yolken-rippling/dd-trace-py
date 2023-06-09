#include <memory>
#include <pybind11/pybind11.h>

#include "TaintTracking/Source.h"
#include "TaintTracking/TaintedObject.h"
#include "TaintTracking/_taint_tracking.h"

#define PY_MODULE_NAME_ASPECTS                                                                                         \
    PY_MODULE_NAME "."                                                                                                 \
                   "aspects"

using namespace pybind11::literals;
namespace py = pybind11;


PYBIND11_MODULE(_native, m)
{
    pyexport_m_taint_tracking(m);


    // Note: the order of these definitions matter. For example,
    // stacktrace_element definitions must be before the ones of the
    // classes inheriting from it.
}
