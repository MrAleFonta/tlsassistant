from enum import Enum
from os import mkdir

from modules.stix.stix import Stix
from utils.validation import Validator, rec_search_key
from utils import output
from datetime import datetime
from os.path import sep
from utils.logger import Logger
from requests.structures import CaseInsensitiveDict
from jinja2 import Environment, FileSystemLoader
from pathlib import Path
from utils.globals import version
from distutils.dir_util import copy_tree as cp
from utils.prune import pruner
from pprint import pformat


class Report:
    """
    Output Module that generates the report.

    """

    class Mode(Enum):
        """
        Enum for the report mode.
        """

        HOSTS = 0
        MODULES = 1

    def __init__(self):
        self.__input_dict = {}
        self.__path = ""
        self.__template_dir = Path(f"configs{sep}out_template")
        self.__logging = Logger("Report")

    def input(self, **kwargs):
        """
        Input function for the Report module.
        :param kwargs: Arguments for the Report module. See below.
        :type kwargs: dict

        :Keyword Arguments:
        * *results* (dict) -- Dictionary containing the results of the scan.
        * *path* (string) -- Path to the report.
        * *mode* (Mode) -- Report mode.
        * *stix* (bool) -- If True, the report will be in STIX format.
        """
        self.__input_dict = kwargs

    def __modules_report_formatter(self, results: dict, modules: list) -> dict:
        """
        Formats the results of the modules.

        :param results: Dictionary containing the results of the scan.
        :type results: dict
        :param modules: List of modules to include in the report.
        :type modules: list
        :return: Dictionary containing the results of the scan.
        :rtype: dict
        """
        out = {}
        for module in modules:
            vuln_hosts = []
            raw_results = {}
            if module not in out:
                out[module] = {}
            for hostname in results:
                self.__logging.debug(f"Generating report for {hostname}")
                if module in results[hostname]:
                    if "raw" in results[hostname][module]:
                        raw_results[hostname] = results[hostname][module]["raw"].copy()
                    if "Entry" in results[hostname][module]:
                        out[module] = CaseInsensitiveDict(
                            results[hostname][module]["Entry"]
                        )
                    if hostname not in vuln_hosts:
                        vuln_hosts.append(hostname)
            if raw_results:
                out[module]["raw"] = pformat(raw_results.copy(), indent=2)
            if vuln_hosts:
                out[module]["hosts"] = vuln_hosts.copy()
            if not out[module]:
                del out[module]
        return out

    def __hosts_report_formatter(self, results: dict) -> dict:
        """
        Formats the results of the hosts.

        :param results: Dictionary containing the results of the scan.
        :type results: dict
        :return: Dictionary containing the results of the scan.
        :rtype: dict
        """
        out = {}
        for hostname in results:
            # the results are good, we need to remove the "Entry" key but preserve the rest with the CaseInsensitiveDict
            if hostname not in out:
                out[hostname] = {}
            for module in results[hostname]:
                raw_results = {}
                if "raw" in results[hostname][module]:
                    raw_results = results[hostname][module]["raw"].copy()
                if "Entry" in results[hostname][module]:
                    out[hostname][module] = CaseInsensitiveDict(
                        results[hostname][module]["Entry"]
                    )
                    if raw_results:
                        out[hostname][module]["raw"] = pformat(
                            raw_results.copy(), indent=2
                        )
        return out

    def __jinja2__report(
        self, mode: Mode, results: dict, modules: list, date: datetime.date
    ):
        """
        Generates the report using jinja2.

        :param mode: Report mode.
        :type mode: Mode
        :param results: Dictionary containing the results of the scan.
        :type results: dict
        :param modules: List of modules to include in the report.
        :type modules: list
        :param date: Date of the scan.
        :type date: datetime.date
        """
        self.__logging.debug(f"Generating report in jinja2..")
        fsl = FileSystemLoader(searchpath=self.__template_dir)
        env = Environment(loader=fsl)
        to_process = {"version": version, "date": date, "modules": modules}
        if mode == self.Mode.MODULES:
            self.__logging.info(f"Generating modules report..")
            template = env.get_template(f"modules_report.html")
            to_process["results"] = self.__modules_report_formatter(results, modules)
        elif mode == self.Mode.HOSTS:
            self.__logging.info(f"Generating hosts report..")
            template = env.get_template(f"hosts_report.html")
            to_process["results"] = self.__hosts_report_formatter(results)
        else:
            raise ValueError(f"Unknown mode: {mode}")
        return template.render(**to_process)

    def __extract_results(self, res: dict) -> tuple:
        """
        Extracts the results from the input dictionary.

        :param res: Input dictionary.
        :type res: dict
        :return: Tuple containing the results and the modules.
        :rtype: tuple
        """
        # due to the fact that the results are in a dict with the loaded_modules, we have to extract the results
        # by removing the loaded_modules
        modules = {}
        for hostname in res:
            if "loaded_modules" in res[hostname]:
                modules.update(res[hostname]["loaded_modules"].copy())
                del res[hostname]["loaded_modules"]
                res[hostname] = res[hostname]["results"]
        return res, modules

    def run(self, **kwargs):
        """
        Runs the report.

        :param kwargs: Arguments for the Report module. See below.
        :type kwargs: dict

        :Keyword Arguments:
        * *results* (dict) -- Dictionary containing the results of the scan.
        * *path* (string) -- Path to the report.
        * *mode* (Mode) -- Report mode.
        * *stix* (bool) -- If True, the report will be generated in STIX format.
        """

        self.input(**kwargs)
        assert "path" in self.__input_dict, "Missing output path"
        assert "results" in self.__input_dict, "Missing results list"
        assert "mode" in self.__input_dict, "Missing mode"
        assert "stix" in self.__input_dict, "Missing stix flag"

        path = self.__input_dict["path"]
        self.__path = Path(path)

        Validator(
            [
                (path, str),
                (self.__input_dict["results"], dict),
                (self.__input_dict["mode"], self.Mode),
                (self.__input_dict["stix"], bool),
            ]
        )

        if not Path("results").exists():
            self.__logging.debug("Adding result folder...")
            mkdir("results")
        if not Path(f"results{sep}assets").exists():
            self.__logging.debug("Copying assets folder...")
            cp(
                str(Path(f"configs{sep}out_template{sep}assets").absolute()),
                str(Path(f"results{sep}assets").absolute()),
            )

        output_file = Path(f"results{sep}{self.__path.stem}.html")
        output_path = output_file.absolute()
        results, modules = self.__extract_results(
            self.__input_dict["results"]
        )  # obtain results removing loaded_modules
        results = pruner(results)  # prune empty results
        # this block is needed to prepare the output of the compliance modules
        if any([module in modules for module in ["compare_one", "compare_many"]]):
            module = "compare_one" if "compare_one" in modules else "compare_many"
            for hostname in results:
                if results[hostname].get(module):
                    for sheet in results[hostname][module]:
                        if "mitigation" in results[hostname][module][sheet]:
                            modules[module+"_"+sheet] = ""
                            results[hostname][module+"_"+sheet] = results[hostname][module][sheet]
                        else:
                            self.__logging.debug(f"Removing {sheet} from {hostname} because no mitigation was found")
                del results[hostname][module]
            del modules[module]
        # now, we want to divide raw from mitigations
        for hostname in results:
            for module in results[hostname]:
                raw = results[hostname][module].copy()
                if "mitigation" in raw:
                    del raw["mitigation"]
                for mitigation in rec_search_key(
                    "mitigation", results[hostname][module]
                ):
                    if mitigation is not None:
                        results[hostname][
                            module
                        ] = (
                            mitigation.copy()
                        )  # i'm expecting only one mitigation per module, is it ok?
                results[hostname][module]["raw"] = raw
        with open(output_path, "w") as f:
            f.write(
                self.__jinja2__report(
                    mode=self.__input_dict["mode"],
                    modules=list(modules.keys()),
                    results=results,
                    date=datetime.now().replace(microsecond=0).strftime("%Y-%m-%d_%H%M%S"),
                )
            )
        self.__logging.debug("Checking if needs pdf...")

        if self.__path.suffix.lower() == ".pdf":
            output_path = f"{output_file.absolute().parent}{sep}{output_file.stem}.pdf"
            self.__logging.debug("Starting HTML to PDF...")
            output.html_to_pdf(str(output_file.absolute()), output_path)
        self.__logging.info(f"Report generated at {output_path}")

        self.__logging.debug("Checks if needs stix...")

        if "stix" in self.__input_dict and self.__input_dict["stix"]:
            stix_output_path = Path(
                f"{output_file.absolute().parent}{sep}stix_{output_file.stem}.json"
            ).absolute()
            results_to_stix = (
                self.__hosts_report_formatter(results)
                if self.__input_dict["mode"] == self.Mode.HOSTS
                else self.__modules_report_formatter(results, modules)
            )
            self.__logging.info("Starting STIX generation...")
            Stix(type_of_analysis=self.__input_dict["mode"].value).build_and_save(
                results_to_stix, modules, str(stix_output_path)
            )

    # todo: add PDF library
