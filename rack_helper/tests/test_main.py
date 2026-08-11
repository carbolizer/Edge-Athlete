import unittest
from unittest import mock

from edgeathlete_rack_helper import main
from edgeathlete_rack_helper.instance_lock import AlreadyRunningError, EXIT_CODE


class MainTests(unittest.TestCase):
    def test_second_process_has_stable_error_without_loading_runtime_ui(self):
        ownership = mock.Mock()
        ownership.acquire.side_effect = AlreadyRunningError("single_instance_active")
        with (
            mock.patch.object(main, "_show_single_instance_error") as show_error,
            self.assertLogs("edgeathlete_rack_helper", level="WARNING") as logs,
        ):
            result = main.main([], instance_lock=ownership)
        self.assertEqual(result, EXIT_CODE)
        show_error.assert_called_once_with()
        ownership.release.assert_not_called()
        self.assertNotIn("tkinter", main.__dict__)
        self.assertIn("startup_result=single_instance_active", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
