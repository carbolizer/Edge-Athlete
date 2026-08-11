import unittest

from edgeathlete_rack_helper.protocol import ProtocolArgumentError, parse_arguments


class ProtocolTests(unittest.TestCase):
    def test_manual_and_exact_launch_are_the_only_accepts(self):
        self.assertEqual(parse_arguments([]), "manual")
        self.assertEqual(parse_arguments(["edgeathlete-rack:launch"]), "launch")

    def test_rejects_argument_count_and_protocol_fuzz(self):
        rejected = [
            ["edgeathlete-rack:launch", "extra"],
            ["EDGEATHLETE-RACK:launch"],
            ["edgeathlete-rack:launch "],
            [" edgeathlete-rack:launch"],
            ["edgeathlete-rack:%6caunch"],
            ["edgeathlete-rack://launch"],
            ["edgeathlete-rack:launch/path"],
            ["edgeathlete-rack:launch?x=1"],
            ["edgeathlete-rack:launch#x"],
            ["edgeathlete-rack:launch\0"],
            ["edgeathlete-rack:launch\n"],
            ["edgeathlete-rack:la6nch"],
            ["edgeathlete-rack:launch\ud800"],
            ["x" * 4096],
        ]
        for arguments in rejected:
            with self.subTest(arguments=repr(arguments)):
                with self.assertRaises(ProtocolArgumentError):
                    parse_arguments(arguments)


if __name__ == "__main__":
    unittest.main()
