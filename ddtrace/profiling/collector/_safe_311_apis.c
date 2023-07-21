#include "Python.h"
#include "frameobject.h"
//#include "pycore_code.h"
#include "pycore_frame.h"
#include "pycore_object.h"

#include <stdbool.h>


#include <stdio.h>
#define LOG_COUNT(i, ptr, str, ret) do { \
    if (!(ptr)) { \
        if ((i) == 100) { \
            printf("%s: Logging will stop.\n", (str)); \
            fflush(stdout); \
        } else if ((i) > 100) { \
            return (ret); \
        } else { \
            printf("%s: %lu\n", (str), (i)); \
            fflush(stdout); \
            ++(i); \
            return (ret); \
        } \
    } \
} while(0)
/********************************** GetBack ***********************************/
static inline bool
Safe_IsIncomplete(_PyInterpreterFrame *frame) {
  return frame->owner != FRAME_OWNED_BY_GENERATOR && frame->prev_instr < _PyCode_CODE(frame->f_code) + frame->f_code->_co_firsttraceable;
}

PyFrameObject*
Safe_New_NoTrack(PyCodeObject *code)
{
  static size_t badcode_count = 0;
  static size_t badgc_count = 0;
  LOG_COUNT(badcode_count, code, "[B3]C", NULL);

  int slots = code->co_nlocalsplus + code->co_stacksize;
  PyFrameObject *f = PyObject_GC_NewVar(PyFrameObject, &PyFrame_Type, slots);
  LOG_COUNT(badgc_count, f, "[B3]GC", NULL);

  f->f_back = NULL;
  f->f_trace = NULL;
  f->f_trace_lines = 1;
  f->f_trace_opcodes = 0;
  f->f_fast_as_locals = 0;
  f->f_lineno = 0;
  return f;
}

PyFrameObject *
Safe_MakeAndSetFrameObject(_PyInterpreterFrame *frame)
{
  static size_t badframe_count = 0;
  static size_t badgc_count = 0;
  static size_t badframeobj_count = 0;
  static size_t badframefcode_count = 0;
  static size_t badfframedata_count = 0;
  PyObject *error_type, *error_value, *error_traceback;
  PyErr_Fetch(&error_type, &error_value, &error_traceback);

  LOG_COUNT(badframe_count, frame, "[B2]F", NULL);
  LOG_COUNT(badframefcode_count, frame->f_code, "[B2]C", NULL);

  PyFrameObject *f = Safe_New_NoTrack(frame->f_code);
  if (f == NULL) {
    Py_XDECREF(error_type);
    Py_XDECREF(error_value);
    Py_XDECREF(error_traceback);
    LOG_COUNT(badgc_count, f, "[B2]G", NULL);
    return NULL;
  }

  LOG_COUNT(badframeobj_count, frame->frame_obj, "[B2]O", NULL);

  PyErr_Restore(error_type, error_value, error_traceback);
  if (frame->frame_obj == NULL) {
    LOG_COUNT(badfframedata_count, f->_f_frame_data, "[B2]FD", NULL);

    f->f_frame = (_PyInterpreterFrame *)f->_f_frame_data;
    f->f_frame->owner = FRAME_CLEARED;
    f->f_frame->frame_obj = f;
    Py_DECREF(f);
    return frame->frame_obj;
  }

  f->f_frame = frame;
  frame->frame_obj = f;
  return f;
}


static inline PyFrameObject *
Safe_GetFrameObject(_PyInterpreterFrame *frame)
{
  static size_t badframe_count = 0;
  LOG_COUNT(badframe_count, frame, "[B1]F", NULL);
  PyFrameObject *res = frame->frame_obj;
  if (res != NULL) {
    return res;
  }
  return Safe_MakeAndSetFrameObject(frame);
}

PyFrameObject *
Safe_GetBack(PyFrameObject *frame)
{
  static size_t badframe_count = 0;
  static size_t incframe_count = 0;
  static size_t badframe_prev_count = 0;
  LOG_COUNT(badframe_count, frame, "[B0]F", NULL);

  LOG_COUNT(incframe_count, _PyFrame_IsIncomplete(frame->f_frame), "[B0]I", NULL);

  PyFrameObject *back = frame->f_back;
  if (back == NULL) {
      LOG_COUNT(badframe_prev_count, frame->f_frame->previous, "[B0]P", NULL);
      _PyInterpreterFrame *prev = frame->f_frame->previous;
      while (prev && Safe_IsIncomplete(prev)) {
        prev = prev->previous;
      }
      if (prev) {
        back = Safe_GetFrameObject(prev);
      }
  }
  Py_XINCREF(back);
  return (PyFrameObject*)back;
}

PyObject *
get_back(PyObject *self, PyObject *frame) {
  (void)self;
  PyObject *back = (PyObject *)Safe_GetBack((PyFrameObject *)frame);
  if (!back)
    Py_RETURN_NONE;
  return back;
}


/********************************** GetCode ***********************************/
PyCodeObject *
Safe_GetCode(PyFrameObject *frame)
{
  static size_t badframe_count = 0;
  static size_t badfframe_count = 0;
  static size_t badfcode_count = 0;
  LOG_COUNT(badframe_count, frame, "[C0]F", NULL);
  LOG_COUNT(badfframe_count, frame->f_frame, "[C0]FF", NULL);
  LOG_COUNT(badfcode_count, frame->f_frame->f_code, "[C0]FC", NULL);
  PyCodeObject *code = frame->f_frame->f_code;
  return (PyCodeObject*)Py_NewRef(code);
}

PyObject *
get_code(PyObject *self, PyObject *frame) {
  (void)self;
  PyObject *code = (PyObject *)Safe_GetCode((PyFrameObject *)frame);
  if (!code)
    Py_RETURN_NONE;
  return code;
}


/******************************** Registration ********************************/
static PyMethodDef methods[] = {
  { "get_back", (PyCFunction)get_back, METH_O, "gets the f_back"},
  { "get_code", (PyCFunction)get_code, METH_O, "gets the f_code"},
  {NULL, NULL, 0, NULL}, // Sentinel
};

static struct PyModuleDef module_def = {
  PyModuleDef_HEAD_INIT,
  "_safe_311_apis",
  "Implement internal python 3.11 APIs to avoid segfaults",
  0,
  methods,
};

PyMODINIT_FUNC
PyInit__safe_311_apis(void)
{
  return PyModule_Create(&module_def);
}
