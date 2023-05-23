# #!/usr/bin/env python3
#
# from typing import TYPE_CHECKING
#
# from ddtrace.appsec.iast import oce
# from ddtrace.appsec.iast._taint_dict import get_taint_dict
from ddtrace.appsec.iast._taint_tracking._native import ops  # noqa: F401

setup = ops.setup
new_pyobject_id = ops.new_pyobject_id

__all__ = ["new_pyobject_id", "setup"]
#
#
#
# if TYPE_CHECKING:
#     from typing import Any
#     from typing import Dict
#     from typing import List
#     from typing import Tuple
#     from typing import Union
#
#     from ddtrace.appsec.iast._source import _Source
#
#
# def add_taint_pyobject(pyobject, op1, op2):  # type: (Any, Any, Any) -> Any
#     if not (is_pyobject_tainted(op1) or is_pyobject_tainted(op2)):
#         return pyobject
#
#     pyobject = new_pyobject_id(pyobject, len(pyobject))
#     taint_dict = get_taint_dict()
#     new_ranges = []
#     if is_pyobject_tainted(op1):
#         new_ranges = list(taint_dict[id(op1)])
#     if is_pyobject_tainted(op2):
#         offset = len(op1)
#         for source, start, size in taint_dict[id(op2)]:
#             new_ranges.append((source, start + offset, size))
#
#     taint_dict[id(pyobject)] = tuple(new_ranges)
#     return pyobject
#
#
# def taint_pyobject(pyobject, source):  # type: (Any, _Source) -> Any
#     # Request is not analyzed
#     if not oce.request_has_quota:
#         return pyobject
#
#     # Pyobject must be Text with len > 1
#     if not pyobject or not isinstance(pyobject, (str, bytes, bytearray)):
#         return pyobject
#
#     if source is None:
#         return pyobject
#
#     len_pyobject = len(pyobject)
#     pyobject = new_pyobject_id(pyobject, len_pyobject)
#     taint_dict = get_taint_dict()
#     taint_dict[id(pyobject)] = ((source, 0, len_pyobject),)
#     return pyobject
#
#
# def is_pyobject_tainted(pyobject):  # type: (Any) -> bool
#     return id(pyobject) in get_taint_dict()
#
#
# def set_tainted_ranges(pyobject, ranges):  # type: (Any, tuple) -> None
#     taint_dict = get_taint_dict()
#     assert pyobject not in taint_dict
#     taint_dict[id(pyobject)] = ranges
#
#
# def get_tainted_ranges(pyobject):  # type: (Any) -> tuple
#     return get_taint_dict().get(id(pyobject), tuple())
#
#
# def taint_ranges_as_evidence_info(pyobject):  # type: (Any) -> Tuple[List[Dict[str, Union[Any, int]]], list[_Source]]
#     value_parts = []
#     sources = []
#     current_pos = 0
#     tainted_ranges = get_tainted_ranges(pyobject)
#     if not len(tainted_ranges):
#         return ([{"value": pyobject}], [])
#
#     for _range in tainted_ranges:
#         _source, _pos, _length = _range
#         if _pos > current_pos:
#             value_parts.append({"value": pyobject[current_pos:_pos]})
#
#         if _source not in sources:
#             sources.append(_source)
#
#         value_parts.append({"value": pyobject[_pos : _pos + _length], "source": sources.index(_source)})
#         current_pos = _pos + _length
#
#     if current_pos < len(pyobject):
#         value_parts.append({"value": pyobject[current_pos:]})
#
#     return value_parts, sources
