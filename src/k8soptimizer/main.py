"""
This is a skeleton file that can serve as a starting point for a Python
console script. To run this script uncomment the following lines in the
``[options.entry_points]`` section in ``setup.cfg``::

    console_scripts =
         k8soptimizer = k8soptimizer.main:run

Then run ``pip install .`` (or ``pip install -e .`` for editable mode)
which will install the command ``k8soptimizer`` inside your current environment.

Besides console scripts, the header (i.e. until ``_logger``...) of this file can
also be used as template for Python modules.

Note:
    This file can be renamed depending on your needs or safely removed if not needed.

References:
    - https://setuptools.pypa.io/en/latest/userguide/entry_point.html
    - https://pip.pypa.io/en/stable/reference/pip_install
"""

import argparse
import json
import logging
import os
import re
import sys
import time

import requests
from beartype import beartype
from beartype.typing import Optional, Tuple
from kubernetes import client, config
from kubernetes.client.models import (
    V1Container,
    V1Deployment,
    V1DeploymentList,
    V1NamespaceList,
    V2HorizontalPodAutoscaler,
)
from pythonjsonlogger import jsonlogger

from . import __version__, helpers

__author__ = "Philipp Hellmich"
__copyright__ = "Arvato Systems GmbH"
__license__ = "MIT"

__domain__ = "arvato-aws.io"

_logger = logging.getLogger(__name__)


PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")

NAMESPACE_PATTERN = os.getenv("NAMESPACE_PATTERN", ".*")
DEPLOYMENT_PATTERN = os.getenv("DEPLOYMENT_PATTERN", ".*")
CONTAINER_PATTERN = os.getenv("CONTAINER_PATTERN", ".*")

# in minutes
# cannot not be less than 5 minutes)
DEFAULT_LOOKBACK_MINUTES = int(os.getenv("DEFAULT_LOOKBACK_MINUTES", 60 * 4))
DEFAULT_OFFSET_MINUTES = int(
    os.getenv("DEFAULT_OFFSET_MINUTES", (60 * 24 * 7) - (DEFAULT_LOOKBACK_MINUTES))
)
DEFAULT_QUANTILE_OVER_TIME = float(os.getenv("DEFAULT_QUANTILE_OVER_TIME", 0.95))

DEFAULT_QUANTILE_OVER_TIME_STATIC_CPU = float(
    os.getenv("DEFAULT_QUANTILE_OVER_TIME_STATIC_CPU", 0.95)
)
DEFAULT_QUANTILE_OVER_TIME_HPA_CPU = float(
    os.getenv("DEFAULT_QUANTILE_OVER_TIME_HPA_CPU", 0.7)
)

DEFAULT_QUANTILE_OVER_TIME_STATIC_MEMORY = float(
    os.getenv("DEFAULT_QUANTILE_OVER_TIME_STATIC_MEMORY", 0.95)
)
DEFAULT_QUANTILE_OVER_TIME_HPA_MEMORY = float(
    os.getenv("DEFAULT_QUANTILE_OVER_TIME_HPA_MEMORY", 0.8)
)

# operating mode
DRY_RUN_MODE = os.getenv("DRY_RUN_MODE", "false").lower() in ["true", "1", "yes"]
CLUSTER_RUN_MODE = os.getenv("CLUSTER_RUN_MODE", "false").lower() in [
    "true",
    "1",
    "yes",
]

MIN_CPU_REQUEST = float(
    helpers.convert_cpu_request_to_cores(os.getenv("MIN_CPU_REQUEST", "10m"))
)  # below 10m will not work reliable with hpa
MAX_CPU_REQUEST = float(
    helpers.convert_cpu_request_to_cores(os.getenv("MAX_CPU_REQUEST", "16"))
)
MAX_CPU_REQUEST_NODEJS = 1.0
CPU_REQUEST_RATIO = float(os.getenv("CPU_REQUEST_RATIO", 1.0))

MIN_MEMORY_REQUEST = int(
    helpers.convert_memory_request_to_bytes(os.getenv("MIN_MEMORY_REQUEST", "16Mi"))
)
MAX_MEMORY_REQUEST = int(
    helpers.convert_memory_request_to_bytes(os.getenv("MAX_MEMORY_REQUEST", "16Gi"))
)

MEMORY_REQUEST_RATIO = float(os.getenv("MEMORY_REQUEST_RATIO", 1.5))
MEMORY_LIMIT_RATIO = float(os.getenv("MEMORY_LIMIT_RATIO", 2.0))
MIN_MEMORY_LIMIT = int(
    os.getenv("MIN_MEMORY_LIMIT", MIN_MEMORY_REQUEST * MEMORY_LIMIT_RATIO)
)
MAX_MEMORY_LIMIT = int(
    os.getenv("MAX_MEMORY_LIMIT", MAX_MEMORY_REQUEST * MEMORY_LIMIT_RATIO)
)
CHANGE_THRESHOLD = float(os.getenv("CHANGE_THRESHOLD", 0.1))
HPA_TARGET_REPLICAS_RATIO = float(os.getenv("HPA_TARGET_REPLICAS_RATIO", 0.1))

TREND_LOOKBOOK_MINUTES = int(os.getenv("TREND_LOOKBOOK_MINUTES", 60 * 4))
TREND_OFFSET_MINUTES = int(os.getenv("TREND_OFFSET_MINUTES", (60 * 24 * 7)))
TREND_MAX_RATIO = float(os.getenv("TREND_MAX_RATIO", 1.5))
TREND_MIN_RATIO = float(os.getenv("TREND_MIN_RATIO", 0.5))
TREND_QUANTILE_OVER_TIME = float(os.getenv("TREND_QUANTILE_OVER_TIME", 0.8))

DELAY_BETWEEN_UPDATES = float(os.getenv("DELAY_BETWEEN_UPDATES", 0.0))

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_FORMAT = os.getenv("LOG_FORMAT", "json").lower()

stats = {}
stats["old_cpu_sum"] = 0
stats["new_cpu_sum"] = 0
stats["old_memory_sum"] = 0
stats["new_memory_sum"] = 0
stats["old_memory_limits_sum"] = 0
stats["new_memory_limits_sum"] = 0

# ---- Python API ----
# The functions defined in this section can be imported by users in their
# Python scripts/interactive interpreter, e.g. via
# `from k8soptimizer.skeleton import fib`,
# when using this Python module as a library.


class AppFilter(logging.Filter):
    extra = {}

    def __init__(self, extra={}):
        self.extra = extra
        super(AppFilter, self).__init__()

    def filter(self, record):
        for key, value in self.extra.items():
            record.__setattr__(key, value)
        for key in list(record.__dict__.keys()):
            if key not in self.extra and key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
            ]:
                del record.__dict__[key]
        return True


@beartype
def query_prometheus(query: str) -> dict:
    """
    Query Prometheus API with the specified query string.

    Args:
        query (str): The Prometheus query string.

    Returns:
        dict: The JSON response from the Prometheus API.

    Raises:
        RuntimeError: If the response is missing expected data fields.

    Example:
        response = query_prometheus('sum(rate(http_requests_total{job="api"}[5m]))')
    """
    _logger.debug("Query to prometheus: %s", query)
    response = requests.get(PROMETHEUS_URL + "/api/v1/query", params={"query": query})
    j = json.loads(response.text)
    _logger.debug("Response from prometheus: %s", j)
    if "data" not in j:
        raise RuntimeError("Got invalid results from query: {}".format(query))
    if "result" not in j["data"]:
        raise RuntimeError("Got invalid results from query: {}".format(query))
    return j


@beartype
def verify_prometheus_connection() -> bool:
    """
    Verify connection to the Prometheus API.

    Returns:
        bool: True if the connection is successful, False otherwise.

    Raises:
        RuntimeError: If the response is missing expected data fields or the connection fails.

    Example:
        connection_successful = verify_prometheus_connection()
    """
    response = requests.get(PROMETHEUS_URL + "/api/v1/status/buildinfo")
    j = json.loads(response.text)
    _logger.debug(j)
    if "status" not in j:
        raise RuntimeError("Got invalid results request: {}".format(response.text))
    if j["status"] == "success":
        return True
    raise RuntimeError("Connection to prometheus api failed")


@beartype
def verify_kubernetes_connection() -> bool:
    """
    Verify connection to the Kubernetes API.

    Returns:
        bool: True if the connection is successful, False otherwise.

    Raises:
        RuntimeError: If the connection to the Kubernetes API fails or if there is a configuration error.

    Example:
        connection_successful = verify_kubernetes_connection()
    """
    if CLUSTER_RUN_MODE:
        config.load_incluster_config()
    else:
        config.load_kube_config()
    client.ApisApi().get_api_versions_with_http_info()
    return True


@beartype
def get_max_cpu_cores_per_runtime(runtime: str) -> int:
    """
    Get the maximum number of CPU cores allowed per runtime.

    Args:
        runtime (str): The name of the runtime.

    Returns:
        int: The maximum number of CPU cores.

    Example:
        max_cores = get_max_cpu_cores_per_runtime("nodejs")
    """
    if runtime == "nodejs":
        return 1
    return 100


@beartype
def format_offset_minutes(offset_minutes: int) -> str:
    """
    Get the offset minutes as a string for Prometheus queries.

    Args:
        offset_minutes (int): The offset minutes.

    Returns:
        str: The offset minutes as a string.

    Example:
        offset_minutes_str = get_offset_minutes_str(5)
    """
    if offset_minutes == 0:
        return ""
    return "offset {}m".format(offset_minutes)


@beartype
def get_number_of_samples_from_history(
    namespace: str,
    workload: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
) -> int:
    """
    Get the CPU cores usage history for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.

    Returns:
        float: The number of samples from prometheus.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        samples = get_number_of_samples_from_history("my-namespace", "my-deployment")
    """
    query = 'max by (namespace,workload,workload_type) (count_over_time(kube_workload_container_resource_usage_cpu_cores_avg{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}"}}[{lookback_minutes}m] {offset_minutes_str}))'.format(
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        lookback_minutes=lookback_minutes,
        offset_minutes_str=format_offset_minutes(offset_minutes),
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return int(j["data"]["result"][0]["value"][1])


# FIXME not used anymore
@beartype
def get_max_pods_per_deployment_history(
    namespace_name: str,
    deployment_name: str,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> int:
    """
    Get the maximum number of pods for a deployment based on historical data.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        int: The maximum number of pods.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        max_pods = get_max_pods_per_deployment_history("my-namespace", "my-deployment")
    """
    query = 'max(quantile_over_time({quantile_over_time}, kube_deployment_spec_replicas{{job="kube-state-metrics", namespace="{namespace_name}", deployment="{deployment_name}"}}[{lookback_minutes}m] {offset_minutes_str}))'.format(
        quantile_over_time=quantile_over_time,
        namespace_name=namespace_name,
        deployment_name=deployment_name,
        lookback_minutes=lookback_minutes,
        offset_minutes_str=format_offset_minutes(offset_minutes),
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return int(j["data"]["result"][0]["value"][1])


@beartype
def get_cpu_cores_usage_history(
    namespace: str,
    workload: str,
    container: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
    metric: str = "kube_workload_container_resource_usage_cpu_cores_avg",
) -> float:
    """
    Get the CPU cores usage history for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.
        metric (str, optional): The metric used for the query. Default is "kube_workload_container_resource_usage_cpu_cores_avg".


    Returns:
        float: The CPU cores usage value.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        cpu_usage = get_cpu_cores_usage_history("my-namespace", "my-deployment", "my-container")
    """
    query = 'quantile_over_time({quantile_over_time}, {metric}{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m] {offset_minutes_str})'.format(
        quantile_over_time=quantile_over_time,
        metric=metric,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
        offset_minutes_str=format_offset_minutes(offset_minutes),
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


@beartype
def get_memory_bytes_usage_history(
    namespace: str,
    workload: str,
    container: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
    metric: str = "kube_workload_container_resource_usage_memory_bytes_max",
) -> float:
    """
    Get the memory usage history (in bytes) for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.
        metric (str, optional): The metric used for the query. Default is "kube_workload_container_resource_usage_memory_bytes_max".


    Returns:
        float: The memory usage value in bytes.

    Raises:
        RuntimeError: If no data is found for the Prometheus query.

    Example:
        memory_usage = get_memory_bytes_usage_history("my-namespace", "my-deployment", "my-container")
    """
    query = 'quantile_over_time({quantile_over_time}, {metric}{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m] {offset_minutes_str})'.format(
        quantile_over_time=quantile_over_time,
        metric=metric,
        namespace=namespace,
        workload=workload,
        workload_type=workload_type,
        container=container,
        lookback_minutes=lookback_minutes,
        offset_minutes_str=format_offset_minutes(offset_minutes),
    )
    j = query_prometheus(query)

    if j["data"]["result"] == []:
        raise RuntimeError("No data found for prometheus query: {}".format(query))
    return float(j["data"]["result"][0]["value"][1])


@beartype
def discover_container_runtime(
    namespace: str, workload: str, container: str, workload_type: str = "deployment"
) -> Optional[str]:
    """
    Discover the container runtime for a specific container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".

    Returns:
        Optional[str]: The name of the container runtime, or None if it couldn't be determined.

    Example:
        runtime = discover_container_runtime("my-namespace", "my-deployment", "my-container")
    """
    if is_nodejs_container(namespace, workload, container, workload_type):
        return "nodejs"
    return None


@beartype
def get_hpa_for_deployment(
    namespace_name: str, deployment_name: str
) -> Optional[V2HorizontalPodAutoscaler]:
    """
    Get the Horizontal Pod Autoscaler (HPA) associated with a specific deployment.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.

    Returns:
        Optional[V2HorizontalPodAutoscaler]: The HPA object if found, or None if not found.

    Example:
        hpa = get_hpa_for_deployment("my-namespace", "my-deployment")
    """
    autoscaling_api = client.AutoscalingV2Api()
    _logger.debug("Listing HPA for namespace: %s" % namespace_name)
    for hpa in autoscaling_api.list_namespaced_horizontal_pod_autoscaler(
        namespace=namespace_name
    ).items:
        _logger.debug(hpa)
        if hpa.spec.scale_target_ref.kind != "Deployment":
            continue
        if hpa.spec.scale_target_ref.name != deployment_name:
            continue
        return hpa
    return None


@beartype
def is_hpa_enabled_for_deployment(namespace_name: str, deployment_name: str) -> bool:
    """
    Check if Horizontal Pod Autoscaling (HPA) is enabled for a specific deployment.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.

    Returns:
        bool: True if HPA is enabled, False otherwise.

    Example:
        hpa_enabled = is_hpa_enabled_for_deployment("my-namespace", "my-deployment")
    """
    return get_hpa_for_deployment(namespace_name, deployment_name) is not None


@beartype
def calculate_quantile_over_time(namespace_name: str, deployment_name: str) -> dict:
    """
    Calculate the target ratio for Horizontal Pod Autoscaling (HPA) based on historical data.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deployment_name (str): The name of the deployment.
        lookback_minutes (int, optional): The number of minutes to look back in time for historical data. Default is DEFAULT_LOOKBACK_MINUTES.

    Returns:
        dict: A dictionary with target ratios for CPU and memory.

    Example:
        target_ratios = calculate_hpa_target_ratio("my-namespace", "my-deployment")
    """

    target_quantile_cpu = DEFAULT_QUANTILE_OVER_TIME_STATIC_CPU
    target_quantile_memory = DEFAULT_QUANTILE_OVER_TIME_STATIC_MEMORY

    hpa = get_hpa_for_deployment(namespace_name, deployment_name)
    if hpa is None:
        _logger.debug("Hpa not found for: %s" % deployment_name)
        return {
            "cpu": float(target_quantile_cpu),
            "memory": float(target_quantile_memory),
        }

    for metric in hpa.spec.metrics:
        if metric.type != "Resource":
            continue
        if metric.resource.name == "cpu":
            target_quantile_cpu = DEFAULT_QUANTILE_OVER_TIME_HPA_CPU
        if metric.resource.name == "memory":
            target_quantile_memory = DEFAULT_QUANTILE_OVER_TIME_HPA_MEMORY

    return {"cpu": float(target_quantile_cpu), "memory": float(target_quantile_memory)}


def calculate_target_replicas(deployment: V1Deployment) -> int:
    """
    Calculate the target number of replicas for a specific deployment based on historical data.

    Args:
        deployment_name (V1DeploymentList): The deployment.
        lookback_minutes (int, optional): The number of minutes to look back in time for historical data. Default is DEFAULT_LOOKBACK_MINUTES.

    Returns:
        int: The target number of replicas.

    Example:
        target_replicas = calculate_target_replicas("my-namespace", "my-deployment")
    """

    hpa = get_hpa_for_deployment(
        deployment.metadata.namespace, deployment.metadata.name
    )
    if hpa is None:
        _logger.debug("Hpa not found for: %s" % deployment.metadata.name)
        return deployment.spec.replicas

    target_replicas = hpa.spec.max_replicas * HPA_TARGET_REPLICAS_RATIO

    _logger.debug("Target replicas before limits: %s" % target_replicas)
    _logger.debug("Hpa min replicas: %s" % hpa.spec.min_replicas)
    _logger.debug("Hpa max replicas: %s" % hpa.spec.max_replicas)

    return round(
        max(
            hpa.spec.min_replicas,
            min(hpa.spec.max_replicas, target_replicas),
        )
    )


@beartype
def calculate_cpu_trend(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    lookback_minutes: int = TREND_LOOKBOOK_MINUTES,
    offset_minutes: int = TREND_OFFSET_MINUTES,
    quantile_over_time: float = TREND_QUANTILE_OVER_TIME,
) -> float:
    """
    Calculate the CPU requests for a specific container based on historical data compared to today

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        workload_type (str): The type of workload (e.g., deployment,daemonset,statefulset).
        container_name (str): The name of the container.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        float: The calculated CPU requests.

    Example:
        cpu_requests = calculate_cpu_trend("my-namespace", "my-workload", "deployment", "my-container", 1.5, 60)
    """

    cpu_today = get_cpu_cores_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        0,
        quantile_over_time,
        "kube_workload_container_resource_usage_cpu_cores_sum",
    )

    cpu_weekago = get_cpu_cores_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
        "kube_workload_container_resource_usage_cpu_cores_sum",
    )

    trend = round(cpu_today / cpu_weekago, 3)

    _logger.debug("CPU trend raw: %s" % trend)

    trend = max(
        TREND_MIN_RATIO, min(TREND_MAX_RATIO, round(cpu_today / cpu_weekago, 3))
    )

    _logger.debug("CPU trend limited: %s" % trend)

    return float(trend)


@beartype
def calculate_cpu_requests(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    target_replicas: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> float:
    """
    Calculate the CPU requests for a specific container based on historical data and target ratio.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        workload_type (str): The type of workload (e.g., deployment,daemonset,statefulset).
        container_name (str): The name of the container.
        target_replicas (int): The target replica count.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        float: The calculated CPU requests.

    Example:
        cpu_requests = calculate_cpu_requests("my-namespace", "my-workload", "deployment", "my-container", 1.5, 60)
    """

    trend = calculate_cpu_trend(namespace_name, workload, workload_type, container_name)

    history = get_cpu_cores_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
        "kube_workload_container_resource_usage_cpu_cores_sum",
    )

    _logger.debug("CPU trend: %s" % trend)
    _logger.debug("CPU history: %s" % history)

    new_cpu = round(
        max(
            MIN_CPU_REQUEST,
            min(
                MAX_CPU_REQUEST,
                history / target_replicas * trend * CPU_REQUEST_RATIO,
            ),
        ),
        3,
    )
    runtime = discover_container_runtime(
        namespace_name, workload, container_name, workload_type
    )
    _logger.debug("Runtime: %s" % runtime)
    if runtime == "nodejs":
        new_cpu = min(MAX_CPU_REQUEST_NODEJS, new_cpu)

    return float(new_cpu)


@beartype
def calculate_memory_trend(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    lookback_minutes: int = TREND_LOOKBOOK_MINUTES,
    offset_minutes: int = TREND_OFFSET_MINUTES,
    quantile_over_time: float = TREND_QUANTILE_OVER_TIME,
):
    """
    Calculate the memory requests for a specific container based on historical data, target ratio, and OOM history.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        workload_type (str): The type of workload (e.g., deployment,daemonset,statefulset).
        container_name (str): The name of the container.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        int: The calculated memory requests in bytes.

    Example:
        memory_requests = calculate_memory_requests("my-namespace", "my-workload", "deployment", "my-container", 1.5, 60)
    """

    memory_today = get_memory_bytes_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        0,
        quantile_over_time,
        "kube_workload_container_resource_usage_memory_bytes_avg",
    )

    memory_weekago = get_memory_bytes_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
        "kube_workload_container_resource_usage_memory_bytes_avg",
    )

    trend = round(memory_today / memory_weekago, 3)

    _logger.debug("Memory trend raw: %s" % trend)

    trend = max(
        TREND_MIN_RATIO, min(TREND_MAX_RATIO, round(memory_today / memory_weekago, 3))
    )

    _logger.debug("Memory trend limited: %s" % trend)

    return float(trend)


@beartype
def calculate_memory_requests(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    target_replicas: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
):
    """
    Calculate the memory requests for a specific container based on historical data, target ratio, and OOM history.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        workload_type (str): The type of workload (e.g., deployment,daemonset,statefulset).
        container_name (str): The name of the container.
        target_replicas (int): The target replica count.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        int: The calculated memory requests in bytes.

    Example:
        memory_requests = calculate_memory_requests("my-namespace", "my-workload", "deployment", "my-container", 1.5, 60)
    """
    oom_ratio = 1
    if (
        get_oom_killed_history(
            namespace_name, workload, container_name, workload_type, lookback_minutes
        )
        > 0
    ):
        quantile_over_time = 0.99
        oom_ratio = 1.5

    trend = calculate_memory_trend(
        namespace_name, workload, workload_type, container_name
    )

    history = get_memory_bytes_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
        "kube_workload_container_resource_usage_memory_bytes_avg",
    )

    new_memory = round(
        max(
            MIN_MEMORY_REQUEST,
            min(
                MAX_MEMORY_REQUEST,
                history * trend * oom_ratio * MEMORY_REQUEST_RATIO,
            ),
        )
    )

    return int(new_memory)


@beartype
def calculate_memory_limits(
    namespace_name: str,
    workload: str,
    workload_type: str,
    container_name: str,
    target_replicas: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    quantile_over_time: float = 0.99,
) -> int:
    """
    Calculate the memory limits for a specific container based on memory requests.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        workload_type (str): The type of workload (e.g., deployment,daemonset,statefulset).
        container_name (str): The name of the container.
        target_replicas (int): The target replica count.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.
        quantile_over_time (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.

    Returns:
        int: The calculated memory limits in bytes.

    Example:
        memory_limits = calculate_memory_limits("my-namespace", "my-workload", "deployment", "my-container", 2048)
    """
    oom_ratio = 1
    if (
        get_oom_killed_history(
            namespace_name, workload, container_name, workload_type, lookback_minutes
        )
        > 0
    ):
        quantile_over_time = 0.99
        oom_ratio = 2

    trend = calculate_memory_trend(
        namespace_name, workload, workload_type, container_name
    )

    history = get_memory_bytes_usage_history(
        namespace_name,
        workload,
        container_name,
        workload_type,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
        "kube_workload_container_resource_usage_memory_bytes_max",
    )

    new_memory = round(
        max(
            MIN_MEMORY_LIMIT,
            min(
                MAX_MEMORY_LIMIT,
                history * trend * oom_ratio * MEMORY_LIMIT_RATIO,
            ),
        )
    )

    return int(new_memory)


@beartype
def get_namespaces(namespace_pattern: str = ".*") -> V1NamespaceList:
    """
    Get a list of Kubernetes namespaces that match the specified pattern.

    Args:
        namespace_pattern (str, optional): A regular expression pattern to filter namespaces. Default is ".*".

    Returns:
        V1NamespaceList: A list of namespaces.

    Example:
        namespaces = get_namespaces("my-namespace.*")
    """
    core_api = client.CoreV1Api()
    resp_ns = core_api.list_namespace(watch=False)
    items = []

    for namespace in resp_ns.items:
        _logger.debug(namespace)
        namespace_name = namespace.metadata.name

        x = re.search(namespace_pattern, namespace_name)
        if x is None:
            _logger.debug(
                "Skipping namespace due to NAMESPACE_PATTERN: %s" % namespace_name
            )
            continue

        items.append(namespace)

    return V1NamespaceList(items=items)


@beartype
def get_deployments(
    namespace_name: str, deplopyment_pattern: str = ".*", only_running: bool = True
) -> V1DeploymentList:
    """
    Get a list of Kubernetes deployments in a specific namespace that match the specified pattern.

    Args:
        namespace_name (str): The name of the Kubernetes namespace.
        deplopyment_pattern (str, optional): A regular expression pattern to filter deployments. Default is ".*".
        only_running (bool, optional): Flag to include only running deployments. Default is True.

    Returns:
        V1DeploymentList: A list of deployments.

    Example:
        deployments = get_deployments("my-namespace", "my-deployment.*", only_running=True)
    """
    apis_api = client.AppsV1Api()
    resp_deploy = apis_api.list_namespaced_deployment(namespace=namespace_name)
    items = []
    for deployment in resp_deploy.items:
        _logger.debug(deployment)
        deployment_name = deployment.metadata.name

        x = re.search(deplopyment_pattern, deployment_name)
        if x is None:
            _logger.debug(
                "Skipping deployment due to DEPLOYMENT_PATTERN: %s" % deployment_name
            )
            continue

        if only_running and deployment.spec.replicas == 0:
            _logger.debug(
                "Skipping deployment due to zero replicas: %s" % deployment_name
            )
            continue

        items.append(deployment)

    return V1DeploymentList(items=items)


@beartype
def get_oom_killed_history(
    namespace: str,
    workload: str,
    container: str,
    workload_type: str = "deployment",
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> int:
    """
    Get the count of out-of-memory (OOM) events for a specific container based on historical data.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.

    Returns:
        int: The count of OOM events.

    Example:
        oom_count = get_oom_killed_history("my-namespace", "my-workload", "my-container", "deployment", 60)
    """
    query = 'sum_over_time(kube_workload_container_resource_usage_memory_oom_killed{{namespace="{namespace}", workload="{workload}", workload_type="{workload_type}", container="{container}"}}[{lookback_minutes}m])'.format(
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
        return round(float(j["data"]["result"][0]["value"][1]))

    return 0


@beartype
def is_nodejs_container(
    namespace: str, workload: str, container: str, workload_type: str = "deployment"
) -> bool:
    """
    Check if a container in a specific workload and namespace is a Node.js container.

    Args:
        namespace (str): The name of the Kubernetes namespace.
        workload (str): The name of the workload (e.g., myapp).
        container (str): The name of the container.
        workload_type (str, optional): The type of workload. Default is "deployment".

    Returns:
        bool: True if the container is a Node.js container, False otherwise.

    Example:
        is_nodejs = is_nodejs_container("my-namespace", "my-workload", "my-container", "deployment")
    """
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


@beartype
def get_resources_from_deployment(deployment: V1Deployment) -> dict:
    """
    Get resource specifications (requests and limits) for containers in a deployment.

    Args:
        deployment (V1Deployment): The Kubernetes deployment object.

    Returns:
        dict: A dictionary containing resource specifications for each container.

    Example:
        deployment = get_deployment_by_name("my-namespace", "my-deployment")
        resources = get_resources_from_deployment(deployment)
    """
    res = {}
    for container in deployment.spec.template.spec.containers:
        res[container.name] = {}
        try:
            res[container.name]["requests"] = container.resources.requests
        except AttributeError:
            res[container.name]["requests"] = {}
        try:
            res[container.name]["limits"] = container.resources.limits
        except AttributeError:
            res[container.name]["limits"] = {}
    return res


@beartype
def optimize_deployment(
    deployment: V1Deployment,
    container_pattern=CONTAINER_PATTERN,
    lookback_minutes=DEFAULT_LOOKBACK_MINUTES,
    offset_minutes=DEFAULT_OFFSET_MINUTES,
    dry_run=True,
) -> V1Deployment:
    """
    Optimize the resources (CPU and memory) for containers in a deployment.

    Args:
        deployment (V1Deployment): The Kubernetes deployment object to be optimized.
        dry_run (bool, optional): If True, the optimization changes will be simulated (dry-run mode).
                                 If False, the changes will be applied. Default is True.

    Returns:
        V1Deployment: The optimized Kubernetes deployment object.

    Example:
        deployment = get_deployment_by_name("my-namespace", "my-deployment")
        optimized_deployment = optimize_deployment(deployment, dry_run=True)
    """
    apis_api = client.AppsV1Api()
    namespace_name = deployment.metadata.namespace
    deployment_name = deployment.metadata.name

    extra = {"namespace": namespace_name, "deployment": deployment_name}
    _logger.addFilter(AppFilter(extra))
    # _logger = logging.LoggerAdapter(_logger, extra)

    _logger.info("Optimizing deployment: %s" % deployment_name)

    if deployment.spec.replicas == 0:
        _logger.warn("Skipping deployment due to zero replicas: %s" % deployment_name)
        return deployment

    old_resources = get_resources_from_deployment(deployment)
    lookback_minutes = DEFAULT_LOOKBACK_MINUTES
    offset_minutes = DEFAULT_OFFSET_MINUTES
    target_replicas = calculate_target_replicas(deployment)
    target_quantile_over_time = calculate_quantile_over_time(
        namespace_name, deployment_name
    )

    _logger.info("Target replicas: %s" % target_replicas)

    _logger.debug(
        "target_quantile_over_time cpu: %s" % target_quantile_over_time["cpu"]
    )
    _logger.debug(
        "target_quantile_over_time memory: %s" % target_quantile_over_time["memory"]
    )
    changed = False
    for i, container in enumerate(deployment.spec.template.spec.containers):
        container_name = container.name
        extra = {
            "namespace": namespace_name,
            "deployment": deployment_name,
            "container": container_name,
        }
        _logger.addFilter(AppFilter(extra))

        _logger.debug("Filtering containers using pattern: %s" % container_pattern)
        x = re.search(container_pattern, container_name)
        if x is None:
            _logger.debug(
                "Skipping container due to CONTAINER_PATTERN: %s" % container_name
            )
            continue

        container_new, changed_container = optimize_container(
            namespace_name,
            deployment_name,
            container,
            "deployment",
            target_quantile_over_time["cpu"],
            target_quantile_over_time["memory"],
            target_replicas,
            lookback_minutes,
            offset_minutes,
        )
        if changed_container:
            changed = True
        deployment.spec.template.spec.containers[i] = container_new

    extra = {"namespace": namespace_name, "deployment": deployment_name}
    _logger.addFilter(AppFilter(extra))

    if changed:
        deployment.metadata.annotations[
            "k8soptimizer.{}/old-resources".format(__domain__)
        ] = json.dumps(old_resources)
        deployment.metadata.annotations[
            "k8soptimizer.{}/last-update".format(__domain__)
        ] = helpers.create_timestamp()

        # Apply the changes
        if dry_run is True:
            _logger.info("Updating (dry-run) deployment: %s" % deployment_name)
            apis_api.patch_namespaced_deployment(
                deployment_name,
                namespace_name,
                deployment,
                pretty=True,
                dry_run="All",
            )
        else:
            _logger.info("Updating deployment: %s" % deployment_name)
            apis_api.patch_namespaced_deployment(
                deployment_name, namespace_name, deployment, pretty=True
            )
    else:
        _logger.info("Nothing changed deployment: %s" % deployment_name)
    return deployment


@beartype
def optimize_container(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    quantile_over_time_cpu: float = DEFAULT_QUANTILE_OVER_TIME,
    quantile_over_time_memory: float = DEFAULT_QUANTILE_OVER_TIME,
    target_repliacs: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
) -> Tuple[V1Container, bool]:
    """
    Optimize resources (CPU and memory) for a container.

    Args:
        namespace_name (str): The namespace of the container.
        workload (str): The name of the workload associated with the container.
        container (V1Container): The Kubernetes container object to be optimized.
        workload_type (str, optional): The type of workload (e.g., "deployment"). Default is "deployment".
        quantile_over_time_cpu (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.
        quantile_over_time_memory (float, optional): The quantile value for the query. Default is DEFAULT_QUANTILE_OVER_TIME.
        lookback_minutes (int, optional): The number of minutes to look back in time for the query. Default is DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The offset in minutes for the query. Default is DEFAULT_OFFSET_MINUTES.

    Returns:
        V1Container: The optimized Kubernetes container object.
        changed (bool): True if the container was changed, False otherwise.

    Example:
        namespace = "my-namespace"
        workload = "my-workload"
        container = get_container_by_name(namespace, workload, "my-container")
        optimized_container = optimize_container(namespace, workload, container, target_ratio_cpu=0.8)
    """
    container_name = container.name

    _logger.info("Processing container: %s" % container_name)

    old_cpu = get_cpu_requests_from_container(container)

    new_cpu, changed_cpu = optimize_container_cpu_requests(
        namespace_name,
        workload,
        container,
        workload_type,
        target_repliacs,
        lookback_minutes,
        offset_minutes,
        quantile_over_time_cpu,
    )
    old_memory = get_memory_requests_from_container(container)
    new_memory, changed_memory = optimize_container_memory_requests(
        namespace_name,
        workload,
        container,
        workload_type,
        target_repliacs,
        lookback_minutes,
        offset_minutes,
        quantile_over_time_memory,
    )
    old_memory_limit = get_memory_limits_from_container(container)
    new_memory_limit, changed_memory_limit = optimize_container_memory_limits(
        namespace_name,
        workload,
        container,
        workload_type,
        target_repliacs,
        lookback_minutes,
        offset_minutes,
    )

    if changed_cpu:
        stats["new_cpu_sum"] += new_cpu * target_repliacs
    else:
        stats["new_cpu_sum"] += old_cpu * target_repliacs

    if changed_memory:
        stats["new_memory_sum"] += new_memory * target_repliacs
    else:
        stats["new_memory_sum"] += old_memory * target_repliacs

    if changed_memory_limit:
        stats["new_memory_limits_sum"] += new_memory_limit * target_repliacs
    else:
        stats["new_memory_limits_sum"] += old_memory_limit * target_repliacs

    stats["old_cpu_sum"] += old_cpu * target_repliacs
    stats["old_memory_sum"] += old_memory * target_repliacs
    stats["old_memory_limits_sum"] += old_memory_limit * target_repliacs

    container.resources.requests["cpu"] = str(round(new_cpu * 1000)) + "m"
    if "cpu" in container.resources.limits:
        del container.resources.limits["cpu"]
        changed_cpu_limit = True
    else:
        changed_cpu_limit = False
    container.resources.requests["memory"] = str(round(new_memory / 1024 / 1024)) + "Mi"
    container.resources.limits["memory"] = (
        str(round(new_memory_limit / 1024 / 1024)) + "Mi"
    )

    _logger.debug(
        [changed_cpu, changed_cpu_limit, changed_memory, changed_memory_limit]
    )

    return container, any(
        [changed_cpu, changed_cpu_limit, changed_memory, changed_memory_limit]
    )


@beartype
def get_cpu_requests_from_container(container: V1Container) -> float:
    """
    Get the CPU requests from a Kubernetes container.

    Args:
        container (V1Container): The Kubernetes container object.

    Returns:
        float: The CPU requests in cores.

    Example:
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"cpu": "100m"}))
        cpu_requests = get_cpu_requests_from_container(container)
    """
    try:
        old_cpu = helpers.convert_cpu_request_to_cores(
            container.resources.requests["cpu"]
        )
    except (KeyError, AttributeError):
        old_cpu = 0.001
    return float(old_cpu)


@beartype
def get_memory_requests_from_container(container: V1Container) -> int:
    """
    Get the memory requests from a Kubernetes container.

    Args:
        container (V1Container): The Kubernetes container object.

    Returns:
        int: The memory requests in bytes.

    Example:
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"memory": "2Gi"}))
        memory_requests = get_memory_requests_from_container(container)
    """
    try:
        old_memory = helpers.convert_memory_request_to_bytes(
            container.resources.requests["memory"]
        )
    except (KeyError, AttributeError):
        old_memory = 1024**2 * 1
    return int(old_memory)


@beartype
def get_memory_limits_from_container(container: V1Container) -> int:
    """
    Get the memory limits from a Kubernetes container.

    Args:
        container (V1Container): The Kubernetes container object.

    Returns:
        int: The memory limits in bytes.

    Example:
        container = V1Container(name="my-container", resources=V1ResourceRequirements(limits={"memory": "4Gi"}))
        memory_limits = get_memory_limits_from_container(container)
    """
    try:
        old_memory = helpers.convert_memory_request_to_bytes(
            container.resources.limits["memory"]
        )
    except (KeyError, AttributeError):
        old_memory = 1024**2 * 1
    return int(old_memory)


@beartype
def optimize_container_cpu_requests(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    target_replicas: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> Tuple[float, bool]:
    """
    Optimize CPU requests for a Kubernetes container.

    Args:
        namespace_name (str): The namespace of the workload.
        workload (str): The name of the workload.
        container (V1Container): The Kubernetes container object.
        workload_type (str, optional): The type of workload. Defaults to "deployment".
        target_ratio (float, optional): The target ratio for CPU optimization. Defaults to 1.
        lookback_minutes (int, optional): The number of minutes to look back for resource usage data. Defaults to DEFAULT_LOOKBACK_MINUTES.

    Returns:
        float: The new CPU request in cores.
        bool: If something was changed

    Example:
        namespace_name = "my-namespace"
        workload = "my-workload"
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"cpu": "100m"}))
        new_cpu = optimize_container_cpu_requests(namespace_name, workload, container)
    """
    container_name = container.name
    _logger.debug("Optimizingg container cpu requests: %s" % container_name)

    try:
        old_cpu = helpers.convert_cpu_request_to_cores(
            container.resources.requests["cpu"]
        )
        _logger.debug("Current cpu request: %s", old_cpu)
    except (KeyError, AttributeError):
        _logger.info("Could not read old CPU requests aassuming it is 0.001")
        old_cpu = 0.001

    new_cpu = calculate_cpu_requests(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_replicas,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
    )
    _logger.debug("New cpu request: %s", new_cpu)

    diff_cpu = round(((new_cpu / old_cpu) - 1) * 100)
    change_too_small = abs(diff_cpu) < CHANGE_THRESHOLD * 100

    if change_too_small:
        _logger.info("CPU requests change is too small: {}%".format(diff_cpu))
        new_cpu = old_cpu
    else:
        _logger.info(
            "CPU requests change: {} -> {} ({}%)".format(
                str(round(old_cpu * 1000)) + "m",
                str(round(new_cpu * 1000)) + "m",
                diff_cpu,
            )
        )

    return float(new_cpu), not change_too_small


@beartype
def optimize_container_memory_requests(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    target_replicas: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
    quantile_over_time: float = DEFAULT_QUANTILE_OVER_TIME,
) -> Tuple[int, bool]:
    """
    Optimize memory requests for a Kubernetes container.

    Args:
        namespace_name (str): The namespace of the workload.
        workload (str): The name of the workload.
        container (V1Container): The Kubernetes container object.
        workload_type (str, optional): The type of workload. Defaults to "deployment".
        target_ratio (float, optional): The target ratio for memory optimization. Defaults to 1.
        lookback_minutes (int, optional): The number of minutes to look back for resource usage data. Defaults to DEFAULT_LOOKBACK_MINUTES.
        offset_minutes (int, optional): The number of minutes to look back for resource usage data. Defaults to offset_minutes.

    Returns:
        int: The new memory request in bytes.
        bool: If something was changed

    Example:
        namespace_name = "my-namespace"
        workload = "my-workload"
        container = V1Container(name="my-container", resources=V1ResourceRequirements(requests={"memory": "1Gi"}))
        new_memory = optimize_container_memory_requests(namespace_name, workload, container)
    """
    container_name = container.name
    _logger.debug("Optimizingg container memory request: %s" % container_name)

    try:
        old_memory = helpers.convert_memory_request_to_bytes(
            container.resources.requests["memory"]
        )
        _logger.debug("Current memory request: %s", old_memory)
    except (KeyError, AttributeError):
        _logger.info("Could not read old meory requests aassuming it is 1")
        old_memory = 1

    new_memory = calculate_memory_requests(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_replicas,
        lookback_minutes,
        offset_minutes,
        quantile_over_time,
    )
    _logger.debug("New memory request: %s", new_memory)

    diff_memory = round(((new_memory / old_memory) - 1) * 100)
    change_too_small = abs(diff_memory) < CHANGE_THRESHOLD * 100

    if change_too_small:
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
    return int(new_memory), not change_too_small


@beartype
def optimize_container_memory_limits(
    namespace_name: str,
    workload: str,
    container: V1Container,
    workload_type: str = "deployment",
    target_replicas: int = 1,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
    offset_minutes: int = DEFAULT_OFFSET_MINUTES,
) -> Tuple[int, bool]:
    """
    Optimize memory limits for a Kubernetes container.

    Args:
        namespace_name (str): The namespace of the workload.
        workload (str): The name of the workload.
        container (V1Container): The Kubernetes container object.
        workload_type (str, optional): The type of workload. Defaults to "deployment".
        new_memory (int, optional): The new memory request in bytes. Defaults to MIN_MEMORY_REQUEST.

    Returns:
        int: The new memory limit in bytes.
        bool: If something was changed

    Example:
        namespace_name = "my-namespace"
        workload = "my-workload"
        container = V1Container(name="my-container", resources=V1ResourceRequirements(limits={"memory": "2Gi"}))
        new_memory_limit = optimize_container_memory_limits(namespace_name, workload, container)
    """
    container_name = container.name
    _logger.debug("Optimizingg container memory limits: %s" % container_name)

    try:
        old_memory_limit = helpers.convert_memory_request_to_bytes(
            container.resources.limits["memory"]
        )
        _logger.debug("Current memory limit: %s", old_memory_limit)
    except (KeyError, AttributeError):
        _logger.info("Could not read old meory limits aassuming it is 1")
        old_memory_limit = 1

    new_memory_limit = calculate_memory_limits(
        namespace_name,
        workload,
        workload_type,
        container_name,
        target_replicas,
        lookback_minutes,
        offset_minutes,
    )

    _logger.debug("New memory linmit: %s", new_memory_limit)
    diff_memory_limit = round(((new_memory_limit / old_memory_limit) - 1) * 100)

    change_too_small = abs(diff_memory_limit) < CHANGE_THRESHOLD * 100

    if change_too_small:
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

    return int(new_memory_limit), not change_too_small


def print_stats():
    if stats["old_cpu_sum"] > 0 and stats["new_cpu_sum"] > 0:
        diff_cpu_sum = round(((stats["new_cpu_sum"] / stats["old_cpu_sum"]) - 1) * 100)

        _logger.info(
            "Summary cpu requests change: {} -> {} ({}%)".format(
                str(round(stats["old_cpu_sum"] * 1000)) + "m",
                str(round(stats["new_cpu_sum"] * 1000)) + "m",
                diff_cpu_sum,
            )
        )

    if stats["old_memory_sum"] > 0 and stats["new_memory_sum"] > 0:
        diff_memory_sum = round(
            ((stats["new_memory_sum"] / stats["old_memory_sum"]) - 1) * 100
        )

        _logger.info(
            "Summary memory requests change: {} -> {} ({}%)".format(
                str(round(stats["old_memory_sum"] / 1024 / 1024)) + "Mi",
                str(round(stats["new_memory_sum"] / 1024 / 1024)) + "Mi",
                diff_memory_sum,
            )
        )

    if stats["old_memory_limits_sum"] > 0 and stats["new_memory_limits_sum"] > 0:
        diff_memory_limits_sum = round(
            ((stats["new_memory_limits_sum"] / stats["old_memory_limits_sum"]) - 1)
            * 100
        )

        _logger.info(
            "Summary memory limits change: {} -> {} ({}%)".format(
                str(round(stats["old_memory_limits_sum"] / 1024 / 1024)) + "Mi",
                str(round(stats["new_memory_limits_sum"] / 1024 / 1024)) + "Mi",
                diff_memory_limits_sum,
            )
        )


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
    parser = argparse.ArgumentParser(description="k8soptimizer")
    parser.add_argument(
        "--version",
        action="version",
        version=f"k8soptimizer {__version__}",
    )

    parser.add_argument(
        "--log",
        "--log-level",
        action="store",
        default=LOG_LEVEL,
        help="Set loglevel.",
        dest="loglevel",
    )

    parser.add_argument(
        "--log-format",
        action="store",
        default=LOG_FORMAT,
        help="Set logformat (txt, json).",
        dest="logformat",
    )

    parser.add_argument(
        "--lookback-minutes",
        action="store",
        default=DEFAULT_LOOKBACK_MINUTES,
        type=int,  # Ensure the input is an integer
        help="Set the lookback time in minutes.",
        dest="lookback_minutes",
    )

    parser.add_argument(
        "--offset-minutes",
        action="store",
        default=DEFAULT_OFFSET_MINUTES,
        type=int,  # Ensure the input is an integer
        help="Set the offset time in minutes.",
        dest="offsett_minutes",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=DRY_RUN_MODE,
        help="Perform a dry run without making any actual changes.",
        dest="dry_run",
    )

    group_ns = parser.add_mutually_exclusive_group()
    group_ns.add_argument(
        "-n",
        "--namespace",
        action="store",
        help="Set namespace",
        dest="namespace",
        type=helpers.valid_k8s_name_arg,
    )
    group_ns.add_argument(
        "--namespace-pattern",
        action="store",
        default=NAMESPACE_PATTERN,
        help="Set namespace pattern (regex)",
        dest="namespace_pattern",
        type=helpers.valid_regex_arg,
    )

    group_ds = parser.add_mutually_exclusive_group()
    group_ds.add_argument(
        "-d",
        "--deployment",
        action="store",
        help="Set deployment",
        dest="deployment",
        type=helpers.valid_k8s_name_arg,
    )
    parser.add_argument(
        "--deployment-pattern",
        action="store",
        default=DEPLOYMENT_PATTERN,
        help="Set deployment pattern (regex)",
        dest="deplopyment_pattern",
        type=helpers.valid_regex_arg,
    )

    group_cs = parser.add_mutually_exclusive_group()
    group_cs.add_argument(
        "-c",
        "--container",
        action="store",
        help="Set container",
        dest="container",
        type=helpers.is_valid_k8s_name,
    )
    group_cs.add_argument(
        "--container-pattern",
        action="store",
        default=CONTAINER_PATTERN,
        help="Set container pattern (regex)",
        dest="container_pattern",
        type=helpers.valid_regex_arg,
    )

    return parser.parse_args(args)


def setup_logging(loglevel: str = "info", logformat: str = "json"):
    """Setup basic logging

    Args:
        loglevel (int): minimum loglevel for emitting messages
    """

    # logformat = "[%(asctime)s] %(levelname)s:%(name)s:%(message)s"
    # logging.basicConfig(
    #     level=loglevel, stream=sys.stdout, format=logformat, datefmt="%Y-%m-%d %H:%M:%S"
    # )

    logger = logging.getLogger()

    if logformat == "txt":
        log_handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s: %(name)s:%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    elif logformat == "json":
        log_handler = logging.StreamHandler(sys.stdout)
        formatter = jsonlogger.JsonFormatter(
            "%(timestamp)s %(levelname)s %(message)s ", timestamp=True
        )
    else:
        raise ValueError("Invalid logformat. Use 'txt' or 'json'.")

    log_handler.setFormatter(formatter)
    logger.addHandler(log_handler)
    logger.setLevel(loglevel.upper())


def main(args):
    """Wrapper allowing :func:`fib` to be called with string arguments in a CLI fashion

    Instead of returning the value from :func:`fib`, it prints the result to the
    ``stdout`` in a nicely formatted message.

    Args:
        args (List[str]): command line parameters as list of strings
            (for example  ``["--verbose", "42"]``).
    """
    args = parse_args(args)
    setup_logging(args.loglevel, args.logformat)
    extra = {}
    _logger.addFilter(AppFilter(extra))
    _logger.info("Starting k8soptimizer...")

    verify_kubernetes_connection()
    verify_prometheus_connection()

    namespace_pattern = args.namespace_pattern
    if args.namespace is not None:
        namespace_pattern = "^{}$".format(args.namespace)
    deplopyment_pattern = args.deplopyment_pattern
    if args.deployment is not None:
        deplopyment_pattern = "^{}$".format(args.deployment)
    container_pattern = args.container_pattern
    if args.container is not None:
        container_pattern = "^{}$".format(args.container)

    lookback_minutes = args.lookback_minutes
    offset_minutes = args.offsett_minutes
    _logger.info("Using namespace_pattern: %s" % namespace_pattern)
    _logger.info("Using deplopyment_pattern: %s" % deplopyment_pattern)
    _logger.info("Using container_pattern: %s" % container_pattern)
    _logger.info("Using lookback_minutes: %s" % lookback_minutes)
    _logger.info("Using offset_minutes: %s" % offset_minutes)
    _logger.info("Using dry_run: %s" % args.dry_run)
    _logger.info("Using cpu request min cores: %s" % MIN_CPU_REQUEST)
    _logger.info("Using cpu request max cores: %s" % MAX_CPU_REQUEST)
    _logger.info("Using cpu request ratio: %s" % CPU_REQUEST_RATIO)
    _logger.info("Using memory request min bytes: %s" % MIN_MEMORY_REQUEST)
    _logger.info("Using memory request max bytes: %s" % MAX_MEMORY_REQUEST)
    _logger.info("Using memory request ratio: %s" % MEMORY_REQUEST_RATIO)
    _logger.info("Using memory limit min: %s" % MIN_MEMORY_LIMIT)
    _logger.info("Using memory limit max: %s" % MAX_MEMORY_LIMIT)
    _logger.info("Using memory limit ratio: %s" % MEMORY_LIMIT_RATIO)
    _logger.info("Using hpa target replicas ratio: %s" % HPA_TARGET_REPLICAS_RATIO)

    for namespace in get_namespaces(namespace_pattern).items:
        extra = {"namespace": namespace.metadata.name}
        _logger.addFilter(AppFilter(extra))
        for deployment in get_deployments(
            namespace.metadata.name, deplopyment_pattern
        ).items:
            try:
                optimize_deployment(
                    deployment,
                    container_pattern,
                    lookback_minutes,
                    offset_minutes,
                    args.dry_run,
                )
                time.sleep(DELAY_BETWEEN_UPDATES)
            except Exception as e:
                _logger.warning(
                    "An error occurred while optimizing the deployment: %s" % str(e),
                    exc_info=True,
                )

    extra = {}
    _logger.addFilter(AppFilter(extra))

    print_stats()

    _logger.info("Finished k8soptimizer")


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
