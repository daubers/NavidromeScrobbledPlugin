"""Minimal fake `extism` module for testing plugin/__init__.py's pure business
logic under plain CPython, without the real extism-py/wasm runtime.

Never shipped or compiled - only used by tests/test_logic.py, which puts this
directory at the front of sys.path before importing the plugin module.
"""


def import_fn(namespace, name):
    def decorator(fn):
        return fn

    return decorator


def plugin_fn(fn):
    return fn


class LogLevel:
    Info = "info"
    Error = "error"


def log(level, message):
    pass


class Config:
    @staticmethod
    def get_str(key):
        return None


def input_json():
    return {}


def output_str(value):
    pass


class _Memory:
    def alloc(self, data):
        raise NotImplementedError("host memory is not available in tests")

    def find(self, offset):
        raise NotImplementedError("host memory is not available in tests")

    def string(self, mem):
        raise NotImplementedError("host memory is not available in tests")


memory = _Memory()
