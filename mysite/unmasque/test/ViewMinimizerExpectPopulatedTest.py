import pytest

from mysite.unmasque.src.core.view_minimizer import ViewMinimizer
from mysite.unmasque.src.pipeline.fragments.DisjunctionPipeLine import probe_expects_populated
from mysite.unmasque.src.util.error_handling import UnmasqueError


class _EmptyResultApp:
    """Executable stub: the query always returns zero data rows."""

    def doJob(self, query):
        return [[]]

    def isQ_result_no_full_nullfree_row(self, result):
        return True


class _RecordingLogger:
    def __init__(self):
        self.errors = []
        self.infos = []
        self.debugs = []

    def error(self, *args, **kwargs):
        self.errors.append(' '.join(str(arg) for arg in args))

    def info(self, *args, **kwargs):
        self.infos.append(' '.join(str(arg) for arg in args))

    def debug(self, *args, **kwargs):
        self.debugs.append(' '.join(str(arg) for arg in args))


def _minimizer(expect_populated):
    minimizer = ViewMinimizer.__new__(ViewMinimizer)
    minimizer.app = _EmptyResultApp()
    minimizer.logger = _RecordingLogger()
    minimizer.expect_populated = expect_populated
    return minimizer


def test_falsified_probe_does_not_raise_error_001():
    minimizer = _minimizer(expect_populated=False)

    result = minimizer.doActualJob('query')

    assert result is False
    assert minimizer.logger.errors == []
    assert any('No disjunct exists' in message for message in minimizer.logger.infos)


def test_normal_probe_still_raises_error_001_when_empty():
    minimizer = _minimizer(expect_populated=True)

    with pytest.raises(UnmasqueError) as exc_info:
        minimizer.doActualJob('query')

    assert exc_info.value.err_code == '001'
    assert any('not giving populated result' in message for message in minimizer.logger.errors)


def test_probe_expects_populated_only_when_every_where_is_true():
    assert probe_expects_populated(None) is True
    assert probe_expects_populated([]) is True
    assert probe_expects_populated([('customer', 'true'), ('orders', 'TRUE')]) is True
    assert probe_expects_populated(
        [('customer', "c_phone NOT LIKE '27-%'"), ('orders', 'true')]) is False
