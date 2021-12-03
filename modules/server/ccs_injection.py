from modules.server.testssl_base import Testssl_base
from modules.stix.stix_base import Bundled
from utils.mitigations import load_mitigation


class Ccs_injection(Testssl_base):

    """
    Analysis of the css_injection testssl results
    """

    stix = Bundled(mitigation_object=load_mitigation("CCS_INJECTION"))
    # to override
    def _set_arguments(self):
        """
        Sets the arguments for the testssl command
        """
        self._arguments = ["-I"]

    # to override
    def _worker(self, results):
        """
        The worker method, which runs the testssl command

        :param results: dict
        :return: dict
        :rtype: dict
        """
        return self._obtain_results(results, ["CCS"])
