"""
This is a skeleton file that can serve as a starting point for a Python
console script. To run this script uncomment the following lines in the
``[options.entry_points]`` section in ``setup.cfg``::

    console_scripts =
         fibonacci = k8soptimizer.main:run

Then run ``pip install .`` (or ``pip install -e .`` for editable mode)
which will install the command ``fibonacci`` inside your current environment.

Besides console scripts, the header (i.e. until ``_logger``...) of this file can
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

from . import helpers

__author__ = "Philipp Hellmich"
__copyright__ = "Philipp Hellmich"
__license__ = "MIT"

_logger = logging.getLogger(__name__)

# Configs can be set in Configuration class directly or using helper utility
config.load_kube_config()

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

NAMESPACE_FILTER = os.getenv("NAMESPACE_FILTER", ".*")
DEPLOYMENT_FILTER = os.getenv("DEPLOYMENT_FILTER", ".*")
CONTAINER_FILTER = os.getenv("CONTAINER_FILTER", ".*")
AGE_FILTER = int(os.getenv("AGE_FILTER", 3600))

CPU_MIN = float(os.getenv("CPU_MIN", 0.001))
CPU_MAX = float(os.getenv("CPU_MAX", 4))
CPU_MAX_NODEJS = 1
MEMORY_MIN = int(os.getenv("MEMORY_MIN", 1024**2 * 16))
MEMORY_MAX = int(os.getenv("MEMORY_MAX", 1024**3 * 16))
MEMORY_LIMIT_MIN = int(os.getenv("MEMORY_LIMIT_MIN", 1024**2 * 128))
MEMORY_LIMIT_MAX = int(os.getenv("MEMORY_LIMIT_MAX", 1024**3 * 32))
MEMORY_LIMIT_RATIO = int(os.getenv("MEMORY_LIMIT_RATIO", 1.5))

CHANGE_MIN = os.getenv("CHANGE_MIN", 0.1)

# ---- Python API ----
# The functions defined in this section can be imported by users in their
# Python scripts/interactive interpreter, e.g. via
# `from k8soptimizer.skeleton import fib`,
# when using this Python module as a library.


def query_prometheus(query):
    _logger.debug(query)
    response = requests.get(PROMETHEUS_URL + "/api/v1/query", params={"query": query})
    j = json.loads(response.text)
    _logger.debug(j)
    if "data" not in j:
        raise RuntimeError("Got invalid results from query: {}".format(query))
    if "result" not in j["data"]:
        raise RuntimeError("Got invalid results from query: {}".format(query))
    return j


def get_max_cpu_cores_per_runtime(runtime):
    if runtime == "nodejs":
        return 1
    return 100


def get_max_pods_per_deployment_history(
    namespace_name,
    deployment_name,
    lookback_minutes=3600 * 24 * 7,
    quantile_over_time=0.95,
):
    query = 'max(quantile_over_time({quantile_over_time}, kube_deployment_spec_replicas{{job="kube-state-metrics", namespace="{namespace_name}", deployment="{deployment_name}"}}[{lookback_minutes}m]))'.format(
        quantile_over_time=quantile_over_time,
        namespace_name=namespace_name,
        deployment_name=deployment_name,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return int(j["data"]["result"][0]["value"][1])


def get_cpu_cores_usage_history(
    namespace,
    workload,
    container,
    workload_type="deployment",
    lookback_minutes=3600 * 24 * 7,
    quantile_over_time=0.95,
):
    query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_cpu_cores_avg{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


def get_memory_bytes_usage_history(
    namespace,
    workload,
    container,
    workload_type="deployment",
    lookback_minutes=3600 * 24 * 7,
    quantile_over_time=0.95,
):
    query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_memory_bytes_max{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


def discover_container_runtime(
    namespace, workload, container, workload_type="deployment"
):
    if is_nodejs_container(namespace, workload, container, workload_type):
        return "nodejs"
    return None


def is_nodejs_container(namespace, workload, container, workload_type="deployment"):
    query = 'count(nodejs_version_info{{container="{container}"}} * on(namespace,pod) group_left(workload, workload_type) namespace_workload_pod:kube_pod_owner:relabel{{workload="{workload}", workload_type="{workload_type}", namespace="{namespace}"}}) by (namespace, workload, workload_type, container)'.format(
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        return False

    if float(j["data"]["result"][0]["value"][1]) > 0:
        return True

    return False


def get_hpa_for_deployment(namespace_name, deployment_name):
    autoscaling_api = client.AutoscalingV2Api()
    for hpa in autoscaling_api.list_namespaced_horizontal_pod_autoscaler(
        namespace=namespace_name
    ).items:
        if hpa.spec.scale_target_ref.kind != "Deployment":
            continue
        if hpa.spec.scale_target_ref.name != deployment_name:
            continue
        return hpa
    return None


def is_hpa_enabled_for_deployment(namespace_name, deployment_name):
    return get_hpa_for_deployment(namespace_name, deployment_name) is not None


def calculate_hpa_target_ratio(
    namespace_name, deployment_name, lookback_minutes=3600 * 24 * 7
):
    hpa_ratio_addon = 0
    hpa_min_replica = 0
    hpa_max_replica = 0
    hpa_range = 0
    target_ratio_cpu = 1
    target_ratio_memory = 1

    hpa = get_hpa_for_deployment(namespace_name, deployment_name)
    if hpa is None:
        return {target_ratio_cpu, target_ratio_memory}

    hpa_min_replica = hpa.spec.min_replicas
    hpa_max_replica = hpa.spec.max_replicas
    hpa_range = hpa_max_replica - hpa_min_replica
    for metric in hpa.spec.metrics:
        if metric.type != "Resource":
            continue
        if metric.resource.name == "cpu":
            hpa_target_cpu = metric.resource.target.average_utilization / 100
            target_ratio_cpu = round(1 / hpa_target_cpu, 2)
            _logger.info(
                "Changing target ratio cpu to match hpa utilization: %s"
                % target_ratio_cpu
            )
        if metric.resource.name == "memory":
            hpa_target_memory = metric.resource.target.average_utilization / 100
            target_ratio_memory = round(1 / hpa_target_memory, 2)
            _logger.info(
                "Changing target ratio memory to match hpa utilization: %s"
                % target_ratio_memory
            )

    replica_count_history = round(
        get_max_pods_per_deployment_history(
            namespace_name, deployment_name, lookback_minutes
        )
    )

    oom_killed_history = round(
        get_oom_killed_history(namespace_name, deployment_name, lookback_minutes)
    )

    _logger.debug("Hpa min repliacs: %s" % hpa_min_replica)
    _logger.debug("Hpa max replicas: %s" % hpa_max_replica)
    _logger.debug("Hpa avg count history: %s" % replica_count_history)

    # increase cpu request if current replica count is higher than min replica count
    if replica_count_history > hpa_min_replica and hpa_range > 0:
        _logger.debug("Hpa avg range: %s" % hpa_range)
        hpa_range_position = replica_count_history - hpa_min_replica
        _logger.debug("Hpa avg range position: %s" % hpa_range_position)
        hpa_ratio_addon = round((hpa_range_position) / hpa_range, 2)

    if hpa_ratio_addon > 0.5:
        _logger.info(
            "Increasing target ratio cpu due to hpa near limit: %s" % hpa_ratio_addon
        )
        target_ratio_cpu = round(target_ratio_cpu + hpa_ratio_addon, 3)

    # increase memory request if oom was detected
    if oom_killed_history > 0:
        target_ratio_memory = 2

    return {"cpu": target_ratio_cpu, "memory": target_ratio_memory}


def calculate_cpu_requests(
    namespace_name, workload, workload_type, container_name, target_ratio_cpu
):
    new_cpu = round(
        max(
            CPU_MIN,
            min(
                CPU_MAX,
                get_cpu_cores_usage_history(
                    namespace_name,
                    workload,
                    container_name,
                    workload_type,
                )
                * target_ratio_cpu,
            ),
        ),
        3,
    )
    runtime = discover_container_runtime(
        namespace_name, workload, container_name, workload_type
    )
    if runtime == "nodejs":
        new_cpu = min(CPU_MAX_NODEJS, new_cpu)

    return new_cpu


def calculate_memory_requests(
    namespace_name, workload, workload_type, container_name, target_ratio_memory
):
    new_memory = round(
        max(
            MEMORY_MIN,
            min(
                MEMORY_MAX,
                get_memory_bytes_usage_history(
                    namespace_name,
                    workload,
                    container_name,
                    workload_type,
                )
                * target_ratio_memory,
            ),
        )
    )

    return new_memory


def calculate_memory_limits(
    namespace_name, workload, workload_type, container, memory_requests
):
    container_name = container.name
    new_memory_limit = max(
        MEMORY_LIMIT_MIN,
        min(MEMORY_LIMIT_MAX, memory_requests * MEMORY_LIMIT_RATIO),
    )
    return new_memory_limit


def get_namespaces(namespace_filter=".*"):
    core_api = client.CoreV1Api()
    resp_ns = core_api.list_namespace(watch=False)
    resp_rs = []

    for namespace in resp_ns.items:
        _logger.debug(namespace)
        namespace_name = namespace.metadata.name

        x = re.search(namespace_filter, namespace_name)
        if x == None:
            _logger.debug(
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
        _logger.debug(deployment)
        deployment_name = deployment.metadata.name

        x = re.search(deployment_filter, deployment_name)
        if x == None:
            _logger.debug(
                "Skipping deployment due to DEPLOYMENT_FILTER: %s" % deployment_name
            )
            continue

        if only_running and deployment.spec.replicas == 0:
            _logger.debug(
                "Skipping deployment due to zero replicas: %s" % deployment_name
            )
            continue

        resp_rs.append(deployment)

    return resp_rs


def get_max_pods_per_deployment_history(
    namespace_name,
    deployment_name,
    lookback_minutes=3600 * 24 * 7,
    quantile_over_time="0.95",
):
    query = 'max(quantile_over_time({quantile_over_time}, kube_deployment_spec_replicas{{job="kube-state-metrics", namespace="{namespace_name}", deployment="{deployment_name}"}}[{lookback_minutes}m]))'.format(
        quantile_over_time=quantile_over_time,
        namespace_name=namespace_name,
        deployment_name=deployment_name,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return int(j["data"]["result"][0]["value"][1])


def get_cpu_cores_usage_history(
    namespace,
    workload,
    container,
    workload_type="deployment",
    lookback_minutes=3600 * 24 * 7,
    quantile_over_time="0.95",
):
    query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_cpu_cores_avg{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


def get_memory_bytes_usage_history(
    namespace,
    workload,
    container,
    workload_type="deployment",
    lookback_minutes=3600 * 24 * 7,
    quantile_over_time=0.95,
):
    query = 'quantile_over_time({quantile_over_time}, kube_workload_container_resource_usage_memory_bytes_max{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


def get_oom_killed_history(
    namespace,
    workload,
    container,
    workload_type="deployment",
    lookback_minutes=3600 * 24 * 7,
):
    query = 'sum_over_time(kube_workload_container_resource_usage_memory_oom_killed{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
        quantile_over_time=quantile_over_time,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        return 0

    if float(j["data"]["result"][0]["value"][1]) > 0:
        return float(j["data"]["result"][0]["value"][1])

    return 0


def is_nodejs_container(namespace, workload, container, workload_type="deployment"):
    query = 'count(nodejs_version_info{{container="{container}"}} * on(namespace,pod) group_left(workload, workload_type) namespace_workload_pod:kube_pod_owner:relabel{{workload="{workload}", workload_type="{workload_type}", namespace="{namespace}"}}) by (namespace, workload, workload_type, container)'.format(
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        return False

    if float(j["data"]["result"][0]["value"][1]) > 0:
        return True

    return False


def optimze_deplayment(deployment, dry_run=True):
    apis_api = client.AppsV1Api()
    _logger.info("Optimizing deployment: %s" % deployment_name)
    namespace_name = deployment.metadata.namespace
    deployment_name = deployment.metadata.name

    _logger.debug("Checking deployment status")
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

    _logger.debug("Oldest change: {}".format(oldest_change))
    _logger.debug("Newest change: {}".format(latest_change))

    if oldest_change > (
        datetime.datetime.now() - datetime.timedelta(seconds=AGE_FILTER)
    ):
        _logger.info(
            "Skipping deployment because of oldest change is too recent: {}".format(
                oldest_change
            )
        )
        return

    target_ratio = calculate_hpa_target_ratio(namespace_name, deployment_name)

    target_ratio_cpu = target_ratio["cpu"]
    target_ratio_memory = target_ratio["memory"]

    _logger.info("Target ratio cpu: %s" % target_ratio_cpu)
    _logger.info("Target ratio memory: %s" % target_ratio_memory)
    i = -1

    for container in deployment.spec.template.spec.containers:
        i = i + 1
        container_new = optimize_container(
            namespace_name,
            deployment_name,
            container,
            "deployment",
            target_ratio_cpu,
            target_ratio_memory,
        )
        deployment.spec.template.spec[i] = container_new

    # Apply the changes
    if dry_run == True:
        _logger.info("Updating deployment: %s" % deployment_name)
        apis_api.patch_namespaced_deployment(
            name=deployment_name, namespace=namespace_name, body=deployment, pretty=True
        )


def optimize_container(
    namespace_name,
    workload,
    container,
    workload_type="deployment",
    target_ratio_cpu=1,
    target_ratio_memory=1,
):
    container_name = container.name

    _logger.info("Processing container: %s" % container_name)

    new_cpu = optimize_container_cpu_requests(
        namespace_name, workload, container, workload_type, target_ratio_cpu
    )
    new_memory = optimize_container_memory_requests(
        namespace_name, workload, container, workload_type, target_ratio_memory
    )
    new_memory_limit = optimize_container_memory_limits(
        namespace_name, workload, container, workload_type, target_ratio_memory
    )

    # old_cpu_sum += old_cpu * deployment.spec.replicas
    # new_cpu_sum += new_cpu * deployment.spec.replicas
    # old_memory_sum += old_memory * deployment.spec.replicas
    # new_memory_sum += new_memory * deployment.spec.replicas

    container.resources.requests["cpu"] = str(round(new_cpu * 1000)) + "Mi"
    if "cpu" in container.resources.limits:
        del container.resources.limits["cpu"]
    container.resources.requests["memory"] = str(round(new_memory / 1024 / 1024)) + "Mi"
    container.resources.limits["memory"] = (
        str(round(new_memory_limit / 1024 / 1024)) + "Mi"
    )

    return container


def optimize_container_cpu_requests(
    namespace_name, workload, container, workload_type="deployment", target_ratio=1
):
    container_name = container.name
    try:
        old_cpu = convert_to_bytes(container.resources.requests["cpu"])
    except:
        _logger.info("Could not read old cpu requests aassuming it is 0.001")
        old_cpu = 0.001

    new_cpu = calculate_cpu_requests(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_ratio,
    )

    diff_cpu = round(((new_cpu / old_cpu) - 1) * 100)

    if abs(diff_cpu) < CHANGE_MIN * 100:
        _logger.info("CPU requests change is too small: {}%".format(diff_cpu))
        new_cpu = old_cpu
    else:
        _logger.info(
            "CPU requests change: {} -> {} ({}%)".format(
                str(round(old_cpu * 1000)) + "Mi",
                str(round(new_cpu * 1000)) + "Mi",
                diff_cpu,
            )
        )

    return new_cpu


def optimize_container_memory_requests(
    namespace_name, workload, container, workload_type="deployment", target_ratio=1
):
    container_name = container.name

    try:
        old_memory = convert_to_bytes(container.resources.requests["memory"])
    except:
        _logger.info("Could not read old meory requests aassuming it is 1")
        old_memory = 1

    new_memory = calculate_memory_requests(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_ratio,
    )
    diff_memory = round(((new_memory / old_memory) - 1) * 100)

    if abs(diff_memory) < CHANGE_MIN * 100:
        _logger.info("Memory request change is too small: {}%".format(diff_memory))
        new_memory = old_memory
    else:
        _logger.info(
            "Memory requests change: {} -> {} ({}%)".format(
                str(round(old_memory / 1024 / 1024)) + "Mi",
                str(round(new_memory / 1024 / 1024)) + "Mi",
                diff_memory,
            )
        )
    return new_memory


def optimize_container_memory_limits(
    namespace_name,
    workload,
    container,
    workload_type="deployment",
    new_memory=MEMORY_MIN,
):
    container_name = container.name

    try:
        old_memory_limit = convert_to_bytes(container.resources.limits["memory"])
    except:
        _logger.info("Could not read old meory limits aassuming it is 1")
        old_memory_limit = 1

    new_memory_limit = calculate_memory_limits(
        namespace_name,
        workload,
        workload_type,
        container_name,
        new_memory,
    )
    diff_memory_limit = round(((new_memory_limit / old_memory_limit) - 1) * 100)

    if abs(diff_memory_limit) < CHANGE_MIN * 100:
        _logger.info("Memory limit change is too small: {}%".format(diff_memory_limit))
        new_memory_limit = old_memory_limit
    else:
        _logger.info(
            "Memory limits change: {} -> {} ({}%)".format(
                str(round(old_memory_limit / 1024 / 1024)) + "Mi",
                str(round(new_memory_limit / 1024 / 1024)) + "Mi",
                diff_memory_limit,
            )
        )

    return new_memory_limit


# ---- CLI ----
# The functions defined in this section are wrappers around the main Python
# API allowing them to be called directly from the terminal as a CLI
# executable/script.


def parse_args(args):
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


def setup_logging(loglevel):
    """Setup basic logging

    Args:
        loglevel (int): minimum loglevel for emitting messages
    """
    logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    logging.basicConfig(
        level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
    )


def main(args):
    """Wrapper allowing :func:`fib` to be called with string arguments in a CLI fashion

    Instead of returning the value from :func:`fib`, it prints the result to the
    ``stdout`` in a nicely formatted message.

    Args:
        args (List[str]): command line parameters as list of strings
            (for example  ``["--verbose", "42"]``).
    """
    args = parse_args(args)
    setup_logging(args.loglevel)
    _logger.debug("Starting k8soptimizer...")

    # old_cpu_sum = 0
    # old_memory_sum = 0
    # new_cpu_sum = 0
    # new_memory_sum = 0

    _logger.debug("Listing k8s namespaces")
    for namespace in get_namespaces(NAMESPACE_FILTER):
        _logger.debug("Processing namespace: %s" % namespace.metadata.name)
        _logger.debug("Listing k8s deployments")
        for deployment in get_deployments(namespace.metadata.name, DEPLOYMENT_FILTER):
            optimze_deplayment(deployment)

    # if old_cpu_sum > 0:
    #     diff_cpu_sum = round(((new_cpu_sum / old_cpu_sum) - 1) * 100)
    #     diff_memory_sum = round(((new_memory_sum / old_memory_sum) - 1) * 100)

    #     _logger.info(
    #         "Summary CPU requests change: {} -> {} ({}%)".format(
    #             str(round(old_cpu_sum * 1000)) + "Mi",
    #             str(round(new_cpu_sum * 1000)) + "Mi",
    #             diff_cpu_sum,
    #         )
    #     )

    #     _logger.info(
    #         "Summary Memory requests change: {} -> {} ({}%)".format(
    #             str(round(old_memory_sum / 1024 / 1024)) + "Mi",
    #             str(round(new_memory_sum / 1024 / 1024)) + "Mi",
    #             diff_memory_sum,
    #         )
    #     )

    _logger.info("Starting finished k8s optimizer")


def run():
    """Calls :func:`main` passing the CLI arguments extracted from :obj:`sys.argv`

    This function can be used as entry point to create console scripts with setuptools.
    """
    main(sys.argv[1:])


if __name__ == "__main__":
    # ^  This is a guard statement that will prevent the following code from
    #    being executed in the case someone imports this file instead of
    #    executing it as a script.
    #    https://docs.python.org/3/library/__main__.html

    # After installing your project with pip, users can also run your Python
    # modules as scripts via the ``-m`` flag, as defined in PEP 338::
    #
    #     python -m k8soptimizer.skeleton 42
    #
    run()
