"""
This is a skeleton file that can serve as a starting point for a Python
console script. To run this script uncomment the following lines in the
``[options.entry_points]`` section in ``setup.cfg``::

    console_scripts =
         fibonacci = k8soptimizer.main:run

Then run ``pip install .`` (or ``pip install -e .`` for editable mode)
which will install the command ``fibonacci`` inside your current environment.

Besides console scripts, the header (i.e. until ``logging``...) of this file can
also be used as template for Python modules.

Note:
    This file can be renamed depending on your needs or safely removed if not needed.

References:
    - https://setuptools.pypa.io/en/latest/userguide/entry_point.html
    - https://pip.pypa.io/en/stable/reference/pip_install
"""

import argparse
import logging
import sys

import requests
import json
import re
import datetime
import os

from kubernetes import client, config

from k8soptimizer import __version__

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"

# Configs can be set in Configuration class directly or using helper utility
config.load_kube_config()

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
PROMETHEUS_QUERY_MEMORY = os.getenv(
    "PROMETHEUS_QUERY_MEMORY",
    'round(max by (container,namespace) (round((1 * avg(quantile_over_time(.95,container_memory_working_set_bytes{container!="POD",container!=""}[7d])) by (container,pod,namespace)))))',
)
PROMETHEUS_QUERY_CPU = os.getenv(
    "PROMETHEUS_QUERY_CPU",
    'avg by (container, namespace) (irate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]))',
)

NAMESPACE_FILTER = os.getenv("NAMESPACE_FILTER", ".*")
DEPLOYMENT_FILTER = os.getenv("DEPLOYMENT_FILTER", ".*")
CONTAINER_FILTER = os.getenv("CONTAINER_FILTER", ".*")
AGE_FILTER = int(os.getenv("AGE_FILTER", 3600))

CPU_MIN = float(os.getenv("CPU_MIN", 0.001))
CPU_MAX = float(os.getenv("CPU_MAX", 4))
MEMORY_MIN = int(os.getenv("MEMORY_MIN", 1024**2 * 16))
MEMORY_MAX = int(os.getenv("MEMORY_MAX", 1024**3 * 16))
MEMORY_LIMIT_MIN = int(os.getenv("MEMORY_LIMIT_MIN", 1024**2 * 128))
MEMORY_LIMIT_MAX = int(os.getenv("MEMORY_LIMIT_MAX", 1024**3 * 32))
MEMORY_LIMIT_RATIO = int(os.getenv("MEMORY_LIMIT_RATIO", 1.5))

CHANGE_MIN = os.getenv("CHANGE_MIN", 0.1)

class Optimizer:

    def __init__(self, config={}):
        self._config = config
        self.logger = logging.getLogger(__name__)
        self.setup_logging(logging.INFO)
        self.logger.warn('init optimizer')

    def run(self):
        #prometheus = PrometheusQuery()
        #prometheus.query('hallo')
        self.logger.info('run optimizer')

    def setup_logging(self, loglevel):
        """Setup basic logging

        Args:
          loglevel (int): minimum loglevel for emitting messages
        """
        logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
        logging.basicConfig(
            level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
        )


    def get_max_cpu_cores_per_technology(technology):
        if technology == "nodejs":
            return 1
        return 100

    def get_hpa_target_ratio(namespace_name, deployment_name):
        autoscaling_api = client.AutoscalingV2Api()
        hpa_ratio_addon = 0
        hpa_enabled = False
        hpa_min_replica = 0
        hpa_max_replica = 0
        hpa_range = 0
        hpa_target_cpu = None
        hpa_target_memory = None
        target_ratio_cpu = 1
        target_ratio_memory = 1
        for hpa in autoscaling_api.list_namespaced_horizontal_pod_autoscaler(
            namespace=namespace_name
        ).items:
            if hpa.spec.scale_target_ref.kind != "Deployment":
                continue
            if hpa.spec.scale_target_ref.name != deployment_name:
                continue
            hpa_enabled = True
            hpa_min_replica = hpa.spec.min_replicas
            hpa_max_replica = hpa.spec.max_replicas
            hpa_range = hpa_max_replica - hpa_min_replica
            for metric in hpa.spec.metrics:
                if metric.type != "Resource":
                    continue
                if metric.resource.name == "cpu":
                    hpa_target_cpu = metric.resource.target.average_utilization / 100
                    target_ratio_cpu = round(1 / hpa_target_cpu, 2)
                    self.logger.info(
                        "Changing target ratio cpu to match hpa utilization: %s"
                        % target_ratio_cpu
                    )
                if metric.resource.name == "memory":
                    hpa_target_memory = metric.resource.target.average_utilization / 100
                    target_ratio_memory = round(1 / hpa_target_memory, 2)
                    self.logger.info(
                        "Changing target ratio memory to match hpa utilization: %s"
                        % target_ratio_memory
                    )

        if hpa_enabled == True:
            replica_count_history = get_max_pods_per_deployment_history(
                namespace_name, deployment_name
            )
            self.logger.info("Hpa min repliacs: %s" % hpa_min_replica)
            self.logger.info("Hpa max replicas: %s" % hpa_max_replica)
            self.logger.info("Hpa avg count history: %s" % replica_count_history)
            # increase request if hpa is enabled and current replica count is higher than min replica count
            if replica_count_history > hpa_min_replica and hpa_range > 0:
                self.logger.info("Hpa avg range: %s" % hpa_range)
                hpa_range_position = replica_count_history - hpa_min_replica
                self.logger.info("Hpa avg range position: %s" % hpa_range_position)
                hpa_ratio_addon = round((hpa_range_position) / hpa_range, 2)

        if hpa_ratio_addon > 0.5:
            self.logger.info(
                "Increasing target ratio cpu due to hpa near limit: %s" % hpa_ratio_addon
            )
            target_ratio_cpu = round(target_ratio_cpu + hpa_ratio_addon, 3)
            target_ratio_memory = round(target_ratio_memory + hpa_ratio_addon, 3)

        return {target_ratio_cpu, target_ratio_memory}


    def get_namespaces(namespace_filter=".*"):
        core_api = client.CoreV1Api()
        resp_ns = core_api.list_namespace(watch=False)
        resp_rs = []

        for namespace in resp_ns.items:
            self.logger.debug(namespace)
            namespace_name = namespace.metadata.name

            x = re.search(namespace_filter, namespace_name)
            if x == None:
                self.logger.debug(
                    "Skipping namespace due to NAMESPACE_FILTER: %s" % namespace_name
                )
                continue

            resp_rs.append(namespace)

        return resp_rs

    def get_deployments(namespace_name, deployment_filter=".*", only_running=True):
        apis_api = client.AppsV1Api()
        resp_deploy = apis_api.list_namespaced_deployment(namespace=namespace_name)
        resp_rs = []
        for deployment in resp_deploy.items:
            self.logger.debug(deployment)
            deployment_name = deployment.metadata.name

            x = re.search(deployment_filter, deployment_name)
            if x == None:
                self.logger.debug(
                    "Skipping deployment due to DEPLOYMENT_FILTER: %s" % deployment_name
                )
                continue

            if only_running and deployment.spec.replicas == 0:
                self.logger.debug(
                    "Skipping deployment due to zero replicas: %s" % deployment_name
                )
                continue

            resp_rs.append(deployment)

        return resp_rs

    def run():
        """Wrapper allowing :func:`fib` to be called with string arguments in a CLI fashion

        Instead of returning the value from :func:`fib`, it prints the result to the
        ``stdout`` in a nicely formatted message.

        Args:
        args (List[str]): command line parameters as list of strings
            (for example  ``["--verbose", "42"]``).
        """
        self.logger.debug("Starting crazy calculations...")

        old_cpu_sum = 0
        old_memory_sum = 0
        new_cpu_sum = 0
        new_memory_sum = 0

        self.logger.debug("Listing k8s namespaces")
        for namespace in get_namespaces(NAMESPACE_FILTER):
            namespace_name = namespace.metadata.name

            self.logger.info("Processing namespace: %s" % namespace_name)

            self.logger.debug("Listing k8s deployments")
            for deployment in get_deployments(namespace_name, DEPLOYMENT_FILTER):
                deployment_name = deployment.metadata.name

                self.logger.info("Processing deployment: %s" % deployment_name)

                self.logger.debug("Checking deployment status")
                latest_change = None
                oldest_change = None
                for condition in deployment.status.conditions:
                    if condition.last_update_time == None:
                        continue

                    if latest_change == None:
                        latest_change = datetime.datetime.fromtimestamp(
                            condition.last_update_time.timestamp()
                        )

                    if latest_change < datetime.datetime.fromtimestamp(
                        condition.last_update_time.timestamp()
                    ):
                        latest_change = datetime.datetime.fromtimestamp(
                            condition.last_update_time.timestamp()
                        )

                    if oldest_change == None:
                        oldest_change = datetime.datetime.fromtimestamp(
                            condition.last_update_time.timestamp()
                        )

                    if oldest_change > datetime.datetime.fromtimestamp(
                        condition.last_update_time.timestamp()
                    ):
                        oldest_change = datetime.datetime.fromtimestamp(
                            condition.last_update_time.timestamp()
                        )

                self.logger.debug("Oldest change: {}".format(oldest_change))
                self.logger.debug("Newest change: {}".format(latest_change))

                if oldest_change > (
                    datetime.datetime.now() - datetime.timedelta(seconds=AGE_FILTER)
                ):
                    self.logger.info(
                        "Skipping deployment because of oldest change is too recent: {}".format(
                            oldest_change
                        )
                    )
                    continue

                self.logger.info("Inital target ratio cpu: %s" % target_ratio_cpu)
                self.logger.info("Inital target ratio memory: %s" % target_ratio_memory)

                # TODO OOM addon
                target_ratio_cpu, target_ratio_memory = get_hpa_target_ratio(
                    namespace_name, deployment_name
                )

                self.logger.info("Final target ratio cpu: %s" % target_ratio_cpu)
                self.logger.info("Final target ratio memory: %s" % target_ratio_memory)
                i = -1

                for container in deployment.spec.template.spec.containers:
                    container_name = container.name
                    i += 1

                    x = re.search(CONTAINER_FILTER, container_name)
                    if x == None:
                        self.logger.info(
                            "Skipping container due to CONTAINER_FILTER: %s"
                            % container_name
                        )
                        continue

                    self.logger.info("Processing container: %s" % container_name)

                    nodejs = is_nodejs_container(
                        namespace_name, deployment_name, container_name, "deployment"
                    )
                    if nodejs == True:
                        self.logger.info("Found nodejs in container: %s" % container_name)

                    if hasattr(container, "resources") is False:
                        self.logger.info(
                            "Skipping container due to missing resources: %s"
                            % container_name
                        )
                        continue
                    if hasattr(container.resources, "requests") is False:
                        self.logger.info(
                            "Skipping container due to missing requests: %s"
                            % container_name
                        )
                        continue
                    if container.resources.requests is None:
                        self.logger.info(
                            "Skipping container due to missing requests: %s"
                            % container_name
                        )
                        continue
                    if "memory" not in container.resources.requests:
                        self.logger.info(
                            "Skipping container due to missing memory requests: %s"
                            % container_name
                        )
                        continue
                    if "cpu" not in container.resources.requests:
                        self.logger.info(
                            "Skipping container due to missing cpu requests: %s"
                            % container_name
                        )
                        continue

                    old_memory = convert_to_bytes(container.resources.requests["memory"])
                    new_memory = max(
                        MEMORY_MIN,
                        min(
                            MEMORY_MAX,
                            get_memory_bytes_usage_history(
                                namespace_name,
                                deployment_name,
                                container_name,
                                "deployment",
                            )
                            * target_ratio_memory,
                        ),
                    )
                    diff_memory = round(((new_memory / old_memory) - 1) * 100)

                    if abs(diff_memory) < CHANGE_MIN * 100:
                        self.logger.info(
                            "Memory request change is too small: {}%".format(diff_memory)
                        )
                        new_memory = old_memory
                    else:
                        self.logger.info(
                            "Memory requests change: {} -> {} ({}%)".format(
                                str(round(old_memory / 1024 / 1024)) + "Mi",
                                str(round(new_memory / 1024 / 1024)) + "Mi",
                                diff_memory,
                            )
                        )

                    old_memory_limit = convert_to_bytes(
                        container.resources.limits["memory"]
                    )
                    new_memory_limit = max(
                        MEMORY_LIMIT_MIN,
                        min(MEMORY_LIMIT_MAX, new_memory * MEMORY_LIMIT_RATIO),
                    )
                    diff_memory_limit = round(
                        ((new_memory_limit / old_memory_limit) - 1) * 100
                    )

                    if abs(diff_memory_limit) < CHANGE_MIN * 100:
                        self.logger.info(
                            "Memory limit change is too small: {}%".format(
                                diff_memory_limit
                            )
                        )
                        new_memory_limit = old_memory_limit
                    else:
                        self.logger.info(
                            "Memory limits change: {} -> {} ({}%)".format(
                                str(round(old_memory_limit / 1024 / 1024)) + "Mi",
                                str(round(new_memory_limit / 1024 / 1024)) + "Mi",
                                diff_memory_limit,
                            )
                        )

                    old_cpu = convert_to_number(container.resources.requests["cpu"])
                    new_cpu = round(
                        max(
                            CPU_MIN,
                            min(
                                CPU_MAX,
                                get_cpu_cores_usage_history(
                                    namespace_name,
                                    deployment_name,
                                    container_name,
                                    "deployment",
                                )
                                * target_ratio_cpu,
                            ),
                        ),
                        3,
                    )

                    diff_cpu = round(((new_cpu / old_cpu) - 1) * 100)

                    if abs(diff_cpu) < CHANGE_MIN * 100:
                        self.logger.info(
                            "CPU requests change is too small: {}%".format(diff_cpu)
                        )
                        new_cpu = old_cpu
                    else:
                        self.logger.info(
                            "CPU requests change: {} -> {} ({}%)".format(
                                str(round(old_cpu * 1000)) + "Mi",
                                str(round(new_cpu * 1000)) + "Mi",
                                diff_cpu,
                            )
                        )

                    old_cpu_sum += old_cpu * deployment.spec.replicas
                    new_cpu_sum += new_cpu * deployment.spec.replicas
                    old_memory_sum += old_memory * deployment.spec.replicas
                    new_memory_sum += new_memory * deployment.spec.replicas

                    deployment.spec.template.spec.containers[i].resources.requests[
                        "cpu"
                    ] = (str(round(new_cpu * 1000)) + "Mi")
                    deployment.spec.template.spec.containers[i].resources.requests[
                        "memory"
                    ] = (str(round(new_memory / 1024 / 1024)) + "Mi")
                    deployment.spec.template.spec.containers[i].resources.limits[
                        "memory"
                    ] = (str(round(new_memory_limit / 1024 / 1024)) + "Mi")

                # Apply the changes
                self.logger.info("Updating deployment: %s" % deployment_name)
                # apis_api.patch_namespaced_deployment(
                #    name=deployment_name, namespace=namespace_name, body=deployment, pretty=True
                # )

                print("")

        if old_cpu_sum > 0:
            diff_cpu_sum = round(((new_cpu_sum / old_cpu_sum) - 1) * 100)
            diff_memory_sum = round(((new_memory_sum / old_memory_sum) - 1) * 100)

            self.logger.info(
                "Summary CPU requests change: {} -> {} ({}%)".format(
                    str(round(old_cpu_sum * 1000)) + "Mi",
                    str(round(new_cpu_sum * 1000)) + "Mi",
                    diff_cpu_sum,
                )
            )

            self.logger.info(
                "Summary Memory requests change: {} -> {} ({}%)".format(
                    str(round(old_memory_sum / 1024 / 1024)) + "Mi",
                    str(round(new_memory_sum / 1024 / 1024)) + "Mi",
                    diff_memory_sum,
                )
            )

        self.logger.info("Script ends here")


def run():
    """Calls :func:`main` passing the CLI arguments extracted from :obj:`sys.argv`

    This function can be used as entry point to create console scripts with setuptools.
    """
    #main(sys.argv[1:])
