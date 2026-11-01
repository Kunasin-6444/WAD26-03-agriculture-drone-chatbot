"""Native stays loopback-only; Docker can explicitly bind its container interface."""
from unittest.mock import patch

import pytest

from scripts import playground


@pytest.mark.parametrize('args,host', [([], '127.0.0.1'), (['--host', '0.0.0.0'], '0.0.0.0')])
def test_bind_address_is_explicit_and_never_starts_a_line_app(args, host):
    from app.playground import app
    previous = app.state.pipeline
    try:
        with patch('sys.argv', ['playground', '--pipeline', 'support', '--port', '8082', *args]), \
             patch('importlib.util.find_spec', return_value=object()), \
             patch('uvicorn.run') as run:
            playground.main()
        run.assert_called_once_with(app, host=host, port=8082, workers=1)
        assert app.state.pipeline == 'support'
    finally:
        app.state.pipeline = previous


def test_json_mode_is_opt_in_and_only_available_for_support():
    from app.playground import app
    previous = app.state.pipeline
    try:
        with patch('sys.argv', ['playground', '--pipeline', 'support', '--support-json-mode']), \
             patch('importlib.util.find_spec', return_value=object()), patch('uvicorn.run'):
            playground.main()
        assert app.state.support_json_mode is True
        with patch('sys.argv', ['playground', '--pipeline', 'baseline', '--support-json-mode']), pytest.raises(SystemExit):
            playground.main()
    finally:
        app.state.pipeline = previous
        app.state.support_json_mode = False
