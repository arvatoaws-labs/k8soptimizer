import argparse
import logging
import sys

from k8soptimizer import __version__
from promhelper import *

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"


class Cli:
    def __init__(self, args):
        self._args = self.parse_args(args)
        self.logger = logging.getLogger(__name__)
        self.setup_logging(self._args.loglevel)
        self.logger.info("init cli")

    def run(self):
        logging.info("run cli")
        #prometheus = PrometheusQuery()
        #prometheus.query("hallo")

    # ---- CLI ----
    # The functions defined in this section are wrappers around the main Python
    # API allowing them to be called directly from the terminal as a CLI
    # executable/script.

    def parse_args(self, args):
        """Parse command line parameters

        Args:
          args (List[str]): command line parameters as list of strings
              (for example  ``["--help"]``).

        Returns:
          :obj:`argparse.Namespace`: command line parameters namespace
        """
        parser = argparse.ArgumentParser(description="Just a Fibonacci demonstration")
        parser.add_argument(
            "--version",
            action="version",
            version=f"k8soptimizer {__version__}",
        )
        # parser.add_argument(dest="n", help="n-th Fibonacci number", type=int, metavar="INT")
        parser.add_argument(
            "-v",
            "--verbose",
            dest="loglevel",
            help="set loglevel to INFO",
            action="store_const",
            const=logging.INFO,
        )
        parser.add_argument(
            "-vv",
            "--very-verbose",
            dest="loglevel",
            help="set loglevel to DEBUG",
            action="store_const",
            const=logging.DEBUG,
        )
        return parser.parse_args(args)

    def setup_logging(self, loglevel):
        """Setup basic logging

        Args:
          loglevel (int): minimum loglevel for emitting messages
        """
        logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
        logging.basicConfig(
            level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
        )

    def run_old(self):
        """Wrapper allowing :func:`fib` to be called with string arguments in a CLI fashion

        Instead of returning the value from :func:`fib`, it prints the result to the
        ``stdout`` in a nicely formatted message.

        Args:
          args (List[str]): command line parameters as list of strings
              (for example  ``["--verbose", "42"]``).
        """
        # args = self.parse_args(args)
        # self.setup_logging(args.loglevel)
        # _logger.debug("Starting crazy calculations...")


if __name__ == "__main__":
    # ^  This is a guard statement that will prevent the following code from
    #    being executed in the case someone imports this file instead of
    #    executing it as a script.
    #    https://docs.python.org/3/library/__main__.html

    # After installing your project with pip, users can also run your Python
    # modules as scripts via the ``-m`` flag, as defined in PEP 338::
    #
    #     python -m k8soptimizer.cli 42
    #
    Cli(sys.argv[1:]).run()
