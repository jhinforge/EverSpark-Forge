"""Service threads survive paused consoles and cancelled HTTP responses."""
import ctypes
import unittest
from http.server import BaseHTTPRequestHandler
from unittest.mock import Mock, patch
from Archon.Gate.CLI import archon, windows_console
from Archon.Gate.control_server import ControlHandler
from Archon.Portal.app import RequestHandler


class ConsoleReliabilityTests(unittest.TestCase):
    def test_quick_edit_preserves_other_console_flags(self):
        api = Mock()
        def read_mode(handle, pointer):
            ctypes.cast(pointer, ctypes.POINTER(windows_console.wintypes.DWORD))[0] = 0x0047
            return True
        api.GetConsoleMode.side_effect = read_mode
        with patch.object(windows_console.sys, 'platform', 'win32'):
            self.assertTrue(windows_console.disable_quick_edit(api))
        api.SetConsoleMode.assert_called_once_with(api.GetStdHandle.return_value, 0x0087)

    def test_redirected_input_skips_mode_change(self):
        api = Mock()
        api.GetConsoleMode.return_value = False
        with patch.object(windows_console.sys, 'platform', 'win32'):
            self.assertFalse(windows_console.disable_quick_edit(api))
        api.SetConsoleMode.assert_not_called()

    def test_configure_forwards_import_options(self):
        with patch('Archon.Vault.import_config.main', return_value=0) as configure:
            self.assertEqual(archon.main(['configure', '--from', 'inbox']), 0)
        configure.assert_called_once_with(['--from', 'inbox'])

    def test_cancelled_requests_close_without_a_second_response(self):
        for handler_class in (ControlHandler, RequestHandler):
            for error in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                with self.subTest(handler=handler_class, error=error):
                    handler = object.__new__(handler_class)
                    handler._log = Mock()
                    with patch.object(BaseHTTPRequestHandler, 'handle', side_effect=error()), patch.object(handler_class, 'send_error') as reply:
                        handler.handle()
                    self.assertTrue(handler.close_connection)
                    reply.assert_not_called()

    def test_unexpected_request_errors_are_not_suppressed(self):
        for handler_class in (ControlHandler, RequestHandler):
            with patch.object(BaseHTTPRequestHandler, 'handle', side_effect=RuntimeError('unexpected')):
                with self.assertRaises(RuntimeError):
                    object.__new__(handler_class).handle()
